"""
A DRAW follow-up must draw the problem in play, and nothing else.

Pilot bug (traces/seed-1, turn 5): after a two-block pulley problem, a hint
ladder and a check-work, "draw the free body diagram for the hanging block"
got a correct text reply but a placeholder SVG ("No problem geometry
available ... Please restate the problem"), and the reply said "Here's the
free-body diagram". Causes: the DRAW parse lost the problem (INPUT_PARSER_PROMPT
returns "unclear" for a follow-up, and a self_contained Router verdict dropped
the history), nothing stopped the visualizer drawing an empty problem, and the
placeholder counted as a rendered diagram.

Every test drives run() and run_stream() with a fake client. No API calls.
"""
import json

import pytest

import main
from agents import orchestrator as o
from agents.memory import SessionMemory
from agents.orchestrator import (
    DRAW_NEEDS_CLARIFICATION_MESSAGE,
    DRAW_NO_PROBLEM_MESSAGE,
    MAX_HISTORY_MESSAGES,
    OrchestratorAgent,
    _screen_svg,
)
from conftest import FakeResponse, FakeStreamCtx, FakeTextBlock, FakeThinkingBlock
from test_run_stream_memory import RecordingMemory

PULLEY = ("A 10 kg block sits on a 25° incline and is connected by a rope over a "
          "frictionless pulley at the top to a 6 kg block hanging straight down. The "
          "kinetic friction coefficient between the block and incline is 0.2. Find the "
          "acceleration of the system and the tension in the rope.")

# The seed-1 conversation up to the draw request.
HISTORY = [
    {"role": "user", "content": PULLEY},
    {"role": "assistant", "content": "Sketch a free-body diagram for each block separately."},
    {"role": "user", "content": "I think the tension is just 6 times 9.81 = 58.9 N"},
    {"role": "assistant", "content": "That would only be true if block B wasn't accelerating."},
    {"role": "user", "content": "Can I get a hint?"},
    {"role": "assistant", "content": "What forces act on block B?"},
    {"role": "user", "content": "Can I get a bigger hint?"},
    {"role": "assistant", "content": "Block B has gravity down and tension up."},
]

FOLLOW_UP = "draw the free body diagram for the hanging block"
NEW_PROBLEM = "draw a 5 kg box on a flat floor pulled by 20 N at 30°"

PULLEY_PARSE = {
    "problem_type": "dynamics", "family": "kinetics",
    "body_description": "10 kg block on a 25 degree incline tied over a pulley to a 6 kg hanging block",
    "scenario": {"bodies": [{"label": "A", "kind": "particle", "mass_kg": 10},
                            {"label": "B", "kind": "particle", "mass_kg": 6}],
                 "incline_angle_deg": 25, "friction": {"mu_k": 0.2}},
    "givens": [{"symbol": "m_B", "value": 6, "unit": "kg"}],
    "raw_summary": "10 kg block on incline connected to a 6 kg block hanging straight down",
}
BOX_PARSE = {
    "problem_type": "dynamics", "family": "kinetics",
    "body_description": "5 kg box on a flat floor pulled by 20 N at 30 degrees",
    "scenario": {"bodies": [{"label": "box", "kind": "particle", "mass_kg": 5}]},
    "givens": [{"symbol": "P", "value": 20, "unit": "N"}],
}
UNCLEAR_PARSE = {
    "problem_type": "unclear", "scenario": {"bodies": [], "gravity": 9.81},
    "givens": [], "unknowns_requested": [],
    "raw_summary": "follow-up without a problem statement",
}

GOOD_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 400">'
            '<rect x="250" y="150" width="100" height="60"/><text x="300" y="300">W = 58.9 N</text></svg>')
# The placeholder from traces/seed-1/5.json, trimmed.
PLACEHOLDER_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 400">'
                   '<rect x="180" y="130" width="240" height="120" stroke-dasharray="6,4"/>'
                   '<text x="300" y="60">No problem geometry available</text>'
                   '<text x="300" y="190">body placeholder (not specified)</text>'
                   '<text x="300" y="300">Please restate the problem: bodies, supports, loads.</text>'
                   '</svg>')
NO_DIAGRAM_SVG = '<svg xmlns="http://www.w3.org/2000/svg" data-diagram="none"></svg>'


def _latest(user_content: str) -> str:
    return user_content.rsplit("Student's latest message:\n", 1)[-1]


