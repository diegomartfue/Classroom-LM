"""
Pilot item 6 — /feedback endpoint. Calls the FastAPI endpoint function
directly (same pattern as test_stream_error_path.py), no server needed and
no real API calls.
"""
import functools
import sys
import types

import pytest

# Shim the heavy rag_pipeline (chromadb) so `import main` works offline —
# same shim as test_stream_error_path.py.
if "rag_pipeline" not in sys.modules:
    _fake = types.ModuleType("rag_pipeline")
    _fake.ingest_document = lambda *a, **k: {}
    _fake.query_rag = lambda *a, **k: {}
    sys.modules["rag_pipeline"] = _fake

import main  # noqa: E402
import feedback_store  # noqa: E402
from fastapi import HTTPException


def _patch_record_feedback_path(monkeypatch, tmp_path):
    # record_feedback's `path` parameter defaults to feedback_store's module-
    # level _DEFAULT_PATH, which is bound at function-definition time — so
    # patching _DEFAULT_PATH after import has no effect on later calls.
    # Bind a fixed test path via partial instead, on the SAME name main.py
    # imported (`main.record_feedback`), so the test never touches the real
    # backend/state/feedback.jsonl.
    monkeypatch.setattr(
        main, "record_feedback",
        functools.partial(feedback_store.record_feedback, path=str(tmp_path / "feedback.jsonl")),
    )


def test_feedback_endpoint_records_a_rating(tmp_path, monkeypatch):
    _patch_record_feedback_path(monkeypatch, tmp_path)

    req = main.FeedbackRequest(session_id="s1", turn_number=2, rating="up")
    result = main.feedback_endpoint(req, code="P07")
    assert result["status"] == "ok"
    assert result["entry"]["rating"] == "up"
    assert result["entry"]["session_id"] == "s1"
    # Stored under the verified participant code, never a client-sent id.
    assert result["entry"]["student_id"] == "P07"

    on_disk = feedback_store.read_feedback(path=str(tmp_path / "feedback.jsonl"))
    assert len(on_disk) == 1


def test_feedback_endpoint_rejects_bad_rating_as_400(tmp_path, monkeypatch):
    _patch_record_feedback_path(monkeypatch, tmp_path)

    req = main.FeedbackRequest(session_id="s1", turn_number=2, rating="sideways")
    with pytest.raises(HTTPException) as exc_info:
        main.feedback_endpoint(req, code="P07")
    assert exc_info.value.status_code == 400
    # Nothing written on a rejected rating.
    assert feedback_store.read_feedback(path=str(tmp_path / "feedback.jsonl")) == []
