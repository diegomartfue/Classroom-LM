"""
Tests for visualizer()'s SVG extraction (Bug 1 fix).

The visualizer now asks Opus for raw SVG and must pull a clean <svg>...</svg>
element out of whatever surrounds it (code fences, an <?xml ?> prolog,
leading prose), discard responses truncated at max_tokens, and return "" when
no SVG can be found — never garbage that would render as a blank/broken box.
"""
import logging

from agents.orchestrator import OrchestratorAgent
from agents import orchestrator as o
from model_config import OPUS_MODEL, VISUALIZER_MODEL
from conftest import FakeResponse, FakeTextBlock, FakeThinkingBlock


class _Usage:
    def __init__(self, output_tokens):
        self.output_tokens = output_tokens


class FakeVisualizerClient:
    """Fake Anthropic client whose messages.create() always returns one
    canned response, enough to drive visualizer() in isolation. Records the
    kwargs of every call so tests can inspect model/thinking/effort."""
    def __init__(self, response):
        self.messages = self
        self._response = response
        self.create_kwargs = None

    def create(self, **kw):
        self.create_kwargs = kw
        return self._response


def _agent_for(text, stop_reason="end_turn", usage_output_tokens=None):
    # Lead with a ThinkingBlock, like real Claude responses, to prove
    # extraction works through extract_text's block-type filtering.
    response = FakeResponse([FakeThinkingBlock(), FakeTextBlock(text)], stop_reason=stop_reason)
    if usage_output_tokens is not None:
        response.usage = _Usage(usage_output_tokens)
    agent = OrchestratorAgent()
    agent.client = FakeVisualizerClient(response)
    return agent


SVG = '<svg viewBox="0 0 100 100"><rect width="10" height="10"/></svg>'


def test_plain_valid_svg_is_returned_unchanged():
    agent = _agent_for(SVG)
    assert agent.visualizer({}, None) == SVG


def test_fenced_svg_is_extracted():
    text = f"```svg\n{SVG}\n```"
    agent = _agent_for(text)
    assert agent.visualizer({}, None) == SVG


def test_svg_with_xml_prolog_is_extracted_without_prolog():
    text = f'<?xml version="1.0" encoding="UTF-8"?>\n{SVG}'
    agent = _agent_for(text)
    assert agent.visualizer({}, None) == SVG


def test_svg_with_leading_prose_is_extracted():
    text = f"Here is the free-body diagram:\n\n{SVG}"
    agent = _agent_for(text)
    assert agent.visualizer({}, None) == SVG


def test_truncated_svg_with_no_closing_tag_returns_empty(caplog):
    text = '<svg viewBox="0 0 100 100"><rect width="10" height="10"/>'  # cut off mid-document
    agent = _agent_for(text)
    with caplog.at_level(logging.WARNING):
        result = agent.visualizer({}, None)
    assert result == ""
    assert any("no <svg> element" in r.message for r in caplog.records)


def test_max_tokens_stop_reason_returns_empty_and_logs_output_tokens(caplog):
    agent = _agent_for(SVG, stop_reason="max_tokens", usage_output_tokens=4096)
    with caplog.at_level(logging.WARNING):
        result = agent.visualizer({}, None)
    assert result == ""
    assert any("max_tokens" in r.message and "4096" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Model migration — visualizer() only moves to VISUALIZER_MODEL
# ("claude-opus-5-5"); every other agent keeps its current model. Opus 5.5
# still accepts thinking={"type": "adaptive"} (it's the *only* accepted
# mode — "disabled" 400s at every effort level, unlike Opus 5) and the same
# output_config.effort mechanism, and thinking tokens still count against
# max_tokens exactly as on Opus 5.
# ---------------------------------------------------------------------------

def test_visualizer_uses_the_dedicated_visualizer_model():
    assert VISUALIZER_MODEL == "claude-opus-5-5"
    agent = _agent_for(SVG)
    agent.visualizer({}, None)
    assert agent.client.create_kwargs["model"] == VISUALIZER_MODEL


def test_visualizer_still_sets_adaptive_thinking_and_effort():
    agent = _agent_for(SVG)
    agent.visualizer({}, None)
    kwargs = agent.client.create_kwargs
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"] == {"effort": "medium"}


def test_other_agents_are_unaffected_by_the_visualizer_model_switch():
    # creator() and pedagogical_planner() are the other two OPUS_MODEL
    # call sites — they must not have moved to VISUALIZER_MODEL.
    import inspect
    src = inspect.getsource(o.OrchestratorAgent.creator)
    assert "model=OPUS_MODEL" in src
    src = inspect.getsource(o.OrchestratorAgent.pedagogical_planner)
    assert "model=OPUS_MODEL" in src
    assert OPUS_MODEL != VISUALIZER_MODEL
