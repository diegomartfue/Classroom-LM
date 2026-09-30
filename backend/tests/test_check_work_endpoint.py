"""
Pilot item 9 — /check-work endpoint and the server-side solution cache.
Calls the endpoint function directly (same pattern as
test_feedback_endpoint.py). OrchestratorAgent is replaced by a fake, so no
real API call is possible.
"""
import json
import math
import sys
import types

import pytest

if "rag_pipeline" not in sys.modules:
    _fake = types.ModuleType("rag_pipeline")
    _fake.ingest_document = lambda *a, **k: {}
    _fake.query_rag = lambda *a, **k: {}
    sys.modules["rag_pipeline"] = _fake

import main  # noqa: E402
from agents import solution_cache  # noqa: E402
from agents.orchestrator import SOLVER_PROMPT, OrchestratorAgent  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from utils.usage_tracker import DailyLimitReached  # noqa: E402

from conftest import FakeResponse, FakeTextBlock  # noqa: E402


PARSED = {
    "family": "kinetics",
    "scenario": {"gravity": 9.81},
    "givens": [
        {"symbol": "m", "value": 10, "unit": "kg"},
        {"symbol": "theta", "value": 30, "unit": "deg"},
    ],
    "unknowns_requested": [{"symbol": "N"}],
}
N_TRUE = 10 * 9.81 * math.cos(math.radians(30))
SOLUTION = {"final_answers": [{"symbol": "N", "value": N_TRUE, "unit": "N"}]}


@pytest.fixture(autouse=True)
def _empty_cache():
    solution_cache.clear()
    yield
    solution_cache.clear()


@pytest.fixture(autouse=True)
def recorded_checks(monkeypatch):
    """Capture research-log writes instead of touching backend/state/."""
    records = []
    monkeypatch.setattr(main, "record_check_work",
                        lambda *args: records.append(args))
    return records


class FakeAgent:
    """Counts solver lookups; never touches a client."""
    calls = 0
    result = SOLUTION
    raises = None

    def solution_for_work_check(self, parsed_input):
        FakeAgent.calls += 1
        if FakeAgent.raises is not None:
            raise FakeAgent.raises
        return FakeAgent.result


@pytest.fixture
def fake_agent(monkeypatch):
    FakeAgent.calls, FakeAgent.result, FakeAgent.raises = 0, SOLUTION, None
    monkeypatch.setattr(main, "OrchestratorAgent", FakeAgent)
    return FakeAgent


def _check(lines, parsed=PARSED, **extra):
    return main.check_work_endpoint(
        main.CheckWorkRequest(lines=lines, parsed_input=parsed, **extra), code="P07")


def test_check_is_logged_under_the_participant_code(fake_agent, recorded_checks):
    _check(["m*g = 98.1"], session_id="conv-1", turn_number=3)
    [(session_id, turn_number, code, results)] = recorded_checks
    assert (session_id, turn_number, code) == ("conv-1", 3, "P07")
    assert results[0]["status"] == "correct"


# --- Endpoint -------------------------------------------------------------------

def test_givens_only_lines_never_look_up_the_solver(fake_agent):
    result = _check(["m*g = 98.1"])
    assert result["results"][0]["status"] == "correct"
    assert fake_agent.calls == 0
    assert result["answers_available"] is False


def test_unknown_lines_fetch_answers_and_hide_them(fake_agent):
    result = _check(["N = m*g*cos(30)", "N = 50"])
    assert fake_agent.calls == 1
    assert result["answers_available"] is True
    assert [r["status"] for r in result["results"]] == ["correct", "incorrect"]
    assert result["first_wrong_index"] == 1
    wrong = result["results"][1]
    assert wrong["lhs_value"] is None
    assert f"{N_TRUE:.4g}" not in wrong["detail"]


def test_solver_unavailable_leaves_lines_unchecked(fake_agent):
    # Without solver answers N can't be checked; the line just saves N for
    # later lines, and a line with two unknowns stays "can't check".
    fake_agent.result = None
    result = _check(["N = m*g*cos(30)", "T = a*m + x"])
    assert [r["status"] for r in result["results"]] == ["defined", "unverifiable"]
    assert result["answers_available"] is False


def test_solver_crash_degrades_to_unchecked(fake_agent):
    fake_agent.raises = RuntimeError("boom")
    result = _check(["N = m*g*cos(30)"])
    assert result["results"][0]["status"] == "defined"


def test_daily_limit_is_a_429(fake_agent):
    fake_agent.raises = DailyLimitReached("limit")
    with pytest.raises(HTTPException) as exc_info:
        _check(["N = m*g*cos(30)"])
    assert exc_info.value.status_code == 429


def test_no_problem_is_a_400(fake_agent):
    with pytest.raises(HTTPException) as exc_info:
        _check(["N = 5"], parsed={})
    assert exc_info.value.status_code == 400
    assert fake_agent.calls == 0


def test_injection_through_endpoint_is_invalid(fake_agent):
    result = _check(["N = __import__('os').system('echo pwned')"])
    assert result["results"][0]["status"] == "invalid"
    assert fake_agent.calls == 0


def test_injection_through_parsed_input_symbol_is_ignored(fake_agent):
    parsed = dict(PARSED, givens=PARSED["givens"] + [
        {"symbol": "__import__", "value": 1, "unit": ""}])
    result = _check(["m = __import__"], parsed=parsed)
    assert result["results"][0]["status"] == "invalid"


# --- OrchestratorAgent.solution_for_work_check + cache ---------------------------

