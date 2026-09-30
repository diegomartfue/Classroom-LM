"""
ClassroomLM Backend - FastAPI Server
Handles AI tutoring requests with Claude + SymPy verification.
"""
import shutil
import os
import base64
import json
import logging
import uuid
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, UploadFile, File, HTTPException, Form, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from rag_pipeline import ingest_document, query_rag
import document_store
from document_store import DocumentError, DocumentForbidden
from feedback_store import FeedbackError, record_feedback
from check_work_store import record_check_work
import participants
import mock_stream
from pydantic import BaseModel
from claude_client import chat
from sympy_solver import extract_and_solve
from agents.orchestrator import OrchestratorAgent, DAILY_LIMIT_MESSAGE
from agents.work_checker import build_known_values, check_work
from utils.usage_tracker import DailyLimitReached
from utils.cost_tracker import estimate_route_cost, REPORT_ROUTES
from model_config import SONNET_MODEL
from response_utils import extract_text

logger = logging.getLogger("classroomlm.tutor")

load_dotenv()

# Paths anyone may reach without a participant code: liveness checks and the
# code check itself. Everything else can spend API money or reads/writes
# research data, so it needs a valid code.
_PUBLIC_PATHS = {"/", "/health", "/participant/verify"}


def participant_code(request: Request) -> str | None:
    """Global dependency: every non-public route requires a valid
    X-Participant-Code header. Returns the normalized code (the student's
    only identity anywhere on the server), or None on a public path."""
    if request.url.path in _PUBLIC_PATHS:
        return None
    code = participants.verify(request.headers.get(participants.HEADER))
    if code is None:
        raise HTTPException(status_code=401, detail="A valid participant code is required.")
    return code


def current_identity(request: Request) -> participants.Identity:
    """The caller's code and role (participant or professor). Only used on
    routes the global participant_code gate already protects."""
    ident = participants.identify(request.headers.get(participants.HEADER))
    if ident is None:
        raise HTTPException(status_code=401, detail="A valid participant code is required.")
    return ident


def require_professor(ident: participants.Identity = Depends(current_identity)) -> participants.Identity:
    if not ident.is_professor:
        raise HTTPException(status_code=403, detail="Only the professor can do that.")
    return ident


app = FastAPI(dependencies=[Depends(participant_code)])


def _cors_origins() -> list[str]:
    """CORS_ALLOWED_ORIGINS: comma-separated origins, e.g. the deployed
    frontend URL on the school server. Defaults to the local dev servers."""
    raw = os.environ.get("CORS_ALLOWED_ORIGINS", "")
    origins = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    return origins or ["http://localhost:5173", "http://localhost:3000"]


# Allow requests from the React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# REQUEST MODELS
# =============================================================================

class ChatRequest(BaseModel):
    message: str
    model: str = "claude"
    role: str = "student"      # "student" or "professor"
    conversation_history: list = []

class ChatResponse(BaseModel):
    response: str
    model_used: str
    sympy_result: dict | None = None
    sympy_verified: bool = False
    
class QueryRequest(BaseModel):
    question: str

class TutorRequest(BaseModel):
    message: str
    conversation_history: list = []
    student_model: dict = {}
    doc_ids: list[str] = []
    # Pilot: stable per-browser id (see frontend's studentId helper — there is
    # no real login system yet, see docs/pilot-plan.md) and the frontend's own
    # per-conversation id. Both optional so older frontend builds keep working;
    # the orchestrator generates a session_id and falls back to student_id
    # "default" when omitted.
    # Ignored: the server uses the verified X-Participant-Code instead, so a
    # client can never save records under anything but its own code.
    student_id: str | None = None
    session_id: str | None = None
    # Pilot item 7: set (1-4) on an explicit Hint-button tap. See
    # OrchestratorAgent._run_turn / _run_stream_events for how this forces a
    # deterministic Planner decision instead of the Router/Planner's own
    # judgment.
    hint_level: int | None = None

class TutorResponse(BaseModel):
    response: str
    decision: str
    student_model: dict
    diagram_image: str = ""
    diagram_svg: str | None = None
    route: str = ""
    metadata: dict

class FeedbackRequest(BaseModel):
    session_id: str
    turn_number: int
    rating: str  # "up" | "down"


class ParticipantVerifyRequest(BaseModel):
    code: str

