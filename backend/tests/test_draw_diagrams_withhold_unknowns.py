"""
Bug 4 — a DRAW-request diagram showed omega, alpha, v_B and a_B: all four
values the problem asked the student to find, while the tutor text withheld
them and asked the student to work them out.

Investigation finding: both live DRAW call sites (run() and run_stream())
already pass solution=None to visualizer() — draw_only()'s old solution=None
pattern is intact here, contrary to the bug report's stated cause. The two
tests below pin that down as a regression guard. The actual leak is that
solution=None alone never stopped the model from computing the values
itself: nothing in VISUALIZER_PROMPT forbade it. The fix is the prompt's new
UNKNOWNS rule (label unsolved target quantities symbolically, e.g. "omega =
?"); test_visualizer_prompt_forbids_self_computed_unknowns pins that down.
"""
import json

from agents.orchestrator import OrchestratorAgent
from agents import orchestrator as o
from conftest import FakeResponse, FakeTextBlock, FakeThinkingBlock, FakeStreamCtx

VALID_SVG = '<svg viewBox="0 0 100 100"><rect width="10" height="10"/></svg>'


class RecordingDrawClient:
    """Fake client for a DRAW turn: records the exact user_content the
    visualizer call received, so the test can confirm the solution it was
    given was None (serialized as JSON null), not a computed answer."""

    def __init__(self):
        self.messages = self
        self.visualizer_user_contents = []

    def _canned(self, system) -> str:
        if system is o.ROUTER_PROMPT:
            return json.dumps({"route": "DRAW", "rationale": "x", "confidence": 0.9})
        if system is o.INPUT_PARSER_PROMPT:
            return json.dumps({"body_description": "ladder against a wall", "is_in_scope": True})
        if system is o.VISUALIZER_PROMPT:
            return VALID_SVG
        if system is o.CONVERSATIONALIST_PROMPT:
            return "Here's the setup — work out omega and alpha yourself."
        return json.dumps({})

    def create(self, **kw):
        if kw["system"] is o.VISUALIZER_PROMPT:
            self.visualizer_user_contents.append(kw["messages"][0]["content"])
        return FakeResponse([FakeThinkingBlock(), FakeTextBlock(self._canned(kw["system"]))])

    def stream(self, **kw):
        return FakeStreamCtx(["Here's the setup — work out omega and alpha yourself."])


def test_run_draw_passes_no_solution_to_the_visualizer():
    agent = OrchestratorAgent()
    agent.client = RecordingDrawClient()

    agent.run("draw the FBD for this ladder problem", [], {})

    assert len(agent.client.visualizer_user_contents) == 1
    # solution=None serializes to JSON "null" in the visualizer's prompt —
    # confirms no solved values reach the model on a plain DRAW request.
    assert "Solver solution:\nnull" in agent.client.visualizer_user_contents[0]


def test_run_stream_draw_passes_no_solution_to_the_visualizer():
    agent = OrchestratorAgent()
    agent.client = RecordingDrawClient()

    list(agent.run_stream("draw the FBD for this ladder problem", [], {}))

    assert len(agent.client.visualizer_user_contents) == 1
    assert "Solver solution:\nnull" in agent.client.visualizer_user_contents[0]


def test_visualizer_prompt_forbids_self_computed_unknowns():
    # Regression guard for the actual fix: the prompt itself must forbid the
    # model from computing/showing a value it wasn't given, since
    # solution=None alone doesn't stop a capable model from deriving it.
    prompt = o.VISUALIZER_PROMPT
    assert "Never compute or derive a quantity yourself" in prompt
    assert "omega = ?" in prompt
    assert "v_B = ?" in prompt
