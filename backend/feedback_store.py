"""
feedback_store.py — thumbs up/down on tutor replies (pilot item 6).

Owns one thing: append-only storage of student feedback on a tutor turn.
No LLM involved anywhere in this module.

Storage layout (relative to the backend directory, same anchoring pattern as
document_store.py and agents/memory.py):
    state/feedback.jsonl   one JSON line per rating
"""
import json
import os
from datetime import datetime, timezone

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_PATH = os.path.join(_BACKEND_DIR, "state", "feedback.jsonl")

_VALID_RATINGS = {"up", "down"}


class FeedbackError(ValueError):
    """Bad input to record_feedback — the caller should turn this into a
    4xx, not a 500."""


def record_feedback(session_id: str, turn_number: int, student_id: str,
                     rating: str, path: str = _DEFAULT_PATH) -> dict:
    """Append one feedback entry. Returns the stored entry.

    Raises FeedbackError for a rating outside {"up", "down"} — that's a
    caller bug (bad request), not a storage failure, so unlike the rest of
    this pilot's persistence code it's the one place that's allowed to
    raise rather than degrade silently; the /feedback endpoint turns it into
    an HTTP 400.
    """
    if rating not in _VALID_RATINGS:
        raise FeedbackError(f"rating must be one of {sorted(_VALID_RATINGS)}, got {rating!r}")

    entry = {
        "session_id": str(session_id),
        "turn_number": int(turn_number),
        "student_id": str(student_id),
        "rating": rating,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_feedback(path: str = _DEFAULT_PATH) -> list[dict]:
    """All recorded feedback entries, oldest first. [] if none yet.
    Corrupt lines are skipped, not fatal — matches agents/memory.py's
    get_error_history."""
    if not os.path.exists(path):
        return []
    entries: list[dict] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries
