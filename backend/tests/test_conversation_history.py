"""
TEST GROUP 3 — conversation-history formatting.

Covers the centralized _format_history (bounded) and _conversation_block
(labeled, separated from the current message).
"""
from agents import orchestrator as o


def test_empty_history():
    assert o._format_history([]) == "(no prior conversation)"
    assert o._conversation_block([]) == ""  # no header when nothing to show


def test_single_turn():
    hist = [{"role": "user", "content": "My name is Diego."}]
    out = o._format_history(hist)
    assert "User: My name is Diego." in out


def test_multiple_turns_preserve_order_and_roles():
    hist = [
        {"role": "user", "content": "My name is Diego."},
        {"role": "assistant", "content": "Nice to meet you."},
    ]
    out = o._format_history(hist)
    assert out == "User: My name is Diego.\nAssistant: Nice to meet you."


def test_truncation_keeps_only_most_recent():
    hist = [{"role": "user", "content": f"msg{i}"} for i in range(o.MAX_HISTORY_MESSAGES + 5)]
    out = o._format_history(hist)
    # Oldest are dropped; only the last MAX_HISTORY_MESSAGES remain.
    assert "msg0" not in out
    assert f"msg{o.MAX_HISTORY_MESSAGES + 4}" in out
    assert out.count("\n") == o.MAX_HISTORY_MESSAGES - 1


def test_conversation_block_is_labeled_and_separated():
    hist = [{"role": "user", "content": "My name is Diego."}]
    block = o._conversation_block(hist)
    assert block.startswith("Previous conversation:\n")
    assert block.endswith("\n\n")  # blank line separates it from the current message
    assert "My name is Diego." in block


def test_conversation_block_does_not_include_a_current_message_marker():
    # The block is prior turns ONLY; the caller adds the current message
    # separately, so it must never duplicate it or invent a current-message line.
    hist = [{"role": "user", "content": "prior turn"}]
    block = o._conversation_block(hist)
    assert "Current student message" not in block
