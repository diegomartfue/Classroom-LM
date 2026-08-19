"""
ClassroomLM Backend - FastAPI Server
Handles AI tutoring requests with Claude + SymPy verification.
"""
import shutil
import os
import base64
import json
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from rag_pipeline import ingest_document, query_rag
import document_store
from document_store import DocumentError
from pydantic import BaseModel
from claude_client import chat
from sympy_solver import extract_and_solve
from agents.orchestrator import OrchestratorAgent
from utils.cost_tracker import estimate_route_cost, REPORT_ROUTES
from model_config import SONNET_MODEL
from response_utils import extract_text

app = FastAPI()

# Allow requests from the React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
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

class TutorResponse(BaseModel):
    response: str
    decision: str
    student_model: dict
    diagram_image: str = ""
    route: str = ""
    metadata: dict

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
async def upload_endpoint(file: UploadFile = File(...)):
    temp_path = f"temp_{file.filename}"
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
def tutor_endpoint(request: TutorRequest):
    agent = OrchestratorAgent()
    result = agent.run(request.message, request.conversation_history, request.student_model)
    return TutorResponse(
        response=result["response"],
        decision=result["plan"].get("decision", result["plan"].get("action", "UNKNOWN")),
        student_model=result["updated_student_model"],
        diagram_image=result.get("diagram_image", ""),
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
    


@app.post("/tutor/stream")
def tutor_stream_endpoint(request: TutorRequest):
    agent = OrchestratorAgent()

    # Text from any documents the student attached. Empty when none, in which
    # case the pipeline behaves exactly as it did before.
    source_text = ""
    if request.doc_ids:
        try:
            source_text = document_store.get_context(request.doc_ids)
        except DocumentError:
            # A missing document must not kill the whole turn — the tutor
            # answers without it.
            source_text = ""

    def event_gen():
        try:
            for event in agent.run_stream(request.message, request.conversation_history,
                                          request.student_model, source_text):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# =============================================================================
# DOCUMENT STORE
# =============================================================================

@app.post("/documents")
async def create_document(file: UploadFile = File(...),
                          course: str = Form("default")):
    """Upload one course document. Extracts and stores its text."""
    try:
        data = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400,
                            detail=f"Could not read the upload: {exc}")
    try:
        return document_store.save_document(file.filename or "", data, course)
    except DocumentError as exc:
        # Rejections carry a user-facing message; 422 = we understood the
        # request but the file itself is unusable.
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500,
                            detail=f"Unexpected error storing the document: {exc}")


@app.get("/documents")
def list_documents_endpoint(course: str | None = None):
    """List stored documents, newest first. Text is not included."""
    return {"documents": document_store.list_documents(course)}


@app.get("/documents/{doc_id}")
def get_document_endpoint(doc_id: str):
    """One document record plus its full extracted text."""
    try:
        return document_store.get_document(doc_id)
    except DocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/documents/{doc_id}")
def delete_document_endpoint(doc_id: str):
    """Remove a document and its stored text."""
    try:
        return document_store.delete_document(doc_id)
    except DocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    
    
    
class SummarizeRequest(BaseModel):
    doc_ids: list[str]
    instruction: str = ""


@app.post("/documents/summarize")
def summarize_endpoint(request: SummarizeRequest):
    """Summarize one or more stored documents."""
    import document_features
    try:
        return document_features.summarize(request.doc_ids, request.instruction)
    except DocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Summarization failed: {exc}")
    
    
    
class QuizRequest(BaseModel):
    doc_ids: list[str]
    num_questions: int = 5


@app.post("/documents/quiz")
def quiz_endpoint(request: QuizRequest):
    """Generate a multiple-choice quiz from stored documents."""
    import document_features
    try:
        return document_features.make_quiz(request.doc_ids, request.num_questions)
    except DocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except document_features.QuizError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Quiz generation failed: {exc}")