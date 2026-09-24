"""
Bug 3 (second half) — if input_parser's response fails to parse, the
visualizer must never be called with the resulting {"parse_error": ...,
"raw_response": ...} dict. Guessing a diagram from a broken parse is worse
than no diagram at all; both DRAW paths (run() and run_stream()) must skip
drawing and fall through to the same "diagram not rendered" signal already
used for a genuinely failed visualizer call.
"""
import json

from agents.orchestrator import OrchestratorAgent
from agents import orchestrator as o
from conftest import FakeResponse, FakeTextBlock, FakeThinkingBlock, FakeStreamCtx


class BrokenInputParserClient:
    """Fake client: DRAW routing succeeds, but input_parser's response is
    truncated JSON with no closing brace — the exact real-world failure
    mode from Bug 3's log ("Extra data" / unterminated string)."""
    TRUNCATED_INPUT_PARSE = '{\n  "body_description": "ladder leaning against a wal'

    def __init__(self):
        self.messages = self
        self.create_systems = []
        self.stream_calls = []

    def _canned(self, system) -> str:
        if system is o.ROUTER_PROMPT:
            return json.dumps({"route": "DRAW", "rationale": "x", "confidence": 0.9})
        if system is o.INPUT_PARSER_PROMPT:
            return self.TRUNCATED_INPUT_PARSE
        if system is o.CONVERSATIONALIST_PROMPT:
            return "I couldn't quite parse that setup — could you rephrase it?"
        return json.dumps({})

    def create(self, **kw):
        self.create_systems.append(kw["system"])
        return FakeResponse([FakeThinkingBlock(), FakeTextBlock(self._canned(kw["system"]))])

    def stream(self, **kw):
        self.stream_calls.append(kw)
        return FakeStreamCtx(["I couldn't quite parse that setup."])


def test_run_skips_visualizer_when_input_parser_fails_to_parse():
    agent = OrchestratorAgent()
    agent.client = BrokenInputParserClient()

    result = agent.run("draw the FBD for this ladder problem", [], {})

    assert o.VISUALIZER_PROMPT not in agent.client.create_systems
    assert result["diagram_svg"] == ""
    assert result["route"] == "DRAW"


def test_run_stream_skips_visualizer_when_input_parser_fails_to_parse():
    agent = OrchestratorAgent()
    agent.client = BrokenInputParserClient()

    events = list(agent.run_stream("draw the FBD for this ladder problem", [], {}))

    assert o.VISUALIZER_PROMPT not in agent.client.create_systems
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["diagram_svg"] == ""


def test_run_logs_a_warning_and_does_not_raise(caplog):
    import logging
    agent = OrchestratorAgent()
    agent.client = BrokenInputParserClient()

    with caplog.at_level(logging.WARNING):
        agent.run("draw the FBD for this ladder problem", [], {})  # must not raise

    assert any(
        "input_parser failed to parse" in r.message for r in caplog.records
    )
