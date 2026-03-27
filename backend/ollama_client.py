"""
Ollama Client - Handles communication with local Ollama models.
Supports both Qwen2.5 7B and DeepSeek-R1 8B with model switching.
"""

import requests
import json

OLLAMA_URL = "http://127.0.0.1:11434"

MODELS = {
    "qwen": "qwen2.5:3b",
    "deepseek": "deepseek-r1:5b"
}

SYSTEM_PROMPT = """You are an expert engineering tutor for a classroom assistant platform.
You help students understand engineering concepts including:
- Mathematics (calculus, linear algebra, differential equations)
- Physics (mechanics, thermodynamics, electromagnetism)
- Freeform equations and how to solve them step by step
- Free body diagrams and force analysis
- Vector operations

When solving equations:
- Always show step-by-step work
- Explain what each step means
- Use clear notation
- Do NOT use LaTeX syntax. Write all equations in plain text (e.g. write "x = 2" not "\\boxed{x = 2}", write "x^2" not "\\(x^2\\)").

When you see a SymPy verified result included in the context, 
always use that as the correct answer — it has been mathematically verified.

Be encouraging, clear, and thorough in your explanations."""


def chat(message: str, model_key: str = "qwen", conversation_history: list = []) -> str:
    """
    Send a message to Ollama and get a response.
    
    Args:
        message: The user's message
        model_key: "qwen" or "deepseek"
        conversation_history: List of previous messages
    
    Returns:
        The model's response as a string
    """
    model = MODELS.get(model_key, MODELS["qwen"])

    # Build messages array
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Add conversation history
    for msg in conversation_history:
        messages.append(msg)
    
    # Add current message
    messages.append({"role": "user", "content": message})

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
            },
            timeout=300  # 5 min timeout — DeepSeek can be slow
        )
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"]

    except requests.exceptions.ConnectionError:
        return "Error: Ollama is not running. Please start it with 'ollama serve'."
    except requests.exceptions.Timeout:
        return "Error: Model took too long to respond. Try again."
    except Exception as e:
        return f"Error communicating with Ollama: {str(e)}"


def is_ollama_running() -> bool:
    """Check if Ollama server is running."""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return response.status_code == 200
    except Exception:
        return False


def get_available_models() -> list:
    """Get list of models available in Ollama."""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        data = response.json()
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []