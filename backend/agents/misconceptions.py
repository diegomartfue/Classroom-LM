"""
agents/misconceptions.py — loads docs/misconceptions.md into a lookup table,
so it's actually used by the tutor instead of sitting as unreferenced
documentation.

Two uses:
(a) known_misconceptions_block() extends STUDENT_MODELER_PROMPT's detection
    list with the STATICS misconceptions this file catalogs (FBD
    construction, equilibrium equations, reference point selection,
    distributed loads, conceptual) — categories the prompt's own hand-written
    inline list didn't cover at all, since that list is dynamics-focused
    (Newton's second law, kinematics, energy/momentum). Statics (planar
    equilibrium) is explicitly in the project's MVP scope per CLAUDE.md, so
    this was a real detection gap, not a duplicate of the inline list.
(b) remediation_for(id) gives the Conversationalist ONE short, targeted
    "how to address" snippet when the Pedagogical Planner sets
    target_misconception to one of these ids — instead of it having to
    improvise an explanation from a bare id string with no grounding.

Deterministic, no LLM, parsed once at import time. Never raises: a
missing/malformed doc file just means both functions return "" and the
tutor runs exactly as it did before this module existed.
"""
from __future__ import annotations

import os
import re

_DOCS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "docs", "misconceptions.md",
)

# Matches one **ID** entry with its Description/What it looks like/How to
# address bullets, up to (but not including) the next entry or category
# heading. "What it looks like" is optional in the pattern (not in the real
# file) so a hand-edited entry that drops it still parses.
_ENTRY_RE = re.compile(
    r"\*\*([A-Z]+-\d+)\*\*\s*\n"
    r"-\s*\*\*Description:\*\*\s*(.+?)\s*\n"
    r"(?:-\s*\*\*What it looks like:\*\*\s*(.+?)\s*\n)?"
    r"-\s*\*\*How to address:\*\*\s*(.+?)\s*(?=\n\n|\n\*\*[A-Z]|\Z)",
    re.DOTALL,
)
_CATEGORY_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _parse(text: str) -> dict:
    """{id: {description, symptoms, address, category}}. Returns {} (never
    raises) on anything that doesn't match the expected structure."""
    result: dict = {}
    try:
        categories = [(m.start(), m.group(1).strip()) for m in _CATEGORY_RE.finditer(text)]

        def _category_for(pos: int) -> str:
            cat = "General"
            for start, name in categories:
                if start <= pos:
                    cat = name
                else:
                    break
            return cat

        for m in _ENTRY_RE.finditer(text):
            entry_id, description, symptoms, address = m.groups()
            result[entry_id] = {
                "description": " ".join(description.split()),
                "symptoms": " ".join((symptoms or "").split()),
                "address": " ".join(address.split()),
                "category": _category_for(m.start()),
            }
    except Exception:
        return {}
    return result


def _load() -> dict:
    try:
        with open(_DOCS_PATH, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return {}
    return _parse(text)


MISCONCEPTIONS: dict = _load()


def remediation_for(misconception_id: str | None) -> str:
    """Short 'how to address' text for a misconception id, or "" if
    unknown/the doc couldn't be loaded. Falls back to an uppercased lookup
    since ids are conventionally upper (FBD-01), in case the Planner echoes
    a differently-cased variant."""
    if not misconception_id:
        return ""
    entry = MISCONCEPTIONS.get(misconception_id) or MISCONCEPTIONS.get(str(misconception_id).upper())
    return entry["address"] if entry else ""


def known_misconceptions_block() -> str:
    """Compact '- id: description' lines grouped by category (statics), for
    appending to STUDENT_MODELER_PROMPT's existing detection list. "" if the
    doc couldn't be loaded/parsed — the prompt's hand-written list still
    works fine standalone either way, this is purely additive."""
    if not MISCONCEPTIONS:
        return ""
    by_category: dict[str, list[str]] = {}
    for mid, entry in MISCONCEPTIONS.items():
        by_category.setdefault(entry["category"], []).append(f"- {mid}: {entry['description']}")
    lines: list[str] = []
    for category, items in by_category.items():
        lines.append(f"\n{category} (statics):")
        lines.extend(items)
    return "\n".join(lines)
