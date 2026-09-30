"""
ADDITIONAL FINDING #1 — _parse_json failure boundary.

Malformed/empty/non-JSON responses must degrade to a {"parse_error": ...} dict
(with raw_response for debugging), not raise. This is a distinct failure class
from the ThinkingBlock/text-extraction issue.
"""
from agents import orchestrator as o


def test_valid_json():
    assert o._parse_json('{"a": 1, "b": [2, 3]}') == {"a": 1, "b": [2, 3]}


def test_fenced_json():
    text = '```json\n{"route": "CREATE"}\n```'
    assert o._parse_json(text) == {"route": "CREATE"}


def test_malformed_json_yields_parse_error_with_raw():
    raw = "not json at all { oops"
    out = o._parse_json(raw)
    assert "parse_error" in out
    assert out["raw_response"] == raw


def test_empty_text_yields_parse_error_not_crash():
    # e.g. a response whose only block was a thinking block -> extract_text "" .
    out = o._parse_json("")
    assert "parse_error" in out


def test_parse_error_is_logged(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        o._parse_json("{bad json")
    assert any("unparseable JSON" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Bug 3 — the input parser returned fenced JSON with extra content after it
# ("Extra data: line 58 column 1 (char 2518)"). _parse_json now strips code
# fences and extracts the first complete, brace-balanced JSON object,
# ignoring anything before or after it, instead of handing the whole string
# straight to json.loads.
# ---------------------------------------------------------------------------

def test_fenced_json_with_trailing_prose_after_the_closing_fence():
    # Reproduces the exact failure mode from the log: a fenced JSON object
    # followed by more content the old fence-only stripping didn't drop,
    # which made json.loads choke with "Extra data".
    text = (
        '```json\n'
        '{\n  "problem_type": "kinematics",\n  "body": "ladder"\n}\n'
        '```\n'
        'Let me know if you would like any adjustments to this parse.'
    )
    assert o._parse_json(text) == {"problem_type": "kinematics", "body": "ladder"}


def test_prose_before_unfenced_json():
    text = 'Here is the parsed problem:\n{"route": "DRAW", "confidence": 0.9}'
    assert o._parse_json(text) == {"route": "DRAW", "confidence": 0.9}


def test_prose_before_fenced_json():
    text = (
        "Sure, here's the structured output:\n\n"
        '```json\n{"a": 1}\n```'
    )
    assert o._parse_json(text) == {"a": 1}


def test_fenced_json_with_second_fenced_block_after_it():
    # A second code block after the real JSON (e.g. the model "showing its
    # work" in a follow-up fence) must not leak into the result either.
    text = (
        '```json\n{"a": 1}\n```\n\n'
        'For reference, here is the equivalent YAML:\n```yaml\na: 1\n```'
    )
    assert o._parse_json(text) == {"a": 1}


def test_truncated_json_with_no_closing_brace_fails_cleanly():
    # Reproduces the other exact failure mode: "Unterminated string starting
    # at: line 18 column 24" — the response was cut off mid-object, so there
    # is no balanced closing brace anywhere in the text.
    text = '{\n  "concept_mastery": {\n    "fbd_construction": 0.6,\n    "force_id'
    out = o._parse_json(text)
    assert "parse_error" in out
    assert out["raw_response"] == text


def test_truncated_fenced_json_fails_cleanly_not_extra_data():
    text = '```json\n{"a": 1, "b": [2, 3'
    out = o._parse_json(text)
    assert "parse_error" in out


def test_brace_inside_a_json_string_value_does_not_break_balance_tracking():
    # A literal "{" or "}" inside a string value must not be mistaken for
    # object nesting.
    text = '{"note": "use braces like { and } in your answer", "ok": true}'
    assert o._parse_json(text) == {
        "note": "use braces like { and } in your answer", "ok": True,
    }


def test_escaped_quote_inside_string_does_not_end_string_early():
    text = r'{"note": "the \"solved\" value", "ok": true}'
    assert o._parse_json(text) == {"note": 'the "solved" value', "ok": True}
