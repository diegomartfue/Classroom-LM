"""
evals/run.py — run the pilot eval suite (pilot item 10).

    python -m evals.run                       # mocked: canned agent outputs, zero API calls
    python -m evals.run --mode live           # prints the cost estimate and stops
    python -m evals.run --mode live --yes     # real API calls (costs money)
    python -m evals.run --case pendulum       # one case only

Run from the repo root. Each case goes through OrchestratorAgent.run_stream(),
the same entry point /tutor/stream uses, and the event stream is graded
against the case's `expect` block (see evals/pilot_cases.py).

--mode mocked replaces the Anthropic client with one that returns each
case's canned outputs. It checks the pipeline wiring and this grader, not
model quality: route/decision propagation, solver answers reaching the meta
event, the DRAW clarify short-circuit, and so on. Also run under pytest
(backend/tests/test_eval_harness.py).

--mode live grades the real models. It refuses to run without --yes, and
always prints the estimate first. Turns are journaled under
evals/results/<timestamp>/, not the pilot's backend/state/, so eval
students never mix with real ones; the shared daily spending limit
(DAILY_COST_LIMIT_USD) still applies.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from evals.pilot_cases import ANSWER_REL_TOL, CASES  # noqa: E402


# =============================================================================
# Grading (pure: events in, checks out)
# =============================================================================

_ES_WORDS = {"el", "la", "los", "las", "de", "del", "que", "es", "y", "en", "por",
             "para", "una", "un", "se", "con", "su", "como", "sobre", "asi"}
_EN_WORDS = {"the", "and", "is", "of", "to", "that", "it", "with", "for", "on",
             "this", "so", "your", "you", "are"}


def _looks_spanish(text: str) -> bool:
    words = re.findall(r"[a-záéíóúñ]+", text.lower())
    es = sum(w in _ES_WORDS for w in words)
    en = sum(w in _EN_WORDS for w in words)
    return es >= 3 and es > en


def _answer_leaked(text: str, value: float, unit: str) -> bool:
    """True if the response states the reference value. A bare integer like
    "8" is too common to count on its own, so integers only count when
    followed by the unit; a decimal like "2.62" counts anywhere."""
    v = abs(value)
    unit_re = re.escape(unit) if unit else ""
    candidates = {f"{v:.2f}", f"{v:.3g}", f"{v:.1f}"}
    for num in candidates:
        num_re = r"(?<![\d.])" + re.escape(num) + r"(?![\d])"
        if unit_re and re.search(num_re + r"\s*" + unit_re, text):
            return True
        if "." in num and len(num.split(".")[1]) >= 2 and re.search(num_re, text):
            return True
    return False


def _final_answers(solution) -> list[tuple[str, float]]:
    out = []
    answers = solution.get("final_answers") if isinstance(solution, dict) else None
    for a in answers if isinstance(answers, list) else []:
        if not isinstance(a, dict):
            continue
        try:
            out.append((str(a.get("symbol", "")), float(a.get("value"))))
        except (TypeError, ValueError):
            continue
    return out


def _close(a: float, b: float) -> bool:
    # Magnitudes only: "down the incline" vs "up the incline" is a sign
    # convention, not a wrong answer.
    return math.isclose(abs(a), abs(b), rel_tol=ANSWER_REL_TOL, abs_tol=1e-6)


def grade(case: dict, events: list[dict], called_agents: list[str] | None = None) -> list[dict]:
    """Return one {"check", "passed", "detail"} per expectation."""
    expect = case["expect"]
    meta = next((e for e in events if e.get("type") == "meta"), {})
    response = "".join(e.get("text", "") for e in events if e.get("type") == "token")
    errored = any(e.get("type") == "error" for e in events)
    decision = meta.get("decision")
    checks = []

    def add(name, passed, detail=""):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    add("no_error", not errored and bool(meta), "" if meta else "no meta event")
    add("route", meta.get("route") == expect["route"],
        f"got {meta.get('route')!r}, want {expect['route']!r}")
    add("decision", decision in expect["decisions"],
        f"got {decision!r}, want one of {expect['decisions']}")
    add("non_empty_response", bool(response.strip()))

    solved = decision == "SOLVE"
    finals = _final_answers(meta.get("solution"))
    for symbol, (value, unit) in (expect.get("answers") or {}).items():
        if solved:
            by_symbol = [v for s, v in finals if s == symbol]
            ok = any(_close(v, value) for v in by_symbol)
            how = "by symbol"
            if not by_symbol:
                # Live solvers pick their own symbol names; fall back to "some
                # final answer has the right value".
                ok = any(_close(v, value) for _, v in finals)
                how = "by value (symbol not found)"
            add(f"answer:{symbol}", ok,
                f"want {value:.4g} {unit}, solver gave {finals} ({how})")
        elif _answer_leaked(case["message"], value, unit):
            # The student already said this number; repeating it isn't a leak.
            add(f"no_leak:{symbol}", True, "value appears in the student's own message")
        else:
            leaked = _answer_leaked(response, value, unit)
            add(f"no_leak:{symbol}", not leaked,
                f"response states {value:.4g} {unit} without a SOLVE" if leaked else "")

    wanted = expect.get("response_contains_any")
    if wanted:
        low = response.lower()
        add("response_contains_any", any(w.lower() in low for w in wanted),
            f"none of {wanted} in response")

    if expect.get("language") == "es":
        add("language:es", _looks_spanish(response), "response doesn't read as Spanish")

    if called_agents is not None:
        for agent in expect.get("agents_not_called") or []:
            add(f"not_called:{agent}", agent not in called_agents,
                f"{agent} ran (calls: {called_agents})")

    return checks


# =============================================================================
# Mocked client
# =============================================================================

class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Response:
    stop_reason = "end_turn"

    def __init__(self, text):
        self.content = [_Block(text)]


class _Stream:
    def __init__(self, text):
        # Several chunks, so token concatenation is actually exercised.
        self.text_stream = iter(re.findall(r"\S+\s*", text) or [text])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class MockedClient:
    """Stands in for client.messages: answers each agent's call from the
    case's `mock` block and records which agents ran. Never imports or
    touches the real Anthropic client."""

    def __init__(self, mock: dict):
        from agents import orchestrator as o
        self.mock = mock
        self.messages = self
        self.called: list[str] = []
        self._names = {
            id(o.ROUTER_PROMPT): "router",
            id(o.INPUT_PARSER_PROMPT): "input_parser",
            id(o.STUDENT_MODELER_PROMPT): "student_modeler",
            id(o.PEDAGOGICAL_PLANNER_PROMPT): "planner",
            id(o.SOLVER_PROMPT): "solver",
            id(o.VALIDATOR_PROMPT): "validator",
            id(o.VISUALIZER_PROMPT): "visualizer",
            id(o.CONVERSATIONALIST_PROMPT): "conversationalist",
            id(o.DIRECT_TUTOR_PROMPT): "direct_tutor",
        }

    def _name(self, system) -> str:
        return self._names.get(id(system), "other")

    def _canned(self, name: str) -> str:
        if name == "student_modeler":
            return json.dumps({"current_state": "progressing", "observed_misconceptions": []})
        if name == "planner":
            plan = {"rationale": "eval mock", "target_misconception": None,
                    **self.mock.get("planner", {"decision": "ASK", "payload": {}})}
            return json.dumps(plan)
        if name == "validator":
            return json.dumps({"overall_verdict": "PASS", "errors_found": []})
        if name == "visualizer":
            return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>'
        if name in self.mock:
            return json.dumps(self.mock[name])
        return "{}"

    def create(self, **kwargs):
        name = self._name(kwargs.get("system"))
        self.called.append(name)
        return _Response(self._canned(name))

    def stream(self, **kwargs):
        self.called.append(self._name(kwargs.get("system")))
        return _Stream(self.mock.get("response", "OK."))


class _NullMemory:
    """Mocked runs must not write eval turns into the pilot's real journal."""

    def create_session(self, session_id):
        return ""

    def log_turn(self, *args, **kwargs):
        return ""

    def save_student_model(self, *args, **kwargs):
        return ""

    def log_error(self, *args, **kwargs):
        return None

    def get_student_model(self, student_id):
        return {}


