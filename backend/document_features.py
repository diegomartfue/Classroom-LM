"""
document_features.py — features built on top of the document store.

Each feature is the same three steps: pull text via get_context(), send one
prompt, return the result. They do not touch the orchestrator, the router,
or the tutor chat path.
"""

import os
import anthropic
from dotenv import load_dotenv

from document_store import get_context, DocumentError

load_dotenv()

MODEL = "claude-sonnet-4-6"


def _client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise DocumentError("ANTHROPIC_API_KEY is not set.")
    return anthropic.Anthropic(api_key=api_key)


SUMMARIZER_PROMPT = """You summarize course material for engineering students.

You will be given the full text of one or more course documents.

Write a summary that covers:
- What the document is about, in one sentence
- The main topics or sections, in order
- Key definitions, formulas, and results that a student would need to know
- Anything the document emphasizes as important

RULES:
- Summarize only what is in the document. Do not add outside material.
- Keep formulas exactly as written in the source.
- If the text appears to be a transcription of handwriting or a scan, it may
  contain errors — note any spot that looks garbled rather than guessing.
- Plain prose with short headings. No preamble, no "here is a summary".
"""


def summarize(doc_ids: list, instruction: str = "") -> dict:
    """Summarize one or more stored documents."""
    context = get_context(doc_ids)
    if not context.strip():
        raise DocumentError("Those documents have no text to summarize.")

    user_content = context
    if instruction:
        user_content += f"\n\nAdditional instruction from the user:\n{instruction}"

    response = _client().messages.create(
        model=MODEL,
        max_tokens=2048,
        temperature=0.3,
        system=SUMMARIZER_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    text = "".join(
        b.text for b in response.content if getattr(b, "type", "") == "text"
    ).strip()

    return {
        "summary": text,
        "doc_ids": doc_ids,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }