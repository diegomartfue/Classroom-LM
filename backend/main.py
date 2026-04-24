"""
ClassroomLM Backend - FastAPI Server
Handles AI tutoring requests with Ollama + SymPy verification.
"""
import shutil
import os
import base64
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from rag_pipeline import ingest_document, query_rag
from pydantic import BaseModel
from claude_client import chat
from sympy_solver import extract_and_solve
from agents.orchestrator import OrchestratorAgent

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
    model: str = "qwen"        # "qwen" or "deepseek"
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

class TutorResponse(BaseModel):
    response: str
    decision: str
    student_model: dict
    diagram_image: str = ""
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
    2. Send to Ollama with SymPy result injected if available
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
                model="claude-sonnet-4-5",
                max_tokens=1024,
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
            extracted_text = response.content[0].text

        elif ext == "pdf":
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(contents))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            response = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": f"Extract all equations, variables, and diagrams from the following document text. Describe them in plain text.\n\n{text}",
                }],
            )
            extracted_text = response.content[0].text

        elif ext in ("docx", "doc"):
            from docx import Document
            import io
            doc = Document(io.BytesIO(contents))
            text = "\n".join(para.text for para in doc.paragraphs)
            response = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": f"Extract all equations, variables, and diagrams from the following document text. Describe them in plain text.\n\n{text}",
                }],
            )
            extracted_text = response.content[0].text

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


@app.post("/tutor", response_model=TutorResponse)
def tutor_endpoint(request: TutorRequest):
    agent = OrchestratorAgent()
    result = agent.run(request.message, request.conversation_history, request.student_model)
    return TutorResponse(
        response=result["response"],
        decision=result["plan"].get("action", "UNKNOWN"),
        student_model=result["updated_student_model"],
        diagram_image=result.get("diagram_image", ""),
        metadata={
            "parsed_input": result["parsed_input"],
            "plan": result["plan"],
            "solution": result["solution"],
            "validation": result["validation"],
            "visualization": result["visualization"],
        },
    )