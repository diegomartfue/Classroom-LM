"""
DRAW requests must not be parsed against stale conversation history when the
message states its own problem (Bug 2: asking for a pendulum redrew the
block-on-an-incline from an earlier turn), but referential requests like
"draw that one" — or a tweak on the previous problem like "same thing but a
10 kg block" — still need the history.

This used to be decided by a standalone regex (_is_self_contained_problem).
That regex could not tell "a 10 kg block instead" (referential: it still
depends on the previous turn for the incline angle, friction, etc.) from a
genuinely new problem that happens to share the same shape of words. The
Router already reads the message as an LLM call and sees the conversation, so
the decision now rides along as a "problem_scope" field on its JSON output,
and _draw_history() just reads that field.
"""
import json

import pytest

from agents.orchestrator import OrchestratorAgent, _draw_history
from agents import orchestrator as o
from conftest import FakeResponse, FakeTextBlock, FakeThinkingBlock, FakeStreamCtx


HISTORY = [
    {"role": "user", "content": "A 10 kg block sits on a 30 degree incline."},
    {"role": "assistant", "content": "Here is the free-body diagram."},
]

VALID_SVG = '<svg viewBox="0 0 100 100"><rect width="10" height="10"/></svg>'


# ---------------------------------------------------------------------------
# Unit tests: _draw_history() against a route_decision dict directly.
# ---------------------------------------------------------------------------

def test_self_contained_scope_drops_history():
    decision = {"route": "DRAW", "problem_scope": "self_contained"}
    assert _draw_history(decision, HISTORY) == []


def test_referential_scope_keeps_history():
    decision = {"route": "DRAW", "problem_scope": "referential"}
    assert _draw_history(decision, HISTORY) == HISTORY


def test_missing_field_keeps_history():
    """An unparseable/incomplete router response must never strip history."""
    decision = {"route": "DRAW"}
    assert _draw_history(decision, HISTORY) == HISTORY


def test_unrecognized_value_keeps_history():
    decision = {"route": "DRAW", "problem_scope": "sort_of_both"}
    assert _draw_history(decision, HISTORY) == HISTORY


def test_none_route_decision_keeps_history():
    assert _draw_history(None, HISTORY) == HISTORY


def test_missing_history_is_normalized_to_a_list():
    decision = {"route": "DRAW", "problem_scope": "referential"}
    assert _draw_history(decision, None) == []


def test_self_contained_with_empty_history_is_still_empty_list():
    decision = {"route": "DRAW", "problem_scope": "self_contained"}
    assert _draw_history(decision, []) == []


# ---------------------------------------------------------------------------
# Callsite tests: drive run() / run_stream() end-to-end against a fake client
# that returns a controllable problem_scope from the Router, and record what
# input_parser actually received.
# ---------------------------------------------------------------------------

class ScopedDrawClient:
    """Fake Anthropic client for a DRAW turn. Router's problem_scope is
    injected (or omitted); every other agent gets a minimal canned response.
    Records the raw user_content passed to input_parser and to the router,
    so tests can check both what history shaped the parse and that the
    router itself never saw attached-document text.
    """

    def __init__(self, problem_scope):
        self.problem_scope = problem_scope  # None => field omitted entirely
        self.messages = self
        self.input_parser_calls = []
        self.router_calls = []

    def _canned(self, system, user_content) -> str:
        if system is o.ROUTER_PROMPT:
            self.router_calls.append(user_content)
            payload = {"route": "DRAW", "rationale": "x", "confidence": 0.9}
            if self.problem_scope is not None:
                payload["problem_scope"] = self.problem_scope
            return json.dumps(payload)
        if system is o.INPUT_PARSER_PROMPT:
            self.input_parser_calls.append(user_content)
            return json.dumps({"body_description": "block on incline", "is_in_scope": True})
        if system is o.VISUALIZER_PROMPT:
            return VALID_SVG
        if system is o.CONVERSATIONALIST_PROMPT:
            return "Here is the diagram."
        return json.dumps({})

    def create(self, **kw):
        user_content = kw["messages"][0]["content"]
        text = self._canned(kw["system"], user_content)
        return FakeResponse([FakeThinkingBlock(), FakeTextBlock(text)])

    def stream(self, **kw):
        return FakeStreamCtx(["Here is the diagram."])


def _agent(problem_scope):
    agent = OrchestratorAgent()
    agent.client = ScopedDrawClient(problem_scope)
    return agent


def test_run_self_contained_scope_parses_with_no_history():
    agent = _agent("self_contained")
    agent.run("A 2 kg ball swings on a 1.5 m string at 40 degrees.", HISTORY, {})
    assert len(agent.client.input_parser_calls) == 1
    assert "(no prior conversation)" in agent.client.input_parser_calls[0]


def test_run_referential_scope_parses_with_history():
    agent = _agent("referential")
    agent.run("draw that one again", HISTORY, {})
    assert len(agent.client.input_parser_calls) == 1
    assert "A 10 kg block sits on a 30 degree incline." in agent.client.input_parser_calls[0]


def test_run_missing_scope_field_falls_back_to_history():
    agent = _agent(None)
    agent.run("draw the FBD", HISTORY, {})
    assert "A 10 kg block sits on a 30 degree incline." in agent.client.input_parser_calls[0]


def test_run_stream_self_contained_scope_parses_with_no_history():
    agent = _agent("self_contained")
    list(agent.run_stream("A 2 kg ball swings on a 1.5 m string at 40 degrees.", HISTORY, {}))
    assert len(agent.client.input_parser_calls) == 1
    assert "(no prior conversation)" in agent.client.input_parser_calls[0]


def test_run_stream_referential_scope_parses_with_history():
    agent = _agent("referential")
    list(agent.run_stream("same thing but a 10 kg block", HISTORY, {}))
    assert len(agent.client.input_parser_calls) == 1
    assert "A 10 kg block sits on a 30 degree incline." in agent.client.input_parser_calls[0]


def test_attached_course_documents_never_influence_the_router():
    """The Router decides problem_scope from the student's own message alone.
    Quantities inside an attached course document must never leak into the
    router call — it never even sees source_block, self_contained or not."""
    agent = _agent("referential")
    source_text = "Example 4.2: a 12 kg block on a 15 degree ramp with mu_k = 0.25."
    list(agent.run_stream("draw that one", HISTORY, {}, source_text=source_text))
    assert len(agent.client.router_calls) == 1
    assert "12 kg block" not in agent.client.router_calls[0]
    assert source_text not in agent.client.router_calls[0]
    # And the (attached-document-blind) router's "referential" verdict is what
    # governs history — the document text still reaches input_parser via
    # message + source_block, but that's the message content, not the
    # history-gating decision.
    assert "A 10 kg block sits on a 30 degree incline." in agent.client.input_parser_calls[0]


def test_attached_course_documents_do_not_flip_a_self_contained_verdict():
    """Even when problem_scope is self_contained, history is dropped based on
    the router's field alone — not by re-inspecting the document text."""
    agent = _agent("self_contained")
    source_text = "Example 4.2: a 12 kg block on a 15 degree ramp with mu_k = 0.25."
    list(agent.run_stream("A 2 kg ball on a 1.5 m string at 40 degrees.", HISTORY, {},
                           source_text=source_text))
    assert "(no prior conversation)" in agent.client.input_parser_calls[0]