class _ScriptedClient:
    """Returns solver JSON, then validator JSON; records call count."""
    def __init__(self, verdict="PASS"):
        self.calls = 0
        self.verdict = verdict
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        if kwargs["system"] is SOLVER_PROMPT:
            return FakeResponse([FakeTextBlock(json.dumps(SOLUTION))])
        return FakeResponse([FakeTextBlock('{"overall_verdict": "%s"}' % self.verdict)])


def _agent(client):
    agent = OrchestratorAgent()
    agent.client = client
    return agent


def test_solution_for_work_check_solves_once_then_caches():
    client = _ScriptedClient()
    agent = _agent(client)
    assert agent.solution_for_work_check(PARSED)["final_answers"][0]["symbol"] == "N"
    assert client.calls == 2  # solver + validator
    agent.solution_for_work_check(PARSED)
    assert client.calls == 2  # cached


def test_solution_failing_validation_is_not_used_or_cached():
    client = _ScriptedClient(verdict="FAIL")
    agent = _agent(client)
    assert agent.solution_for_work_check(PARSED) is None
    assert solution_cache.get(PARSED) is None


def test_cached_solution_from_a_solve_turn_costs_nothing():
    solution_cache.remember(PARSED, SOLUTION)
    client = _ScriptedClient()
    assert _agent(client).solution_for_work_check(PARSED) == SOLUTION
    assert client.calls == 0


def test_cache_key_ignores_key_order_and_skips_empty_solutions():
    reordered = dict(reversed(list(PARSED.items())))
    solution_cache.remember(PARSED, SOLUTION)
    assert solution_cache.get(reordered) == SOLUTION
    solution_cache.remember({"other": 1}, {"final_answers": []})
    assert solution_cache.get({"other": 1}) is None


def test_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(solution_cache, "_MAX_ENTRIES", 3)
    for i in range(5):
        solution_cache.remember({"i": i}, SOLUTION)
    assert solution_cache.get({"i": 0}) is None
    assert solution_cache.get({"i": 4}) == SOLUTION


# --- A SOLVE turn fills the cache, so /check-work pays nothing extra ----------

class _SolveTurnClient:
    def __init__(self, verdict):
        self.messages = self
        self.verdict = verdict

    def create(self, **kw):
        from agents import orchestrator as o
        canned = {
            id(o.INPUT_PARSER_PROMPT): json.dumps(PARSED),
            id(o.STUDENT_MODELER_PROMPT): json.dumps({"current_state": "progressing"}),
            id(o.SOLVER_PROMPT): json.dumps(SOLUTION),
            id(o.VALIDATOR_PROMPT): json.dumps({"overall_verdict": self.verdict}),
            id(o.VISUALIZER_PROMPT): '<svg viewBox="0 0 10 10"></svg>',
        }.get(id(kw["system"]), "{}")
        return FakeResponse([FakeTextBlock(canned)])

    def stream(self, **kw):
        from conftest import FakeStreamCtx
        return FakeStreamCtx(["Here it is."])


@pytest.mark.parametrize("verdict, cached", [("PASS", True), ("FAIL", False)])
def test_stream_solve_turn_caches_only_validated_solution(verdict, cached):
    from test_run_stream_memory import RecordingMemory
    agent = _agent(_SolveTurnClient(verdict))
    agent.memory = RecordingMemory()
    events = list(agent.run_stream("Just solve it", [], {}, hint_level=4))

    meta = next(e for e in events if e["type"] == "meta")
    # What the browser will send back is exactly what the cache is keyed on.
    assert (solution_cache.get(meta["parsed_input"]) is not None) is cached


# --- Bug report input, exactly as typed in the browser ------------------------
# 10 kg block on a 30 degree incline, mu_k = 0.25, asked for a. Before the
# fix every line came back "! unrecognized name(s): N" / "f".

BLOCK = {
    "family": "kinetics",
    "scenario": {"gravity": 9.81},
    "givens": [{"symbol": "m", "value": 10, "unit": "kg"},
               {"symbol": "theta", "value": 30, "unit": "deg"},
               {"symbol": "mu_k", "value": 0.25, "unit": ""}],
    "unknowns_requested": [{"symbol": "a"}],
}
_BN = 10 * 9.81 * math.cos(math.radians(30))
BLOCK_SOLUTION = {
    "final_answers": [{"symbol": "a", "value": 9.81 * math.sin(math.radians(30)) - 0.25 * _BN / 10,
                       "unit": "m/s^2"}],
    # The solver names things its own way; the student writes N and f.
    "intermediate_values": [{"symbol": "F_N", "value": _BN, "unit": "N"},
                            {"symbol": "f_k", "value": 0.25 * _BN, "unit": "N"}],
}
BUG_REPORT_LINES = ["N = m*g*cos(30)", "f = 0.25*N", "N = m*g"]


def test_bug_report_input_checks_check_x(fake_agent):
    fake_agent.result = BLOCK_SOLUTION
    result = _check(BUG_REPORT_LINES, parsed=BLOCK)
    assert [r["status"] for r in result["results"]] == ["correct", "correct", "incorrect"]
    assert result["first_wrong_index"] == 2
    assert fake_agent.calls == 1
    # Line 3's left side is the solver's N: never shown.
    assert result["results"][2]["lhs_value"] is None
    assert f"{_BN:.4g}" not in result["results"][2]["detail"]


def test_bug_report_input_without_intermediate_values(fake_agent):
    # An older cached solution with only final answers: N and f can't be
    # checked, but lines still chain, so line 3 is caught against line 1.
    fake_agent.result = {"final_answers": BLOCK_SOLUTION["final_answers"]}
    result = _check(BUG_REPORT_LINES, parsed=BLOCK)
    assert [r["status"] for r in result["results"]] == ["defined", "defined", "incorrect"]
