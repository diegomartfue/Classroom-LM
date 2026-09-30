"""
Pilot item 8 — a referential DRAW request ("draw that", "same thing") with
NO prior conversation has nothing to refer to. The tutor must ask which
problem the student means instead of calling input_parser/visualizer and
inventing a setup.
"""
import json

from agents.orchestrator import (
    OrchestratorAgent,
    DRAW_NEEDS_CLARIFICATION_MESSAGE,
    _draw_needs_clarification,
)
from agents import orchestrator as o
from conftest import FakeResponse, FakeTextBlock, FakeThinkingBlock, FakeStreamCtx


# --- Pure helper -------------------------------------------------------------

def test_needs_clarification_when_referential_and_history_empty():
    assert _draw_needs_clarification({"problem_scope": "referential"}, []) is True
    assert _draw_needs_clarification({"problem_scope": "referential"}, None) is True


def test_no_clarification_when_referential_but_history_present():
    history = [{"role": "user", "content": "A 10 kg block on a 20 degree incline."}]
    assert _draw_needs_clarification({"problem_scope": "referential"}, history) is False


def test_no_clarification_when_self_contained_even_with_empty_history():
    assert _draw_needs_clarification({"problem_scope": "self_contained"}, []) is False


def test_no_clarification_when_scope_missing():
    # An unparseable/incomplete router response defaults to NOT blocking —
    # same permissive-default philosophy as _draw_history.
    assert _draw_needs_clarification({}, []) is False
    assert _draw_needs_clarification(None, []) is False


# --- End-to-end via run() / run_stream(), fully mocked ----------------------

class DrawScopeClient:
    def __init__(self, problem_scope):
        self.problem_scope = problem_scope
        self.messages = self
        self.create_systems = []

    def _canned(self, system) -> str:
        if system is o.ROUTER_PROMPT:
            payload = {"route": "DRAW", "rationale": "x", "confidence": 0.9}
            if self.problem_scope is not None:
                payload["problem_scope"] = self.problem_scope
            return json.dumps(payload)
        if system is o.INPUT_PARSER_PROMPT:
            return json.dumps({"family": "kinetics", "body_description": "a block"})
        if system is o.VISUALIZER_PROMPT:
            return '<svg viewBox="0 0 10 10"></svg>'
        return json.dumps({})

    def create(self, **kw):
        self.create_systems.append(kw["system"])
        return FakeResponse([FakeThinkingBlock(), FakeTextBlock(self._canned(kw["system"]))])

    def stream(self, **kw):
        self.create_systems.append(kw["system"])
        return FakeStreamCtx(["Here's the diagram."])


def test_run_asks_for_clarification_on_referential_draw_with_no_history():
    agent = OrchestratorAgent()
    agent.client = DrawScopeClient("referential")
    result = agent.run("draw that one", [], {})

    assert result["response"] == DRAW_NEEDS_CLARIFICATION_MESSAGE
    assert result["plan"]["decision"] == "CLARIFY"
    assert o.INPUT_PARSER_PROMPT not in agent.client.create_systems
    assert o.VISUALIZER_PROMPT not in agent.client.create_systems


def test_run_draws_normally_when_history_present():
    agent = OrchestratorAgent()
    agent.client = DrawScopeClient("referential")
    history = [{"role": "user", "content": "A 12 kg block on a 25 degree incline."}]
    result = agent.run("draw that one", history, {})

    assert result["plan"]["decision"] != "CLARIFY"
    assert o.INPUT_PARSER_PROMPT in agent.client.create_systems


def test_run_draws_normally_when_self_contained_even_without_history():
    agent = OrchestratorAgent()
    agent.client = DrawScopeClient("self_contained")
    result = agent.run("A 5 kg block on a 15 degree incline, draw the FBD.", [], {})

    assert result["plan"]["decision"] != "CLARIFY"
    assert o.INPUT_PARSER_PROMPT in agent.client.create_systems


def test_run_stream_asks_for_clarification_on_referential_draw_with_no_history():
    agent = OrchestratorAgent()
    agent.client = DrawScopeClient("referential")
    events = list(agent.run_stream("draw that one", [], {}))

    types = [e["type"] for e in events]
    assert types == ["meta", "token", "done"]
    meta = events[0]
    assert meta["decision"] == "CLARIFY"
    token = events[1]
    assert token["text"] == DRAW_NEEDS_CLARIFICATION_MESSAGE
    assert o.INPUT_PARSER_PROMPT not in agent.client.create_systems


def test_run_stream_clarification_turn_is_still_logged():
    from test_run_stream_memory import RecordingMemory
    agent = OrchestratorAgent()
    agent.client = DrawScopeClient("referential")
    agent.memory = RecordingMemory()

    list(agent.run_stream("draw that one", [], {}, session_id="s1", student_id="stu1"))
    assert len(agent.memory.logged_turns) == 1
    assert agent.memory.logged_turns[0][2]["decision"] == "CLARIFY"
    assert len(agent.memory.saved_models) == 1
