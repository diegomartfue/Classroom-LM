"""
Bug 2 — student_modeler JSON truncated mid-string ("Unterminated string
starting at: line 18 column 24"). A parse failure must never wipe the
student's real mastery/struggle data by overwriting it with the failed
{"parse_error": ...} dict; _student_modeler_safe() falls back to the caller's
previous value instead.
"""
import logging

from agents.orchestrator import OrchestratorAgent
from conftest import FakeResponse, FakeTextBlock, FakeThinkingBlock


class FakeModelerClient:
    """Fake Anthropic client whose messages.create() always returns one
    canned response, enough to drive student_modeler() in isolation."""
    def __init__(self, text, stop_reason="end_turn"):
        self.messages = self
        self._response = FakeResponse([FakeThinkingBlock(), FakeTextBlock(text)], stop_reason)
        self.create_kwargs = None

    def create(self, **kw):
        self.create_kwargs = kw
        return self._response


REAL_MODEL = {
    "concept_mastery": {"fbd_construction": 0.6},
    "observed_misconceptions": [],
    "strengths": ["clean FBDs"],
    "current_state": "progressing",
    "confidence_level": "medium",
    "recommended_focus": "constraint relations",
}

PREVIOUS_MODEL = {
    "concept_mastery": {"fbd_construction": 0.4},
    "observed_misconceptions": [{"id": "mass_weight_confusion", "evidence": "x", "turn_observed": 1}],
    "strengths": [],
    "current_state": "stuck_on_fbd",
    "confidence_level": "low",
    "recommended_focus": "fbd basics",
}

TRUNCATED_JSON = (
    '{\n  "concept_mastery": {\n    "fbd_construction": 0.6,\n'
    '    "force_identification": "the student correctly identifie'
    # cut off mid-string, exactly like the real bug's "Unterminated string"
)


def _agent(text, stop_reason="end_turn"):
    agent = OrchestratorAgent()
    agent.client = FakeModelerClient(text, stop_reason)
    return agent


def test_successful_response_passes_through_unchanged():
    import json
    agent = _agent(json.dumps(REAL_MODEL))
    result = agent._student_modeler_safe(
        {"body": "x"}, PREVIOUS_MODEL, [], fallback=PREVIOUS_MODEL
    )
    assert result == REAL_MODEL


def test_truncated_json_falls_back_to_previous_model_unchanged():
    agent = _agent(TRUNCATED_JSON)
    result = agent._student_modeler_safe(
        {"body": "x"}, PREVIOUS_MODEL, [], fallback=PREVIOUS_MODEL
    )
    # Must be the untouched previous model — not the parse_error dict, and
    # not an empty/reset model.
    assert result == PREVIOUS_MODEL
    assert "parse_error" not in result
    assert result["concept_mastery"]["fbd_construction"] == 0.4  # not wiped to 0/empty


def test_truncated_json_uses_the_given_fallback_not_the_previous_model():
    # The "identifier" call site passes fallback={} (misconceptions is not a
    # student_model-shaped object) — confirm _student_modeler_safe respects
    # whatever fallback the caller supplies, not always the student_model arg.
    agent = _agent(TRUNCATED_JSON)
    result = agent._student_modeler_safe(
        {"body": "x"}, PREVIOUS_MODEL, [], fallback={}
    )
    assert result == {}


def test_fallback_failure_is_logged(caplog):
    agent = _agent(TRUNCATED_JSON)
    with caplog.at_level(logging.WARNING):
        agent._student_modeler_safe({"body": "x"}, PREVIOUS_MODEL, [], fallback=PREVIOUS_MODEL)
    assert any("parse_error" in r.message for r in caplog.records)


def test_student_modeler_sets_adaptive_thinking_and_low_effort():
    # Regression guard for the actual root cause: claude-sonnet-5 runs
    # adaptive thinking by default when `thinking` is omitted, and those
    # tokens count against max_tokens — this is what was eating the budget
    # and truncating the JSON mid-string in the real bug.
    import json
    agent = _agent(json.dumps(REAL_MODEL))
    agent.student_modeler({"body": "x"}, PREVIOUS_MODEL, [])
    kwargs = agent.client.create_kwargs
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"] == {"effort": "low"}
