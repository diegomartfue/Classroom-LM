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
