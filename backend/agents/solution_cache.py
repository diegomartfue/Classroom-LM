"""
agents/solution_cache.py — in-process cache of solver output, keyed by the
parsed problem (pilot item 9).

/check-work needs the solver's numeric answers to check lines that use the
unknowns, but most tutoring turns are HINT/ASK, where the solver never runs
and — deliberately — no answer is sent to the browser. So the browser hands
back only parsed_input, and the backend looks the solution up here:
populated for free whenever a SOLVE turn already ran the solver, otherwise
filled by one solver call the first time that problem's work is checked.

Keyed by a hash of the canonical JSON of parsed_input, which the browser
returns byte-for-byte from the "meta" event. Process-local and bounded:
a restart just costs one extra solver call per problem, which is fine for
a single-worker pilot.
"""
from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict

_MAX_ENTRIES = 256

_lock = threading.Lock()
_cache: "OrderedDict[str, dict]" = OrderedDict()


def problem_key(parsed_input: dict) -> str | None:
    try:
        canonical = json.dumps(parsed_input, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get(parsed_input: dict) -> dict | None:
    key = problem_key(parsed_input)
    if key is None:
        return None
    with _lock:
        solution = _cache.get(key)
        if solution is not None:
            _cache.move_to_end(key)
        return solution


def remember(parsed_input: dict, solution: dict | None) -> None:
    """Only stores a solution that actually has final answers — caching a
    failed/empty solve would pin that failure for the problem forever."""
    if not isinstance(solution, dict) or not solution.get("final_answers"):
        return
    key = problem_key(parsed_input)
    if key is None:
        return
    with _lock:
        _cache[key] = solution
        _cache.move_to_end(key)
        while len(_cache) > _MAX_ENTRIES:
            _cache.popitem(last=False)


def clear() -> None:
    with _lock:
        _cache.clear()
