"""
memory.py — file-based session memory for the tutoring pipeline.

Inspired by MCP-SIM's session model: every tutoring session gets a directory
under ``traces/`` holding one JSON file per turn plus an append-only
``errors.jsonl`` log, and per-student state is persisted under ``state/``.

Layout (anchored to the backend directory, independent of the process CWD):

    <backend>/traces/{session_id}/{turn}.json     one record per conversation turn
    <backend>/traces/{session_id}/errors.jsonl    append-only validator/solver errors
    <backend>/state/{student_id}.json             latest student model

All methods are defensive: they create directories on demand and never raise
for a missing read target (``get_*`` helpers return empty defaults instead).
"""

import json
import os
import re
from datetime import datetime, timezone


# Restrict ids to a safe character set to avoid path traversal / odd filenames.
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]")

# The backend directory (parent of this ``agents`` package). Anchoring the
# traces/ and state/ directories here keeps them in a stable location no
# matter which working directory uvicorn (or a test) is launched from.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_BASE_DIR = os.path.join(_BACKEND_DIR, "traces")
_DEFAULT_STATE_DIR = os.path.join(_BACKEND_DIR, "state")


def _safe_id(identifier: str) -> str:
    """Sanitize an id into a filesystem-safe token (no path separators)."""
    token = _SAFE_ID.sub("_", str(identifier)).strip("._-")
    return token or "unknown"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: str, payload: object) -> None:
    """Write JSON to ``path`` atomically (temp file + os.replace)."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp, path)


class SessionMemory:
    """File-based persistence for sessions, turns, errors, and student models."""

    def __init__(
        self,
        base_dir: str = _DEFAULT_BASE_DIR,
        state_dir: str = _DEFAULT_STATE_DIR,
    ) -> None:
        self.base_dir = base_dir
        self.state_dir = state_dir
        os.makedirs(self.base_dir, exist_ok=True)
        os.makedirs(self.state_dir, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Path helpers
    # ------------------------------------------------------------------ #
    def _session_dir(self, session_id: str) -> str:
        return os.path.join(self.base_dir, _safe_id(session_id))

    def _errors_path(self, session_id: str) -> str:
        return os.path.join(self._session_dir(session_id), "errors.jsonl")

    def _student_path(self, student_id: str) -> str:
        return os.path.join(self.state_dir, f"{_safe_id(student_id)}.json")

    # ------------------------------------------------------------------ #
    # Sessions & turns
    # ------------------------------------------------------------------ #
    def create_session(self, session_id: str) -> str:
        """Create ``traces/{session_id}/`` and return its path."""
        path = self._session_dir(session_id)
        os.makedirs(path, exist_ok=True)
        return path

    def log_turn(self, session_id: str, turn_number: int, data: dict) -> str:
        """Write ``traces/{session_id}/{turn}.json`` with the turn record."""
        session_dir = self.create_session(session_id)
        path = os.path.join(session_dir, f"{turn_number}.json")
        record = {
            "session_id": session_id,
            "turn": turn_number,
            "logged_at": _utc_now_iso(),
            "data": data,
        }
        _atomic_write_json(path, record)
        return path

    # ------------------------------------------------------------------ #
    # Errors
    # ------------------------------------------------------------------ #
    def log_error(
        self,
        session_id: str,
        error: object,
        fix_attempted: object,
        success: bool,
    ) -> None:
        """Append one error record to ``traces/{session_id}/errors.jsonl``."""
        self.create_session(session_id)
        entry = {
            "timestamp": _utc_now_iso(),
            "error": error,
            "fix_attempted": fix_attempted,
            "success": bool(success),
        }
        with open(self._errors_path(session_id), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def get_error_history(self, session_id: str) -> list:
        """Return the list of past error records for a session ([] if none)."""
        path = self._errors_path(session_id)
        if not os.path.exists(path):
            return []
        history: list = []
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    history.append(json.loads(line))
                except json.JSONDecodeError:
                    # Skip a corrupt line rather than failing the whole read.
                    continue
        return history

    # ------------------------------------------------------------------ #
    # Student models
    # ------------------------------------------------------------------ #
    def get_student_model(self, student_id: str) -> dict:
        """Read ``state/{student_id}.json``; return {} if not found/unreadable."""
        path = self._student_path(student_id)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def save_student_model(self, student_id: str, model: dict) -> str:
        """Write ``state/{student_id}.json`` and return its path."""
        path = self._student_path(student_id)
        _atomic_write_json(path, model or {})
        return path