class DrawClient:
    """Fake client. The Router returns `scope`; the parser behaves like the
    real one should with the new DRAW instructions: a complete new problem
    parses on its own, a follow-up resolves to the pulley problem when it is
    anywhere in what the parser sees, otherwise "unclear" with no bodies."""

    def __init__(self, scope="referential", visualizer_svg=GOOD_SVG, parse=None):
        self.scope = scope
        self.visualizer_svg = visualizer_svg
        self.parse = parse  # forces every parse to this result when set
        self.messages = self
        self.parser_calls = []
        self.visualizer_inputs = []
        self.conversationalist_contexts = []

    def _parse(self, content):
        if self.parse is not None:
            return self.parse
        latest = _latest(content)
        if "5 kg box" in latest:
            return BOX_PARSE
        if "kg" in latest and "draw" not in latest.lower():
            # A created-problem statement parsed on its own (multi-draw).
            return {**BOX_PARSE, "body_description": latest[:40]}
        if "hanging" in latest and "6 kg block hanging" in content:
            return {**PULLEY_PARSE, "draw_focus": {"bodies": ["B"],
                                                   "description": "the hanging 6 kg block alone"}}
        return UNCLEAR_PARSE

    def create(self, **kw):
        system, content = kw["system"], kw["messages"][0]["content"]
        if system is o.ROUTER_PROMPT:
            text = json.dumps({"route": "DRAW", "rationale": "x", "confidence": 0.9,
                               "problem_scope": self.scope})
        elif system is o.INPUT_PARSER_PROMPT:
            self.parser_calls.append(content)
            text = json.dumps(self._parse(content))
        elif system is o.VISUALIZER_PROMPT:
            self.visualizer_inputs.append(content)
            text = self.visualizer_svg
        elif system is o.CONVERSATIONALIST_PROMPT:
            self.conversationalist_contexts.append(content)
            text = "Block B has two forces on it."
        else:
            text = "{}"
        return FakeResponse([FakeThinkingBlock(), FakeTextBlock(text)])

    def stream(self, **kw):
        if kw["system"] is o.CONVERSATIONALIST_PROMPT:
            self.conversationalist_contexts.append(kw["messages"][0]["content"])
        return FakeStreamCtx(["Block B has two forces on it."])


def _drive(mode, client, message, history, active_problem=None, memory=None):
    """One DRAW turn through run() or run_stream(). Returns
    (reply text, diagram_svg sent, events or None)."""
    agent = OrchestratorAgent()
    agent.client = client
    agent.memory = memory or RecordingMemory()
    if mode == "run":
        result = agent.run(message, history, {}, session_id="s1", student_id="P01",
                           active_problem=active_problem)
        return result["response"], result.get("diagram_svg") or "", None
    events = list(agent.run_stream(message, history, {}, session_id="s1", student_id="P01",
                                   active_problem=active_problem))
    meta = next(e for e in events if e["type"] == "meta")
    reply = "".join(e["text"] for e in events if e["type"] == "token")
    return reply, meta["diagram_svg"], events


def _visualization(context: str) -> dict:
    """The visualization object the conversationalist was given."""
    bundle = json.loads(context.split("Context bundle:\n", 1)[1])
    return bundle["visualization"]


BOTH = pytest.mark.parametrize("mode", ["run", "run_stream"])


# --- 1. Referential follow-up gets the history and draws -----------------------

@BOTH
def test_referential_follow_up_parses_with_history_and_draws_the_focus(mode):
    client = DrawClient(scope="referential")
    reply, svg, _ = _drive(mode, client, FOLLOW_UP, HISTORY)

    [parse_input] = client.parser_calls
    assert PULLEY in parse_input
    assert "TASK: the student wants a diagram." in parse_input
    assert svg == GOOD_SVG
    [visualizer_input] = client.visualizer_inputs
    assert '"draw_focus"' in visualizer_input and '"B"' in visualizer_input
    assert FOLLOW_UP in visualizer_input  # draw_request: the student's own words
    assert _visualization(client.conversationalist_contexts[-1]) == {
        "diagram_rendered": True, "diagram_status": "drawn"}


@BOTH
def test_follow_up_misjudged_self_contained_is_reparsed_with_history(mode):
    """The likely seed-1 path: the Router called the follow-up self_contained,
    so the first parse saw no history and found no bodies."""
    client = DrawClient(scope="self_contained")
    _, svg, _ = _drive(mode, client, FOLLOW_UP, HISTORY)

    first, retry = client.parser_calls
    assert "(no prior conversation)" in first
    assert PULLEY in retry
    assert svg == GOOD_SVG


# --- 2. A brand-new problem mid-conversation draws the new problem -------------

