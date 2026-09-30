"""
Pilot item 5 — wire docs/misconceptions.md into the tutor.

Parsing is deterministic and tested against the REAL doc file (a change to
the doc that breaks the parser should fail these tests, not surface as a
silent detection gap). The wiring tests use a fake client to confirm
STUDENT_MODELER_PROMPT actually includes the parsed content and the
conversationalist actually receives remediation guidance when targeted —
no real API calls anywhere.
"""
import json

from agents import misconceptions as mc
from agents.orchestrator import OrchestratorAgent, STUDENT_MODELER_PROMPT
from conftest import FakeResponse, FakeTextBlock, FakeThinkingBlock


# --- Parser, against the real docs/misconceptions.md -----------------------

def test_parses_all_22_known_entries():
    assert len(mc.MISCONCEPTIONS) == 22
    for expected in ("FBD-01", "EQ-03", "RP-02", "DL-04", "CON-05"):
        assert expected in mc.MISCONCEPTIONS


def test_each_entry_has_description_and_address():
    for entry_id, entry in mc.MISCONCEPTIONS.items():
        assert entry["description"], entry_id
        assert entry["address"], entry_id
        assert entry["category"], entry_id


def test_remediation_for_known_id():
    text = mc.remediation_for("FBD-04")
    assert "cable" in text.lower()


def test_remediation_for_unknown_id_is_empty_string():
    assert mc.remediation_for("NOT-A-REAL-ID") == ""


def test_remediation_for_none_is_empty_string():
    assert mc.remediation_for(None) == ""


def test_known_misconceptions_block_is_grouped_by_category():
    block = mc.known_misconceptions_block()
    assert "FBD Construction (statics):" in block
    assert "Equilibrium Equations (statics):" in block
    assert "- FBD-01: Omitting reaction forces at supports" in block


# --- Parser robustness (never breaks the tutor on a bad/missing doc) -------

def test_malformed_text_parses_to_empty_dict_not_a_crash():
    assert mc._parse("not a misconceptions file at all, just prose") == {}


def test_empty_text_parses_to_empty_dict():
    assert mc._parse("") == {}


def test_missing_file_load_returns_empty_dict(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "_DOCS_PATH", str(tmp_path / "does_not_exist.md"))
    assert mc._load() == {}


def test_known_misconceptions_block_is_empty_string_when_nothing_parsed():
    # Directly exercise the "nothing parsed" path without touching the
    # module-level MISCONCEPTIONS other tests depend on staying real.
    saved = mc.MISCONCEPTIONS
    try:
        mc.MISCONCEPTIONS = {}
        assert mc.known_misconceptions_block() == ""
        assert mc.remediation_for("FBD-01") == ""
    finally:
        mc.MISCONCEPTIONS = saved


# --- Wiring into the prompt / pipeline --------------------------------------

def test_student_modeler_prompt_includes_the_statics_catalog():
    assert "FBD-01: Omitting reaction forces at supports" in STUDENT_MODELER_PROMPT
    assert "Distributed Loads (statics):" in STUDENT_MODELER_PROMPT
    # The original hand-written dynamics list is still there too — additive,
    # not a replacement.
    assert "mass_weight_confusion" in STUDENT_MODELER_PROMPT
    assert STUDENT_MODELER_PROMPT.strip().endswith("Return ONLY the JSON. No prose.")


class ConversationalistCapturingClient:
    """Only implements what conversationalist() needs; records the
    context_bundle it was sent."""
    def __init__(self):
        self.messages = self
        self.last_user_content = None

    def create(self, **kw):
        self.last_user_content = kw["messages"][0]["content"]
        return FakeResponse([FakeThinkingBlock(), FakeTextBlock("Here's a nudge.")])


def test_conversationalist_gets_remediation_when_target_misconception_set():
    agent = OrchestratorAgent()
    agent.client = ConversationalistCapturingClient()
    plan = {"decision": "ASK", "target_misconception": "FBD-03"}
    agent.conversationalist(
        student_message="I think the roller pushes sideways",
        parsed_input={}, student_model={}, plan=plan,
        solution=None, validation=None, visualization=None,
    )
    bundle = json.loads(agent.client.last_user_content.split("Context bundle:\n", 1)[1])
    assert "misconception_guidance" in bundle
    assert "roller" in bundle["misconception_guidance"].lower()


def test_conversationalist_omits_guidance_key_when_no_target():
    agent = OrchestratorAgent()
    agent.client = ConversationalistCapturingClient()
    plan = {"decision": "HINT"}  # no target_misconception at all
    agent.conversationalist(
        student_message="ok what's next",
        parsed_input={}, student_model={}, plan=plan,
        solution=None, validation=None, visualization=None,
    )
    bundle = json.loads(agent.client.last_user_content.split("Context bundle:\n", 1)[1])
    assert "misconception_guidance" not in bundle


def test_conversationalist_omits_guidance_key_for_unrecognized_target():
    agent = OrchestratorAgent()
    agent.client = ConversationalistCapturingClient()
    plan = {"decision": "ASK", "target_misconception": "something_not_in_either_catalog"}
    agent.conversationalist(
        student_message="hi",
        parsed_input={}, student_model={}, plan=plan,
        solution=None, validation=None, visualization=None,
    )
    bundle = json.loads(agent.client.last_user_content.split("Context bundle:\n", 1)[1])
    assert "misconception_guidance" not in bundle
