"""
ADDITIONAL FINDING #3 — mocked run_stream() orchestration integration tests.

Covers CONCEPT / CREATE / PROBLEM / DRAW with a fake client that routes canned
responses by system prompt. Every create() also leads with a ThinkingBlock, so
the whole pipeline is exercised against the Sonnet-5 fix end to end.
"""
import json
import pytest

from agents.orchestrator import OrchestratorAgent
from agents import orchestrator as o
from conftest import FakeResponse, FakeTextBlock, FakeThinkingBlock, FakeStreamCtx


class RoutingClient:
    """Fake Anthropic client that returns canned JSON/text keyed by the system
    prompt, so run_stream drives a realistic multi-agent pipeline offline."""
    STREAM_CHUNKS = ["Here is the answer: ", "$F = ma$."]

    def __init__(self, route, decision="HINT"):
        self.route = route
        self.decision = decision
        self.messages = self
        self.create_systems = []   # ordered list of upstream agents invoked
        self.stream_calls = []     # kwargs of the final streamed agent

    def _canned(self, system) -> str:
        if system is o.ROUTER_PROMPT:
            return json.dumps({"route": self.route, "rationale": "x", "confidence": 0.9})
        if system is o.INPUT_PARSER_PROMPT:
            return json.dumps({"body_description": "block on incline", "is_in_scope": True})
        if system is o.STUDENT_MODELER_PROMPT:
            return json.dumps({"mastered": [], "struggling": ["newtons_second_law"]})
        if system is o.PEDAGOGICAL_PLANNER_PROMPT:
            return json.dumps({"decision": self.decision})
        if system is o.SOLVER_PROMPT:
            return json.dumps({"final_answers": {"a": "2 m/s^2"}})
        if system is o.CREATOR_PROMPT:
            return json.dumps({"target_concept": "relative motion",
                               "problems": [{"statement": "A block slides..."}]})
        if system is o.VALIDATOR_PROMPT:
            return json.dumps({"overall_verdict": "PASS"})
        if system is o.VISUALIZER_PROMPT:
            return json.dumps({"renderable": False})
        if system is o.SCHEMATIC_LAYOUT_PROMPT:
            return json.dumps({"drawable": False})
        return json.dumps({})

    def create(self, **kw):
        self.create_systems.append(kw["system"])
        # Lead with a ThinkingBlock to exercise extract_text through the pipeline.
        return FakeResponse([FakeThinkingBlock(), FakeTextBlock(self._canned(kw["system"]))])

    def stream(self, **kw):
        self.stream_calls.append(kw)
        return FakeStreamCtx(list(self.STREAM_CHUNKS))


def _run(route, message, history=None, decision="HINT"):
    agent = OrchestratorAgent()
    client = RoutingClient(route, decision)
    agent.client = client
    events = list(agent.run_stream(message, history or [], {}, ""))
    return events, client


def _types(events):
    return [e["type"] for e in events]


def _final_user_content(client):
    return client.stream_calls[-1]["messages"][0]["content"]


def test_concept_streams_direct_tutor_with_history():
    hist = [{"role": "user", "content": "My name is Diego."}]
    events, client = _run("CONCEPT", "what is my name?", hist)
    types = _types(events)
    assert "meta" in types and "token" in types and types[-1] == "done"
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["decision"] == "CONCEPT"
    # Final (streamed) agent got the prior conversation.
    assert "Previous conversation:" in _final_user_content(client)
    assert "My name is Diego." in _final_user_content(client)
    # Streamed text is reassembled from chunks.
    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert "$F = ma$" in text


def test_create_runs_full_pipeline_and_streams_conversationalist():
    events, client = _run("CREATE", "make me a practice problem")
    assert _types(events)[-1] == "done"
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["decision"] == "CREATE"
    # Modeler (x2: modeler + identifier), planner, creator, visualizer, validator.
    seen = client.create_systems
    assert seen.count(o.STUDENT_MODELER_PROMPT) == 2
    assert o.PEDAGOGICAL_PLANNER_PROMPT in seen
    assert o.CREATOR_PROMPT in seen
    assert o.VISUALIZER_PROMPT in seen
    assert o.VALIDATOR_PROMPT in seen
    # Final response is streamed via the conversationalist.
    assert client.stream_calls[-1]["system"] is o.CONVERSATIONALIST_PROMPT


def test_problem_hint_does_not_call_solver():
    events, client = _run("PROBLEM", "hint on this beam problem", decision="HINT")
    assert _types(events)[-1] == "done"
    assert o.INPUT_PARSER_PROMPT in client.create_systems
    assert o.SOLVER_PROMPT not in client.create_systems  # HINT skips the solver


def test_problem_solve_calls_solver_validator_visualizer():
    events, client = _run("PROBLEM", "solve this beam problem", decision="SOLVE")
    assert _types(events)[-1] == "done"
    seen = client.create_systems
    assert o.SOLVER_PROMPT in seen
    assert o.VALIDATOR_PROMPT in seen
    assert o.VISUALIZER_PROMPT in seen


def test_draw_streams_conversationalist():
    events, client = _run("DRAW", "draw the FBD of a block on an incline")
    types = _types(events)
    assert types[-1] == "done"
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["decision"] == "DRAW"
    assert o.VISUALIZER_PROMPT in client.create_systems
    assert client.stream_calls[-1]["system"] is o.CONVERSATIONALIST_PROMPT


def test_upstream_agent_failure_is_caught_and_yields_a_friendly_error():
    # Pilot hardening (item 3, "no dead ends"): run_stream() now catches a
    # mid-stream failure itself, exactly like run() already does, so every
    # exit path is logged and the student model is still saved — it does
    # NOT propagate raw. main.py's own except block around agent.run_stream()
    # is now a secondary safety net (still useful for anything raised
    # outside the generator, e.g. in FastAPI's own request handling), not the
    # only line of defense.
    class Boom(RoutingClient):
        def create(self, **kw):
            if kw["system"] is o.STUDENT_MODELER_PROMPT:
                raise RuntimeError("boom in student modeler")
            return super().create(**kw)

    agent = OrchestratorAgent()
    agent.client = Boom("CREATE")
    events = list(agent.run_stream("make a problem", [], {}, ""))
    assert events[-2]["type"] == "error"
    assert events[-1]["type"] == "done"


def test_upstream_agent_failure_propagates_out_of_the_inner_event_generator():
    # _run_stream_events() (the pipeline itself, pre-memory-wrapper) still
    # raises raw — only the public run_stream() wrapper catches it.
    class Boom(RoutingClient):
        def create(self, **kw):
            if kw["system"] is o.STUDENT_MODELER_PROMPT:
                raise RuntimeError("boom in student modeler")
            return super().create(**kw)

    agent = OrchestratorAgent()
    agent.client = Boom("CREATE")
    with pytest.raises(RuntimeError):
        list(agent._run_stream_events("make a problem", [], {}, ""))
