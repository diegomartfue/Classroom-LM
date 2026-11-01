"""
Pilot item 7 — leveled Hint button. hint_level=1-4 must be handled
deterministically: no Router call (route is forced to PROBLEM), no
Pedagogical Planner call (the plan is built in Python), and level 4 routes
through the exact same SOLVE path an organic "give me the answer" request
already uses — never a disguised HINT, so CONVERSATIONALIST_PROMPT's
"HINT: do NOT give the answer" rule is never at odds with it.
"""
import json
import math

import pytest

from agents import solution_cache
from agents.orchestrator import (
    OrchestratorAgent,
    _hint_for_level,
    _hint_ladder_plan,
    _HINT_LADDER,
    _pick_worked_step,
)
from agents import orchestrator as o
from conftest import FakeResponse, FakeTextBlock, FakeThinkingBlock, FakeStreamCtx


# --- Pure helpers ------------------------------------------------------------

def test_hint_for_level_returns_the_right_rung_for_a_known_family():
    text1, stage1 = _hint_for_level("kinematics", 1)
    text3, stage3 = _hint_for_level("kinematics", 3)
    assert text1 == _HINT_LADDER["kinematics"][0]
    assert stage1 == "fbd"
    assert text3 == _HINT_LADDER["kinematics"][2]
    assert stage3 == "solving"
    assert text1 != text3


def test_hint_for_level_falls_back_to_kinetics_for_unknown_family():
    text, _ = _hint_for_level("some_family_not_in_the_ladder", 1)
    assert text == _HINT_LADDER["kinetics"][0]


def test_hint_for_level_clamps_out_of_range():
    # Defensive: a level of 0 or 99 must not IndexError.
    assert _hint_for_level("kinetics", 0) == _hint_for_level("kinetics", 1)
    assert _hint_for_level("kinetics", 99) == _hint_for_level("kinetics", 3)


def test_hint_ladder_plan_level_1_is_a_hint_decision():
    plan = _hint_ladder_plan(1, {"family": "kinetics"})
    assert plan["decision"] == "HINT"
    assert plan["payload"]["hint_level"] == 1
    assert plan["payload"]["hint_text"] == _HINT_LADDER["kinetics"][0]
    assert plan["target_misconception"] is None


def test_hint_ladder_plan_level_4_is_a_solve_decision_not_a_hint():
    plan = _hint_ladder_plan(4, {"family": "kinetics"})
    assert plan["decision"] == "SOLVE"
    assert plan["payload"]["permission_source"] == "hint_ladder_exhausted"
    assert "hint_text" not in plan["payload"]


def test_hint_ladder_plan_uses_default_family_when_missing():
    plan = _hint_ladder_plan(2, {})  # no "family" key at all
    assert plan["payload"]["hint_text"] == _HINT_LADDER["kinetics"][1]


# --- End-to-end via run() / run_stream(), fully mocked ----------------------

class HintTrackingClient:
    """Records which system prompts were invoked, so tests can assert the
    Router and Pedagogical Planner were never called for a hint_level turn."""
    def __init__(self, family="kinetics"):
        self.family = family
        self.messages = self
        self.create_systems = []

    def _canned(self, system) -> str:
        if system is o.ROUTER_PROMPT:
            return json.dumps({"route": "PROBLEM", "rationale": "x", "confidence": 0.9})
        if system is o.INPUT_PARSER_PROMPT:
            return json.dumps({"family": self.family, "body_description": "block on incline"})
        if system is o.STUDENT_MODELER_PROMPT:
            return json.dumps({"current_state": "progressing"})
        if system is o.PEDAGOGICAL_PLANNER_PROMPT:
            # If this is ever called during a hint_level turn, the test
            # should fail loudly, not silently succeed on canned output.
            return json.dumps({"decision": "WAIT", "rationale": "SHOULD NOT BE CALLED"})
        if system is o.SOLVER_PROMPT:
            return json.dumps({"final_answers": {"a": "2 m/s^2"}})
        if system is o.VALIDATOR_PROMPT:
            return json.dumps({"overall_verdict": "PASS"})
        if system is o.VISUALIZER_PROMPT:
            return '<svg viewBox="0 0 10 10"></svg>'
        return json.dumps({})

    def create(self, **kw):
        self.create_systems.append(kw["system"])
        return FakeResponse([FakeThinkingBlock(), FakeTextBlock(self._canned(kw["system"]))])

    def stream(self, **kw):
        self.create_systems.append(kw["system"])
        return FakeStreamCtx(["Here's a nudge."])