class CheckWorkRequest(BaseModel):
    lines: list[str]
    # The parsed_input from the PROBLEM turn's "meta" event, handed back
    # unchanged. The solver's answers are looked up server-side (see
    # agents/solution_cache.py) and never sent to the browser.
    parsed_input: dict
    # The tutor turn this check followed, so the export can put the result
    # on that turn's row. Optional: a check is still answered without them.
    session_id: str | None = None
    turn_number: int | None = None

# =============================================================================
# ROUTES
# =============================================================================

@app.get("/")
def root():
    return {"status": "ClassroomLM backend running"}


@app.get("/health")
def health():
    api_key_set = bool(os.environ.get("ANTHROPIC_API_KEY"))
    return {
        "claude_api_configured": api_key_set,
    }


@app.post("/participant/verify")
def participant_verify_endpoint(request: ParticipantVerifyRequest):
    """Checks a participant code before the frontend saves it. Only says
    yes or no — never lists or hints at other valid codes."""
    ident = participants.identify(request.code)
    if ident is None:
        raise HTTPException(status_code=401, detail="That participant code isn't recognized.")
    return {"code": ident.code, "role": ident.role}


@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    """
    Main chat endpoint.
    1. Run SymPy verification if it's a math problem
    2. Send to Claude with SymPy result injected if available
    3. Return response + verification status
    """

    message = request.message
    sympy_result = None

    # Step 1 — Try SymPy verification
    sympy_result = extract_and_solve(message)

    # Step 2 — Inject SymPy result into message if verified
    augmented_message = message
    if sympy_result:
        augmented_message = f"""{message}

[SYMPY VERIFIED RESULT]
Type: {sympy_result['type']}
Input: {sympy_result['input']}
Answer: {', '.join(sympy_result['solution']) if isinstance(sympy_result['solution'], list) else sympy_result['solution']}

Use this verified answer in your explanation. SymPy has confirmed this is correct."""

    # Step 3 — Send to Claude
    response = chat(augmented_message, request.conversation_history)

    return ChatResponse(
        response=response,
        model_used="claude",
        sympy_result=sympy_result,
        sympy_verified=sympy_result is not None
    )


@app.post("/interpret")
async def interpret_endpoint(file: UploadFile = File(...)):
    import anthropic
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    try:
        contents = await file.read()

        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

        if ext in ("png", "jpg", "jpeg", "gif", "webp"):
            media_type_map = {
                "png": "image/png",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "gif": "image/gif",
                "webp": "image/webp",
            }
            b64 = base64.standard_b64encode(contents).decode("utf-8")
            response = client.messages.create(
                model=SONNET_MODEL,
                max_tokens=1400,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type_map[ext],
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Extract all equations, variables, and diagrams from this image. Describe them in plain text.",
                        },
                    ],
                }],
            )
            extracted_text = extract_text(response)

        elif ext == "pdf":
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(contents))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            response = client.messages.create(
                model=SONNET_MODEL,
                max_tokens=1400,
                messages=[{
                    "role": "user",
                    "content": f"Extract all equations, variables, and diagrams from the following document text. Describe them in plain text.\n\n{text}",
                }],
            )
            extracted_text = extract_text(response)

        elif ext in ("docx", "doc"):
            from docx import Document
            import io
            doc = Document(io.BytesIO(contents))
            text = "\n".join(para.text for para in doc.paragraphs)
            response = client.messages.create(
                model=SONNET_MODEL,
                max_tokens=1400,
                messages=[{
                    "role": "user",
                    "content": f"Extract all equations, variables, and diagrams from the following document text. Describe them in plain text.\n\n{text}",
                }],
            )
            extracted_text = extract_text(response)

        else:
            return {"status": "error", "message": "Unsupported file type"}

        return {"status": "success", "extracted_text": extracted_text}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/upload")
async def upload_endpoint(file: UploadFile = File(...),
                          _prof: participants.Identity = Depends(require_professor)):
    """Legacy RAG ingest into the shared "professor_materials" collection
    that /query searches for everyone — so professor only."""
    # Never build a path from the uploaded name ("../../x" would escape).
    temp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             f"temp_upload_{uuid.uuid4().hex}.pdf")
    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        result = ingest_document(temp_path)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.post("/query")
