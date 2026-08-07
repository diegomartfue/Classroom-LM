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
    
    
    


# ---------------------------------------------------------------------------
# Quiz maker
# ---------------------------------------------------------------------------

import json

QUIZ_PROMPT = """You write quiz questions from course material for engineering students.

You will be given the full text of one or more course documents, and a
requested number of questions.

Return ONLY a JSON object matching this schema:

{
  "topic": "short description of what the quiz covers",
  "questions": [
    {
      "question": "the question text",
      "options": ["option A", "option B", "option C", "option D"],
      "correct_index": 0,
      "explanation": "one or two sentences on why that answer is correct",
      "source_quote": "a short phrase from the document this question came from"
    }
  ]
}

RULES:
- Every question must be answerable from the provided document alone. Do not
  use outside knowledge.
- Exactly 4 options per question. Exactly one correct.
- correct_index is 0-based and must point at the correct option.
- Vary which position the correct answer sits in. Do not put it at index 0 every time.
- Wrong options must be plausible — a wrong answer a student might actually
  pick, not an obviously silly one.
- source_quote must be text that genuinely appears in the document.
- If the document is a transcription of handwriting or a scan, it may contain
  errors. Do not write questions about a passage that looks garbled.
- Cover different parts of the document rather than clustering on one section.
- The explanation must be a clean final statement. Never think out loud, never
  write "wait" or "actually" or reverse yourself mid-sentence.
- If a passage contains an arithmetic error or a contradiction you cannot
  resolve, do NOT write a question about it. Skip that passage.

Return ONLY the JSON object. No prose, no markdown fences."""


class QuizError(Exception):
    """Raised when a generated quiz fails validation."""


def _validate_quiz(data: dict, requested: int) -> dict:
    """
    Check the model's JSON before anyone sees it. Drops individual bad
    questions; raises only if nothing usable survives.
    """
    if not isinstance(data, dict):
        raise QuizError("The model did not return a JSON object.")

    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise QuizError("The model returned no questions.")

    clean = []
    rejected = []
    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            rejected.append(f"question {i + 1}: not an object")
            continue

        text = q.get("question")
        options = q.get("options")
        idx = q.get("correct_index")

        if not isinstance(text, str) or not text.strip():
            rejected.append(f"question {i + 1}: missing question text")
            continue
        if not isinstance(options, list) or len(options) != 4:
            rejected.append(f"question {i + 1}: needs exactly 4 options")
            continue
        if any(not isinstance(o, str) or not o.strip() for o in options):
            rejected.append(f"question {i + 1}: has an empty option")
            continue
        if len(set(o.strip().lower() for o in options)) != 4:
            rejected.append(f"question {i + 1}: has duplicate options")
            continue
        if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < 4:
            rejected.append(f"question {i + 1}: correct_index is not 0-3")
            continue
        explanation = (q.get("explanation") or "").strip()
        if any(w in explanation.lower() for w in
               ("wait —", "wait,", "actually,", "let me reconsider", "hmm")):
            rejected.append(f"question {i + 1}: explanation contains visible backtracking")
            continue

        clean.append({
            "question": text.strip(),
            "options": [o.strip() for o in options],
            "correct_index": idx,
            "explanation": (q.get("explanation") or "").strip(),
            "source_quote": (q.get("source_quote") or "").strip(),
        })

    if not clean:
        raise QuizError(
            "No valid questions survived validation: " + "; ".join(rejected)
        )

    return {
        "topic": (data.get("topic") or "").strip(),
        "questions": clean,
        "requested": requested,
        "returned": len(clean),
        "rejected": rejected,
    }
    
    
    
    
def _extract_json(text: str) -> str:
    """
    Pull the JSON object out of a model reply. Handles markdown fences and
    any stray prose before or after the object.
    """
    s = text.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()

    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise QuizError("No JSON object found in the model's reply.")
    return s[start:end + 1]

def make_quiz(doc_ids: list, num_questions: int = 5) -> dict:
    """Generate a multiple-choice quiz from stored documents."""
    if not 1 <= num_questions <= 20:
        raise DocumentError("Ask for between 1 and 20 questions.")

    context = get_context(doc_ids)
    if not context.strip():
        raise DocumentError("Those documents have no text to quiz on.")

    user_content = (
        f"{context}\n\nWrite {num_questions} multiple-choice questions "
        f"from this material."
    )

    response = _client().messages.create(
        model=MODEL,
        max_tokens=4096,
        temperature=0.4,
        system=QUIZ_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    raw = "".join(
        b.text for b in response.content if getattr(b, "type", "") == "text"
    )

    try:
        data = json.loads(_extract_json(raw))
    except json.JSONDecodeError as exc:
        raise QuizError(f"The model returned malformed JSON: {exc}")

    result = _validate_quiz(data, num_questions)
    result["doc_ids"] = doc_ids
    result["input_tokens"] = response.usage.input_tokens
    result["output_tokens"] = response.usage.output_tokens
    return result