@BOTH
def test_new_self_contained_problem_mid_conversation_draws_the_new_one(mode):
    client = DrawClient(scope="self_contained")
    _, svg, _ = _drive(mode, client, NEW_PROBLEM, HISTORY, active_problem=PULLEY_PARSE)

    [parse_input] = client.parser_calls
    assert "(no prior conversation)" in parse_input
    assert PULLEY not in parse_input and "ACTIVE PROBLEM" not in parse_input
    [visualizer_input] = client.visualizer_inputs
    assert "5 kg box" in visualizer_input and "6 kg" not in visualizer_input
    assert svg == GOOD_SVG


# --- 3. "draw that" with nothing to refer to still asks ------------------------

@BOTH
def test_draw_that_with_no_history_asks_which_problem(mode):
    client = DrawClient(scope="referential")
    reply, svg, _ = _drive(mode, client, "draw that", [])
    assert reply == DRAW_NEEDS_CLARIFICATION_MESSAGE
    assert svg == ""
    assert client.parser_calls == [] and client.visualizer_inputs == []


# --- 4. No bodies: no visualizer call, no diagram, no claim of one -------------

@BOTH
def test_no_bodies_skips_the_visualizer_and_says_so(mode):
    client = DrawClient(scope="referential", parse=UNCLEAR_PARSE)
    memory = RecordingMemory()
    reply, svg, _ = _drive(mode, client, FOLLOW_UP, HISTORY, memory=memory)

    assert client.visualizer_inputs == []
    assert svg == ""
    assert reply == DRAW_NO_PROBLEM_MESSAGE
    assert "here's" not in reply.lower() and "below" not in reply.lower()
    assert client.conversationalist_contexts == []  # fixed reply, no model call
    assert memory.logged_turns[-1][2]["diagram_status"] == "skipped_no_bodies"


@BOTH
def test_parse_failure_is_recorded_as_parse_failed(mode):
    client = DrawClient(scope="referential")
    original_create = client.create

    def create(**kw):  # the parser's reply is truncated JSON
        if kw["system"] is o.INPUT_PARSER_PROMPT:
            return FakeResponse([FakeTextBlock('{"body_description": "trunc')])
        return original_create(**kw)
    client.create = create
    memory = RecordingMemory()
    reply, svg, _ = _drive(mode, client, FOLLOW_UP, HISTORY, memory=memory)

    assert svg == "" and client.visualizer_inputs == []
    assert reply == DRAW_NO_PROBLEM_MESSAGE
    assert memory.logged_turns[-1][2]["diagram_status"] == "parse_failed"


# --- 5. Placeholder output is never sent ---------------------------------------

@BOTH
@pytest.mark.parametrize("placeholder", [PLACEHOLDER_SVG, NO_DIAGRAM_SVG])
def test_placeholder_diagram_is_suppressed_and_reply_is_told(mode, placeholder):
    client = DrawClient(scope="referential", visualizer_svg=placeholder)
    memory = RecordingMemory()
    _, svg, _ = _drive(mode, client, FOLLOW_UP, HISTORY, memory=memory)

    assert len(client.visualizer_inputs) == 1
    assert svg == ""
    assert _visualization(client.conversationalist_contexts[-1]) == {
        "diagram_rendered": False, "diagram_status": "suppressed_placeholder"}
    data = memory.logged_turns[-1][2]
    assert data["diagram_status"] == "suppressed_placeholder"
    assert data["diagram_rendered"] is False and data["diagram_svg"] == ""


def test_reply_prompt_forbids_claiming_a_missing_diagram():
    assert "DIAGRAM HONESTY" in o.CONVERSATIONALIST_PROMPT
    assert "never say or imply that a diagram" in o.CONVERSATIONALIST_PROMPT
    assert 'data-diagram="none"' in o.VISUALIZER_PROMPT


def test_screen_svg_keeps_real_diagrams_and_rejects_placeholders():
    assert _screen_svg(GOOD_SVG) == (GOOD_SVG, "drawn")
    assert _screen_svg(PLACEHOLDER_SVG) == ("", "suppressed_placeholder")
    assert _screen_svg(NO_DIAGRAM_SVG) == ("", "suppressed_placeholder")
    assert _screen_svg("") == ("", "visualizer_failed")
    assert _screen_svg("I can't draw that.") == ("", "visualizer_failed")
    # A real label that happens to say "not specified" is not a placeholder.
    direction = GOOD_SVG.replace("W = 58.9 N", "direction not specified")
    assert _screen_svg(direction) == (direction, "drawn")


def test_no_diagram_marker_survives_the_real_visualizer_method():
    """The marker goes through visualizer()'s SVG extraction and label fixer."""
    agent = OrchestratorAgent()
    agent.client = DrawClient(visualizer_svg="```svg\n" + NO_DIAGRAM_SVG + "\n```")
    assert _screen_svg(agent.visualizer(UNCLEAR_PARSE, None))[1] == "suppressed_placeholder"


