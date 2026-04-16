"""
Claude Client - Handles communication with Anthropic's Claude API.
"""

import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

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
always use that as the correct answer -- it has been mathematically verified.

Be encouraging, clear, and thorough in your explanations."""


def chat(message: str, conversation_history: list = []) -> str:
    """
    Send a message to Claude and get a response.

    Args:
        message: The user's message
        conversation_history: List of previous messages (OpenAI-style dicts with role/content)

    Returns:
        The model's response as a string
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "Error: ANTHROPIC_API_KEY environment variable is not set."

    client = anthropic.Anthropic(api_key=api_key)

    # Build messages array from history, then append current message
    messages = []
    for msg in conversation_history:
        messages.append({"role": msg["role"], "content": msg["content"].encode('ascii', 'ignore').decode('ascii')})
    messages.append({"role": "user", "content": message.encode('ascii', 'ignore').decode('ascii')})

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT.encode('ascii', 'ignore').decode('ascii'),
            messages=messages,
        )
        return response.content[0].text

    except anthropic.AuthenticationError:
        return "Error: Invalid Anthropic API key. Please check your ANTHROPIC_API_KEY."
    except anthropic.RateLimitError:
        return "Error: Anthropic API rate limit reached. Please wait a moment and try again."
    except Exception as e:
        return f"Error communicating with Claude: {str(e)}"
