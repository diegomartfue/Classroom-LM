"""
check_work_store.py — research log of show-your-work checks (pilot item 9).

Same append-only JSONL pattern as feedback_store.py:
    state/check_work.jsonl   one JSON line per /check-work call

Each entry is tied to the tutor turn it followed (session_id + turn_number),
so the export can put it on the same row as that turn. Never raises on a
storage failure — losing one research record must not break the check the
student is waiting on.
"""
import json
import logging
import os
from datetime import datetime, timezone

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_PATH = os.path.join(_BACKEND_DIR, "state", "check_work.jsonl")

logger = logging.getLogger("classroomlm.check_work_store")


def record_check_work(session_id, turn_number, participant_code: str, results: list,
                      path: str = _DEFAULT_PATH) -> dict | None:
    entry = {
        "session_id": str(session_id) if session_id is not None else None,
        "turn_number": int(turn_number) if turn_number is not None else None,
        "participant_code": participant_code,
        "results": [{"line": r.get("line"), "status": r.get("status"), "detail": r.get("detail")}
                    for r in results],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("could not record check-work entry")
        return None
    return entry


def read_check_work(path: str = _DEFAULT_PATH) -> list[dict]:
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
