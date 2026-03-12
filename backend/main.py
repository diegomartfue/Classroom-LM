"""
ClassroomLM Backend - FastAPI Server
Handles AI tutoring requests with Ollama + SymPy verification.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from ollama_client import chat, is_ollama_running, get_available_models
from sympy_solver import extract_and_solve

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

# =============================================================================
# ROUTES
# =============================================================================

@app.get("/")
def root():
    return {"status": "ClassroomLM backend running"}


@app.get("/health")
def health():
    ollama_ok = is_ollama_running()
    models = get_available_models()
    return {
        "ollama_running": ollama_ok,
        "available_models": models,
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

    # Step 3 — Send to Ollama
    response = chat(
        message=augmented_message,
        model_key=request.model,
        conversation_history=request.conversation_history
    )

    return ChatResponse(
        response=response,
        model_used=request.model,
        sympy_result=sympy_result,
        sympy_verified=sympy_result is not None
    )