# --- 6. Problem statement older than the history window ------------------------

@BOTH
def test_problem_older_than_the_window_is_drawn_from_the_active_problem(mode):
    filler = []
    for i in range(MAX_HISTORY_MESSAGES):
        filler += [{"role": "user", "content": f"Is step {i} right?"},
                   {"role": "assistant", "content": f"Step {i} looks fine."}]
    long_history = HISTORY[:2] + filler
    client = DrawClient(scope="referential")
    _, svg, _ = _drive(mode, client, FOLLOW_UP, long_history, active_problem=PULLEY_PARSE)

    [parse_input] = client.parser_calls
    conversation_part = parse_input.split("TASK:", 1)[0]
    assert PULLEY not in conversation_part  # scrolled out of the window
    assert "ACTIVE PROBLEM" in parse_input and "6 kg block hanging" in parse_input
    assert svg == GOOD_SVG


@BOTH
def test_unusable_active_problem_is_ignored(mode):
    client = DrawClient(scope="referential")
    _drive(mode, client, FOLLOW_UP, HISTORY, active_problem={"givens": "x" * 30000})
    assert "ACTIVE PROBLEM" not in client.parser_calls[0]


# --- 7. Multi-problem draw still works ------------------------------------------

def test_draw_all_of_them_draws_each_created_problem():
    created = [
        {"role": "user", "content": "make me two practice problems"},
        {"role": "assistant", "content": (
            "Here are two practice problems:\n"
            "A 3 kg block slides down a 20 degree frictionless incline from rest.\n"
            "A 4 kg crate is pushed across a rough floor with a 30 N horizontal force.")},
    ]
    client = DrawClient(scope="referential")
    reply, svg, _ = _drive("run_stream", client, "draw all of them", created)
    assert svg.count("<svg") == 2
    assert len(client.visualizer_inputs) == 2
    assert reply.startswith("Here are the setups for each problem")


# --- 8. Trace fields are saved, and the export still runs -------------------------

@BOTH
def test_trace_records_problem_scope_and_diagram_status(mode):
    memory = RecordingMemory()
    _drive(mode, DrawClient(scope="self_contained"), FOLLOW_UP, HISTORY, memory=memory)
    data = memory.logged_turns[-1][2]
    assert data["problem_scope"] == "self_contained"
    assert data["diagram_status"] == "drawn"
    assert data["diagram_svg"] == GOOD_SVG


def test_trace_events_never_reach_the_browser():
    _, _, events = _drive("run_stream", DrawClient(), FOLLOW_UP, HISTORY)
    assert "trace" not in {e["type"] for e in events}


def test_export_runs_with_the_new_fields(tmp_path, monkeypatch):
    import csv
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(main.__file__).parent / "scripts"))
    import export_conversations as export

    monkeypatch.setenv("PILOT_PROFESSOR_CODES", "")
    monkeypatch.setenv("PILOT_PROFESSORS_FILE", str(tmp_path / "none.txt"))
    memory = SessionMemory(base_dir=str(tmp_path / "traces"), state_dir=str(tmp_path / "state"))
    _drive("run_stream", DrawClient(scope="referential", visualizer_svg=PLACEHOLDER_SVG),
           FOLLOW_UP, HISTORY, memory=memory)

    out = tmp_path / "exports"
    assert export.main(["--traces-dir", str(tmp_path / "traces"), "--state-dir",
                        str(tmp_path / "state"), "--out-dir", str(out)]) == 0
    [csv_path] = out.glob("*.csv")
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        assert next(csv.reader(fh)) == export.CSV_COLUMNS  # columns unchanged
    [json_path] = out.glob("*.json")
    [turn] = json.loads(json_path.read_text())["turns"]
    assert "diagram_status" not in turn and "problem_scope" not in turn
    page = (next(out.glob("transcripts_*")) / "P01.html").read_text()
    assert "(no diagram sent: the drawing was a placeholder, so it was withheld)" in page


# --- The API passes the active problem through ---------------------------------

def test_tutor_stream_endpoint_passes_active_problem(monkeypatch):
    seen = {}

    class Agent:
        def run_stream(self, *a, **kw):
            seen.update(kw)
            yield {"type": "done"}

    monkeypatch.setattr(main, "OrchestratorAgent", lambda: Agent())
    req = main.TutorRequest(message=FOLLOW_UP, conversation_history=HISTORY,
                            active_problem=PULLEY_PARSE)
    resp = main.tutor_stream_endpoint(req, code="P01")
    from test_stream_error_path import _consume
    _consume(resp)
    assert seen["active_problem"] == PULLEY_PARSE