# =============================================================================
# Running
# =============================================================================

def run_case(agent, case: dict) -> list[dict]:
    return list(agent.run_stream(
        case["message"], case.get("history", []), {},
        session_id=f"eval-{case['id']}", student_id=f"eval-{case['id']}",
        hint_level=case.get("hint_level"),
    ))


def run_mocked(cases: list[dict]) -> list[dict]:
    os.environ.setdefault("ANTHROPIC_API_KEY", "mocked-eval-not-a-real-key")
    from agents.orchestrator import OrchestratorAgent

    results = []
    for case in cases:
        agent = OrchestratorAgent()
        client = MockedClient(case.get("mock", {}))
        agent.client = client
        agent.memory = _NullMemory()
        events = run_case(agent, case)
        results.append({"id": case["id"], "events": events,
                        "checks": grade(case, events, client.called)})
    return results


def run_live(cases: list[dict], results_dir: Path) -> list[dict]:
    from agents.memory import SessionMemory
    from agents.orchestrator import OrchestratorAgent

    memory = SessionMemory(base_dir=str(results_dir / "traces"),
                           state_dir=str(results_dir / "state"))
    results = []
    for case in cases:
        agent = OrchestratorAgent()
        agent.memory = memory
        try:
            events = run_case(agent, case)
        except Exception as exc:  # one bad case shouldn't lose the rest
            events = [{"type": "error", "text": f"{type(exc).__name__}: {exc}"}]
        results.append({"id": case["id"], "events": events, "checks": grade(case, events)})
    return results


