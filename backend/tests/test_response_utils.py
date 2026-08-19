"""
TEST GROUP 1 — response extraction (the Sonnet-5 / ThinkingBlock fix).

Verifies response_utils.extract_text pulls only text blocks and is robust to
thinking blocks, in every content-block shape.
"""
from response_utils import extract_text
from conftest import FakeTextBlock, FakeThinkingBlock, FakeResponse


def test_text_block_only():
    resp = FakeResponse([FakeTextBlock("hello world")])
    assert extract_text(resp) == "hello world"


def test_thinking_then_text():
    # The original bug: content[0] is a ThinkingBlock (no .text). extract_text
    # must skip it and return the text block.
    resp = FakeResponse([FakeThinkingBlock(), FakeTextBlock('{"ok": true}')])
    assert extract_text(resp) == '{"ok": true}'


def test_multiple_text_blocks_are_concatenated():
    resp = FakeResponse([FakeTextBlock("foo"), FakeTextBlock("bar")])
    assert extract_text(resp) == "foobar"


def test_thinking_only_returns_empty_string():
    # No text block at all -> empty string, not a crash.
    resp = FakeResponse([FakeThinkingBlock()])
    assert extract_text(resp) == ""


def test_thinking_between_text_blocks():
    resp = FakeResponse([
        FakeTextBlock("a"),
        FakeThinkingBlock(),
        FakeTextBlock("b"),
    ])
    assert extract_text(resp) == "ab"