def query_endpoint(request: QueryRequest):
    return query_rag(request.question)


@app.get("/cost-estimate")
def cost_estimate_endpoint():
    """Estimated API cost of a single interaction on each tutoring route."""
    return {route: estimate_route_cost(route) for route in REPORT_ROUTES}


@app.post("/tutor", response_model=TutorResponse)
def tutor_endpoint(request: TutorRequest, code: str = Depends(participant_code)):
    try:
        agent = OrchestratorAgent()
        result = agent.run(request.message, request.conversation_history, request.student_model,
                            session_id=request.session_id, student_id=code,
                            hint_level=request.hint_level)
        return TutorResponse(
            response=result["response"],
            decision=result["plan"].get("decision", result["plan"].get("action", "UNKNOWN")),
            student_model=result["updated_student_model"],
            diagram_image=result.get("diagram_image", ""),
            diagram_svg=result.get("diagram_svg"),
            route=result.get("route", ""),
            metadata={
                "parsed_input": result["parsed_input"],
                "plan": result["plan"],
                "solution": result["solution"],
                "validation": result["validation"],
                "visualization": result["visualization"],
                "route": result.get("route"),
            },
        )
    except Exception as e:
        # Never let an unexpected pipeline or serialization error surface as a
        # raw 500 to the student — return a graceful, well-formed response.
        return TutorResponse(
            response="I encountered an error processing your request. Please try again.",
            decision="ERROR",
            student_model=request.student_model,
            metadata={"error": str(e)},
        )
    


# Sent with every SSE response. A reverse proxy (nginx, some load balancers)
# may otherwise buffer the whole stream and deliver it as one chunk at the end:
# X-Accel-Buffering turns that off in nginx, and no-transform stops proxies
# from compressing (and so buffering) the body.
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}


def _sse(events):
    for event in events:
        yield f"data: {json.dumps(event)}\n\n"


@app.post("/tutor/stream")
def tutor_stream_endpoint(request: TutorRequest, code: str = Depends(participant_code),
                          ident: participants.Identity = Depends(current_identity)):
    if mock_stream.enabled():
        # Dev only (MOCK_TUTOR_STREAM=1): canned reply, no agents, no API calls.
        return StreamingResponse(_sse(mock_stream.mock_events(request.student_model)),
                                 media_type="text/event-stream", headers=SSE_HEADERS)

    agent = OrchestratorAgent()

    # Text from any documents the student attached. Empty when none, in which
    # case the pipeline behaves exactly as it did before.
    source_text = ""
    if request.doc_ids:
        try:
            # Only documents this caller may see: shared course material and
            # their own uploads. Anyone else's id fails like a missing one.
            source_text = document_store.get_context(
                document_store.visible_ids(request.doc_ids, ident), ident)
        except DocumentError:
            # A missing (or not-yours) document must not kill the whole
            # turn — the tutor answers without it.
            source_text = ""

    def event_gen():
        try:
            for event in agent.run_stream(request.message, request.conversation_history,
                                          request.student_model, source_text,
                                          session_id=request.session_id,
                                          student_id=code,
                                          hint_level=request.hint_level):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            # Log the full traceback server-side for diagnosis; send the frontend
            # only a safe, generic message (no stack trace, no exception detail).
            # We deliberately avoid logging API keys, conversation history, or
            # document contents — only the failure itself and a correlation id.
            request_id = uuid.uuid4().hex[:8]
            logger.exception(
                "tutor/stream failed (request_id=%s, exc_type=%s, doc_count=%d)",
                request_id, type(e).__name__, len(request.doc_ids or []),
            )
            safe_text = (
                "Sorry — the tutor hit an unexpected error while working on that. "
                f"Please try again. (ref {request_id})"
            )
            yield f"data: {json.dumps({'type': 'error', 'text': safe_text})}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/feedback")
def feedback_endpoint(request: FeedbackRequest, code: str = Depends(participant_code)):
    """Thumbs up/down on a tutor reply (pilot item 6). No LLM involved —
    pure file-based storage, same pattern as agents/memory.py."""
    try:
        entry = record_feedback(
            session_id=request.session_id,
            turn_number=request.turn_number,
            student_id=code,
            rating=request.rating,
        )
    except FeedbackError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "entry": entry}


