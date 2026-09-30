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
    def __init__(self, blocks, stop_reason: str = "end_turn"):
        self.content = list(blocks)
        self.stop_reason = stop_reason


class FakeStreamCtx:
    """Context manager returned by a fake `client.messages.stream(...)`."""
    def __init__(self, chunks):
        self.text_stream = iter(chunks)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# ---------------------------------------------------------------------------
# Keep test runs out of the real research data. SessionMemory, the feedback
# and check-work logs, uploads, and the usage tracker all default to
# backend/traces/, backend/state/ and backend/uploads/ — which on the pilot server is exactly what
# scripts/export_conversations.py exports. Their default paths are bound as
# function defaults at import time, so rebind the defaults to a per-run temp
# dir before any test constructs one.
# ---------------------------------------------------------------------------
import pytest  # noqa: E402


@pytest.fixture(autouse=True, scope="session")
def _isolate_research_data(tmp_path_factory):
    from agents.memory import SessionMemory
    import check_work_store
    import feedback_store
    from utils.usage_tracker import DailyUsageTracker

    root = tmp_path_factory.mktemp("research_data")
    patched = [
        (SessionMemory.__init__, (str(root / "traces"), str(root / "state"))),
        (feedback_store.record_feedback, (str(root / "state" / "feedback.jsonl"),)),
        (feedback_store.read_feedback, (str(root / "state" / "feedback.jsonl"),)),
        (check_work_store.record_check_work, (str(root / "state" / "check_work.jsonl"),)),
        (check_work_store.read_check_work, (str(root / "state" / "check_work.jsonl"),)),
    ]
    originals = [(fn, fn.__defaults__) for fn, _ in patched]
    for fn, new_tail in patched:
        fn.__defaults__ = fn.__defaults__[:-len(new_tail)] + new_tail
    import document_store
    original_upload_root = document_store.UPLOAD_ROOT
    document_store.UPLOAD_ROOT = str(root / "uploads")
    usage_defaults = DailyUsageTracker.__init__.__defaults__
    DailyUsageTracker.__init__.__defaults__ = (str(root / "state" / "usage"),) + usage_defaults[1:]
    yield root
    for fn, defaults in originals:
        fn.__defaults__ = defaults
    DailyUsageTracker.__init__.__defaults__ = usage_defaults
    document_store.UPLOAD_ROOT = original_upload_root
