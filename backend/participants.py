"""
participants.py — pilot participant codes (the only student identity the
server ever sees or stores).

A student types a code like P07; every API request carries it in the
X-Participant-Code header, and it is the student_id in every saved record.
No names, emails, or other identifying info are collected anywhere.

The allowlist comes from, in order:
  1. PILOT_PARTICIPANT_CODES env var — comma- or whitespace-separated
  2. the file named by PILOT_PARTICIPANTS_FILE (default:
     backend/participants.txt) — one code per line, '#' starts a comment

Both are read on every check (the file is tiny), so codes can be added on
the server without a restart. An empty allowlist rejects everyone: the
tutor spends real API money, so a misconfigured server fails closed.

Professor codes work the same way, from PILOT_PROFESSOR_CODES and
PILOT_PROFESSORS_FILE (default backend/professors.txt). A professor can do
everything a participant can, and anything a professor uploads is shared
course material every participant sees. A code listed as both is treated as
a participant — a misconfiguration must never grant professor powers.
"""
from __future__ import annotations

import os
import re
from typing import NamedTuple

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_FILE = os.path.join(_BACKEND_DIR, "participants.txt")
_DEFAULT_PROFESSORS_FILE = os.path.join(_BACKEND_DIR, "professors.txt")

PARTICIPANT = "participant"
PROFESSOR = "professor"


class Identity(NamedTuple):
    code: str
    role: str  # PARTICIPANT | PROFESSOR

    @property
    def is_professor(self) -> bool:
        return self.role == PROFESSOR


HEADER = "X-Participant-Code"

# Codes are also used as file names (state/{code}.json), so keep them to a
# short, filesystem-safe alphabet.
_CODE_RE = re.compile(r"^[A-Z0-9-]{2,32}$")


def normalize(code) -> str | None:
    """Uppercased, trimmed code, or None if it can't be a valid code."""
    if not isinstance(code, str):
        return None
    c = code.strip().upper()
    return c if _CODE_RE.match(c) else None


def _codes_from(env_var: str, file_env_var: str, default_file: str) -> set[str]:
    codes: set[str] = set()
    env = os.environ.get(env_var, "")
    for token in re.split(r"[\s,]+", env):
        if (c := normalize(token)):
            codes.add(c)

    path = os.environ.get(file_env_var, default_file)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                if (c := normalize(line.split("#", 1)[0])):
                    codes.add(c)
    except OSError:
        pass
    return codes


def allowed_codes() -> set[str]:
    return _codes_from("PILOT_PARTICIPANT_CODES", "PILOT_PARTICIPANTS_FILE", _DEFAULT_FILE)


def professor_codes() -> set[str]:
    return _codes_from("PILOT_PROFESSOR_CODES", "PILOT_PROFESSORS_FILE",
                       _DEFAULT_PROFESSORS_FILE) - allowed_codes()


def identify(code) -> Identity | None:
    """Who this code belongs to, or None if it's on neither list."""
    c = normalize(code)
    if c is None:
        return None
    if c in allowed_codes():
        return Identity(c, PARTICIPANT)
    if c in professor_codes():
        return Identity(c, PROFESSOR)
    return None


def verify(code) -> str | None:
    """The normalized code if it's a valid participant or professor code."""
    ident = identify(code)
    return ident.code if ident else None
