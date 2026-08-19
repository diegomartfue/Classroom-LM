"""
Shared test fixtures/fakes for the backend regression suite.

These tests never hit the Anthropic API. They import backend modules directly
and substitute fake response/stream objects for the Claude client.
"""
import os
import sys
import pathlib

# Make the backend package importable regardless of pytest's rootdir.
BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# OrchestratorAgent.__init__ raises without a key; a dummy value is fine because
# the real client is always replaced with a fake in these tests.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")


class FakeTextBlock:
    """Stands in for an Anthropic TextBlock."""
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class FakeThinkingBlock:
    """Stands in for a ThinkingBlock. Deliberately has NO `.text` attribute, so
    any code that does `block.text` on it would raise — proving extract_text
    must filter by type."""
    def __init__(self, thinking: str = "...internal reasoning..."):
        self.type = "thinking"
        self.thinking = thinking


class FakeResponse:
    """Stands in for a Messages API response object."""
    def __init__(self, blocks):
        self.content = list(blocks)


class FakeStreamCtx:
    """Context manager returned by a fake `client.messages.stream(...)`."""
    def __init__(self, chunks):
        self.text_stream = iter(chunks)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