def test_run_hint_level_1_skips_router_and_planner():
    agent = OrchestratorAgent()
    agent.client = HintTrackingClient()
    result = agent.run("Can I get a hint?", [], {}, hint_level=1)

    assert o.ROUTER_PROMPT not in agent.client.create_systems
    assert o.PEDAGOGICAL_PLANNER_PROMPT not in agent.client.create_systems
    assert result["plan"]["decision"] == "HINT"
    assert result["plan"]["payload"]["hint_level"] == 1
    assert result["route"] == "PROBLEM"


def test_run_hint_level_4_solves_without_router_or_planner():
    agent = OrchestratorAgent()
    agent.client = HintTrackingClient()
    result = agent.run("Show me the answer", [], {}, hint_level=4)

    assert o.ROUTER_PROMPT not in agent.client.create_systems
    assert o.PEDAGOGICAL_PLANNER_PROMPT not in agent.client.create_systems
    assert o.SOLVER_PROMPT in agent.client.create_systems  # the real SOLVE path ran
    assert o.VALIDATOR_PROMPT in agent.client.create_systems
    assert result["plan"]["decision"] == "SOLVE"
    assert result["plan"]["payload"]["permission_source"] == "hint_ladder_exhausted"
    assert result["solution"] is not None


def test_run_without_hint_level_still_calls_router_and_planner_normally():
    # Regression guard: the normal (non-button) path must be unaffected.
    agent = OrchestratorAgent()
    agent.client = HintTrackingClient()
    agent.run("A 10 kg block slides down a 20 degree incline.", [], {})
    assert o.ROUTER_PROMPT in agent.client.create_systems
    assert o.PEDAGOGICAL_PLANNER_PROMPT in agent.client.create_systems


def test_run_stream_hint_level_2_skips_router_and_planner():
    agent = OrchestratorAgent()
    agent.client = HintTrackingClient(family="kinematics")
    events = list(agent.run_stream("Can I get a bigger hint?", [], {}, hint_level=2))

    assert o.ROUTER_PROMPT not in agent.client.create_systems
    assert o.PEDAGOGICAL_PLANNER_PROMPT not in agent.client.create_systems
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["decision"] == "HINT"
    assert meta["route"] == "PROBLEM"


def test_run_stream_hint_level_4_solves():
    agent = OrchestratorAgent()
    agent.client = HintTrackingClient()
    events = list(agent.run_stream("Show me the answer already", [], {}, hint_level=4))

    assert o.PEDAGOGICAL_PLANNER_PROMPT not in agent.client.create_systems
    assert o.SOLVER_PROMPT in agent.client.create_systems
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["decision"] == "SOLVE"


def test_hint_level_turn_is_still_logged_with_the_forced_route():
    from test_run_stream_memory import RecordingMemory
    agent = OrchestratorAgent()
    agent.client = HintTrackingClient()
    agent.memory = RecordingMemory()

    list(agent.run_stream("Can I get a hint?", [], {}, session_id="s1", student_id="stu1", hint_level=1))
    assert len(agent.memory.logged_turns) == 1
    assert agent.memory.logged_turns[0][2]["route"] == "PROBLEM"
    assert agent.memory.logged_turns[0][2]["decision"] == "HINT"


# --- Level 3 carries out one real step with numbers ---------------------------


_N_VAL = round(10 * 9.81 * math.cos(math.radians(30)), 2)          # 84.96
_A_VAL = round(9.81 * (0.5 - 0.25 * math.cos(math.radians(30))), 3)  # final answer
LEVEL3_PARSED = {"family": "kinetics", "raw_summary": "10 kg block, 30 deg incline, mu_k 0.25",
                 "givens": [{"symbol": "m", "value": 10, "unit": "kg"}],
                 "unknowns_requested": [{"symbol": "a"}]}
