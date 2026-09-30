"""
Pilot item 10 — eval harness (evals/run.py). Mocked mode only; live mode is
asserted to refuse without --yes and never to construct an agent.

The grader tests feed deliberately bad event streams, so a harness that
passes everything regardless is caught here.
"""
import copy
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals import run  # noqa: E402
from evals.pilot_cases import CASES  # noqa: E402

CASE = {c["id"]: c for c in CASES}


def _events(route, decision, text, solution=None):
    meta = {"type": "meta", "route": route, "decision": decision}
    if solution is not None:
        meta["solution"] = solution
    return [meta, {"type": "token", "text": text}, {"type": "done"}]


def _failed(checks):
    return {c["check"] for c in checks if not c["passed"]}


# --- Suite ---------------------------------------------------------------------

def test_cases_are_well_formed():
    assert len(CASES) == 8
    assert len({c["id"] for c in CASES}) == 8
    for c in CASES:
        assert c["expect"]["route"] and c["expect"]["decisions"]


def test_mocked_suite_passes_end_to_end():
    results = run.run_mocked(CASES)
    failures = {r["id"]: _failed(r["checks"]) for r in results if _failed(r["checks"])}
    assert failures == {}


def test_main_mocked_exit_code_and_json_out(tmp_path, capsys):
    out = tmp_path / "r.json"
    assert run.main(["--case", "pendulum", "--out", str(out)]) == 0
    assert out.exists()
    assert "1/1 cases passed" in capsys.readouterr().out


def test_main_rejects_unknown_case():
    with pytest.raises(SystemExit):
        run.main(["--case", "nope"])


def test_live_mode_without_yes_never_runs(monkeypatch, capsys):
    def _boom(*a, **k):
        raise AssertionError("live run started without --yes")
    monkeypatch.setattr(run, "run_live", _boom)
    assert run.main(["--mode", "live"]) == 2
    out = capsys.readouterr().out
    assert "TOTAL" in out and "--yes" in out


def test_cost_estimate_prices_every_case():
    rows, total = run.estimate_cost(CASES)
    assert len(rows) == 8 and total > 0
    priced = {r["id"]: r["priced_as"] for r in rows}
    assert priced["draw_that_no_context"] == "ROUTER_ONLY"
    assert priced["crate_incline"] == "PROBLEM_SOLVE"
    assert priced["beam_reactions"] == "PROBLEM_HINT"


# --- Grader catches bad turns ---------------------------------------------------

def test_grader_flags_wrong_solved_answer():
    case = CASE["crate_incline"]
    bad = {"final_answers": [{"symbol": "a", "value": 4.9, "unit": "m/s^2"}]}
    checks = run.grade(case, _events("PROBLEM", "SOLVE", "a = 4.9 m/s^2", bad))
    assert "answer:a" in _failed(checks)


def test_grader_accepts_answer_under_a_different_symbol():
    case = CASE["pendulum"]
    value = case["expect"]["answers"]["v"][0]
    sol = {"final_answers": [{"symbol": "v_B", "value": value, "unit": "m/s"}]}
    assert _failed(run.grade(case, _events("PROBLEM", "SOLVE", "done", sol))) == set()


def test_grader_flags_answer_leak_on_hint():
    case = CASE["ladder_kinematics"]
    checks = run.grade(case, _events("PROBLEM", "HINT", "The top moves down at 0.60 m/s."))
    assert "no_leak:v_top" in _failed(checks)


def test_grader_integer_answers_only_leak_with_unit():
    case = CASE["beam_reactions"]
    ok = run.grade(case, _events("PROBLEM", "HINT", "Step 4: take moments about A. Step 8: check."))
    assert _failed(ok) == set()
    leaked = run.grade(case, _events("PROBLEM", "HINT", "By is 4 kN and Ay is 8 kN."))
    assert {"no_leak:Ay", "no_leak:By"} <= _failed(leaked)


def test_grader_allows_repeating_the_students_own_number():
    case = CASE["pushed_box"]
    checks = run.grade(case, _events("PROBLEM", "ASK", "You said 2.39 m/s^2. That's right!"))
    assert _failed(checks) == set()


def test_grader_flags_wrong_route_and_decision():
    case = CASE["crate_incline"]
    checks = run.grade(case, _events("CONCEPT", "CONCEPT", "Friction opposes motion."))
    assert {"route", "decision"} <= _failed(checks)


def test_grader_flags_english_reply_to_spanish_problem():
    case = CASE["spanish_incline"]
    value = case["expect"]["answers"]["a"][0]
    sol = {"final_answers": [{"symbol": "a", "value": value, "unit": "m/s^2"}]}
    text = "The block slides down the incline, so the acceleration is g sin(25) and it is 4.15 m/s^2."
    assert "language:es" in _failed(run.grade(case, _events("PROBLEM", "SOLVE", text, sol)))


def test_grader_flags_draw_that_guessing():
    case = CASE["draw_that_no_context"]
    checks = run.grade(case, _events("DRAW", "DRAW", "Here is a block on an incline."),
                       called_agents=["router", "input_parser", "visualizer"])
    assert {"decision", "not_called:input_parser", "not_called:visualizer",
            "response_contains_any"} <= _failed(checks)


def test_grader_flags_error_event_and_missing_meta():
    checks = run.grade(CASE["pendulum"], [{"type": "error", "text": "boom"}])
    assert "no_error" in _failed(checks)


def test_mocked_run_catches_a_broken_pipeline():
    # A mock whose solver returns the wrong value must fail the suite —
    # proves mocked mode grades real pipeline output, not the case file.
    case = copy.deepcopy(CASE["crate_incline"])
    case["mock"]["solver"] = {"final_answers": [{"symbol": "a", "value": 1.0, "unit": "m/s^2"}]}
    [result] = run.run_mocked([case])
    assert "answer:a" in _failed(result["checks"])