# =============================================================================
# DOCUMENT STORE
# =============================================================================

@app.post("/check-work")
def check_work_endpoint(request: CheckWorkRequest, code: str = Depends(participant_code)):
    """Line-by-line check of a student's worked solution (pilot item 9).
    The checking is pure SymPy (agents/work_checker.py). Lines that only use
    givens are checked with no LLM call at all; the solver's answers are
    fetched only when a line uses a symbol the givens don't cover, and at most once per problem
    (reused from a SOLVE turn when one already ran)."""
    if not request.parsed_input.get("givens") and not request.parsed_input.get("unknowns_requested"):
        raise HTTPException(status_code=400,
                            detail="There's no problem to check against yet — send the problem first.")

    ctx = build_known_values(request.parsed_input, None)
    report = check_work(request.lines, ctx.known_values, ctx.allowed_symbols,
                        angle_symbols=ctx.angle_symbols)

    # "defined" counts too: the student may be defining N or f, which the
    # solver knows — only its answers can turn that into a real check.
    needs_answers = any(r["status"] in ("unverifiable", "defined") for r in report["results"])
    answers_available = False
    if needs_answers:
        try:
            solution = OrchestratorAgent().solution_for_work_check(request.parsed_input)
        except DailyLimitReached:
            raise HTTPException(status_code=429, detail=DAILY_LIMIT_MESSAGE)
        except Exception:
            logger.exception("check-work: solver lookup failed")
            solution = None
        if solution is not None:
            answers_available = True
            ctx = build_known_values(request.parsed_input, solution)
            report = check_work(request.lines, ctx.known_values, ctx.allowed_symbols,
                                angle_symbols=ctx.angle_symbols,
                                hidden_symbols=ctx.hidden_symbols)

    record_check_work(request.session_id, request.turn_number, code, report["results"])
    return {**report, "answers_available": answers_available}


@app.post("/documents")
async def create_document(file: UploadFile = File(...),
                          course: str = Form("default"),
                          ident: participants.Identity = Depends(current_identity)):
    """Upload one document: shared course material from a professor,
    private to the uploader from a participant."""
    try:
        data = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400,
                            detail=f"Could not read the upload: {exc}")
    try:
        return document_store.save_document(file.filename or "", data, ident, course)
    except DocumentError as exc:
        # Rejections carry a user-facing message; 422 = we understood the
        # request but the file itself is unusable.
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500,
                            detail=f"Unexpected error storing the document: {exc}")


@app.get("/documents")
def list_documents_endpoint(course: str | None = None,
                            ident: participants.Identity = Depends(current_identity)):
    """Shared course material plus the caller's own uploads, newest first.
    Text is not included."""
    return {"documents": document_store.list_documents(ident, course)}


@app.get("/documents/{doc_id}")
def get_document_endpoint(doc_id: str,
                          ident: participants.Identity = Depends(current_identity)):
    """One document record plus its full extracted text — 404 for anything
    the caller may not see, exactly as for an id that doesn't exist."""
    try:
        return document_store.get_document(doc_id, ident)
    except DocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/documents/{doc_id}")
def delete_document_endpoint(doc_id: str,
                             ident: participants.Identity = Depends(current_identity)):
    """Remove one of the caller's own documents (a professor: shared ones)."""
    try:
        return document_store.delete_document(doc_id, ident)
    except DocumentForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except DocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


class SummarizeRequest(BaseModel):
    doc_ids: list[str]
    instruction: str = ""


@app.post("/documents/summarize")
def summarize_endpoint(request: SummarizeRequest,
                       ident: participants.Identity = Depends(current_identity)):
    """Summarize one or more stored documents the caller may see."""
    import document_features
    try:
        return document_features.summarize(request.doc_ids, ident, request.instruction)
    except DocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Summarization failed: {exc}")
    
    
    
class QuizRequest(BaseModel):
    doc_ids: list[str]
    num_questions: int = 5


@app.post("/documents/quiz")
def quiz_endpoint(request: QuizRequest,
                  ident: participants.Identity = Depends(current_identity)):
    """Generate a multiple-choice quiz from stored documents the caller may see."""
    import document_features
    try:
        return document_features.make_quiz(request.doc_ids, ident, request.num_questions)
    except DocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except document_features.QuizError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Quiz generation failed: {exc}")