# =============================================================================
# Cost estimate (never makes a call)
# =============================================================================

def estimate_cost(cases: list[dict]) -> tuple[list[dict], float]:
    """Worst case per case from utils/cost_tracker's route averages: a case
    that may SOLVE is priced as PROBLEM_SOLVE. A DRAW clarify is a single
    Router call, priced from the tracker's own router line. Validator
    retries and extended thinking aren't in the tracker's averages, so a
    real run can come in higher."""
    from utils.cost_tracker import ROUTE_PIPELINES, estimate_route_cost, _agent_cost

    router_line = next(line for line in ROUTE_PIPELINES["PROBLEM_HINT"] if line[0] == "router")
    router_cost = _agent_cost(router_line[1], router_line[2], router_line[3])

    rows = []
    for case in cases:
        route, decisions = case["expect"]["route"], case["expect"]["decisions"]
        if route == "DRAW" and decisions == ["CLARIFY"]:
            key, cost = "ROUTER_ONLY", router_cost
        elif route == "PROBLEM":
            key = "PROBLEM_SOLVE" if "SOLVE" in decisions else "PROBLEM_HINT"
            cost = estimate_route_cost(key)["cost_usd"]
        else:
            key = route
            cost = estimate_route_cost(route)["cost_usd"]
        rows.append({"id": case["id"], "priced_as": key, "cost_usd": cost})
    return rows, sum(r["cost_usd"] for r in rows)


def print_estimate(cases: list[dict]) -> None:
    rows, total = estimate_cost(cases)
    print("Estimated cost of one live run (utils/cost_tracker averages):")
    for r in rows:
        print(f"  {r['id']:<24} {r['priced_as']:<14} ${r['cost_usd']:.4f}")
    print(f"  {'TOTAL':<24} {'':<14} ${total:.4f}")
    print("  Validator retries and extended thinking aren't in these averages; "
          "a real run can cost more.")


# =============================================================================
# Report / CLI
# =============================================================================

def summarize(results: list[dict]) -> tuple[int, int]:
    passed = sum(all(c["passed"] for c in r["checks"]) for r in results)
    return passed, len(results)


def print_report(results: list[dict]) -> None:
    for r in results:
        ok = all(c["passed"] for c in r["checks"])
        print(f"{'PASS' if ok else 'FAIL'}  {r['id']}")
        for c in r["checks"]:
            if not c["passed"]:
                print(f"        x {c['check']}: {c['detail']}")
    passed, total = summarize(results)
    print(f"\n{passed}/{total} cases passed")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the pilot eval suite.")
    parser.add_argument("--mode", choices=["mocked", "live"], default="mocked")
    parser.add_argument("--yes", action="store_true",
                        help="live mode only: actually make the (paid) API calls")
    parser.add_argument("--case", action="append", default=[],
                        help="run only this case id (repeatable)")
    parser.add_argument("--out", type=Path, help="also write full results as JSON here")
    args = parser.parse_args(argv)

    cases = [c for c in CASES if not args.case or c["id"] in args.case]
    unknown = set(args.case) - {c["id"] for c in CASES}
    if unknown:
        parser.error(f"unknown case id(s): {', '.join(sorted(unknown))}")

    if args.mode == "live":
        print_estimate(cases)
        if not args.yes:
            print("\nLive mode makes real API calls. Re-run with --yes to proceed.")
            return 2
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        results_dir = REPO_ROOT / "evals" / "results" / stamp
        results = run_live(cases, results_dir)
        out = args.out or results_dir / "results.json"
    else:
        results = run_mocked(cases)
        out = args.out

    print_report(results)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, indent=2, default=str))
        print(f"results written to {out}")
    passed, total = summarize(results)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