LEVEL3_SOLUTION = {
    "equations": [{"name": "perp", "symbolic": "N = m*g*cos(theta)",
                   "numeric": "N = 10*9.81*cos(30deg)"}],
    "final_answers": [{"symbol": "a", "value": _A_VAL, "unit": "m/s^2"}],
    "intermediate_values": [{"symbol": "N", "value": _N_VAL, "unit": "N",
                             "description": "normal force"}],
}


class WorkedStepClient(HintTrackingClient):
    def __init__(self, verdict="PASS"):
        super().__init__()
        self.verdict = verdict
        self.stream_contents = []

    def _canned(self, system):
        if system is o.INPUT_PARSER_PROMPT:
            return json.dumps(LEVEL3_PARSED)
        if system is o.SOLVER_PROMPT:
            return json.dumps(LEVEL3_SOLUTION)
        if system is o.VALIDATOR_PROMPT:
            return json.dumps({"overall_verdict": self.verdict})
        return super()._canned(system)

    def stream(self, **kw):
        self.stream_contents.append(kw["messages"][0]["content"])
        return super().stream(**kw)


@pytest.fixture
def empty_solution_cache():
    solution_cache.clear()
    yield
    solution_cache.clear()


def _bundle(client) -> str:
    [content] = [c for c in client.stream_contents if "Context bundle" in c]
    return content


def test_pick_worked_step_skips_final_answers():
    step = _pick_worked_step(LEVEL3_SOLUTION)
    assert step["symbol"] == "N" and step["value"] == _N_VAL
    assert step["equation"] == "N = m*g*cos(theta)"
    only_finals = {"final_answers": [{"symbol": "N", "value": 1}],
                   "intermediate_values": [{"symbol": "N", "value": 1}]}
    assert _pick_worked_step(only_finals) is None
    assert _pick_worked_step(None) is None


def test_stream_level_3_hands_one_numeric_step_but_not_the_answer(empty_solution_cache):
    agent = OrchestratorAgent()
    agent.client = WorkedStepClient()
    events = list(agent.run_stream("Show me one worked step", [], {}, hint_level=3))

    bundle = _bundle(agent.client)
    assert '"worked_step"' in bundle and str(_N_VAL) in bundle
    # Final answer never reaches the conversationalist or the browser.
    assert str(_A_VAL) not in bundle and "final_answers" not in bundle
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["decision"] == "HINT" and meta.get("solution") is None
    assert str(_A_VAL) not in json.dumps(events)
    # Prompt tells the conversationalist to actually do the step.
    assert "payload.worked_step" in o.CONVERSATIONALIST_PROMPT


def test_run_level_3_also_gets_the_worked_step(empty_solution_cache):
    agent = OrchestratorAgent()
    agent.client = WorkedStepClient()
    result = agent.run("Show me one worked step", [], {}, hint_level=3)
    assert result["plan"]["payload"]["worked_step"]["value"] == _N_VAL
    assert result["solution"] is None


def test_level_3_uses_cached_solution_without_solving_again(empty_solution_cache):
    solution_cache.remember(LEVEL3_PARSED, LEVEL3_SOLUTION)
    agent = OrchestratorAgent()
    agent.client = WorkedStepClient()
    list(agent.run_stream("Show me one worked step", [], {}, hint_level=3))
    assert o.SOLVER_PROMPT not in agent.client.create_systems
    assert '"worked_step"' in _bundle(agent.client)


def test_level_3_falls_back_to_text_hint_when_validation_fails(empty_solution_cache):
    agent = OrchestratorAgent()
    agent.client = WorkedStepClient(verdict="FAIL")
    list(agent.run_stream("Show me one worked step", [], {}, hint_level=3))
    bundle = _bundle(agent.client)
    assert '"worked_step"' not in bundle
    assert _HINT_LADDER["kinetics"][2][:20] in bundle


def test_levels_1_and_2_still_never_call_the_solver(empty_solution_cache):
    for level in (1, 2):
        agent = OrchestratorAgent()
        agent.client = WorkedStepClient()
        list(agent.run_stream("hint", [], {}, hint_level=level))
        assert o.SOLVER_PROMPT not in agent.client.create_systems
