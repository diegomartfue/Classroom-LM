"""
/tutor/stream: proxy-buffering headers, and the dev-only mock stream
(MOCK_TUTOR_STREAM) that lets the frontend smoothing be tested with no API.
"""
import sys
import types
import asyncio
import json
import random

# Shim the heavy rag_pipeline (chromadb) so `import main` works in CI/offline.
if "rag_pipeline" not in sys.modules:
    _fake = types.ModuleType("rag_pipeline")
    _fake.ingest_document = lambda *a, **k: {}
    _fake.query_rag = lambda *a, **k: {}
    sys.modules["rag_pipeline"] = _fake

import main  # noqa: E402
import mock_stream  # noqa: E402


def _events(resp):
    async def _run():
        out = []
        async for chunk in resp.body_iterator:
            out.append(chunk if isinstance(chunk, str) else chunk.decode())
        return out
    body = "".join(asyncio.run(_run()))
    return [json.loads(f[len("data: "):]) for f in body.split("\n\n") if f.startswith("data: ")]


def _request():
    return main.TutorRequest(message="hi", conversation_history=[],
                             student_model={"level": 1}, doc_ids=[])


class _FakeAgent:
    def run_stream(self, *a, **k):
        yield {"type": "token", "text": "real"}
        yield {"type": "done"}


def test_stream_sends_no_buffering_headers(monkeypatch):
    monkeypatch.delenv("MOCK_TUTOR_STREAM", raising=False)
    monkeypatch.setattr(main, "OrchestratorAgent", _FakeAgent)
    resp = main.tutor_stream_endpoint(_request(), code="P01")
    assert resp.headers["x-accel-buffering"] == "no"
    assert "no-cache" in resp.headers["cache-control"]
    assert "no-transform" in resp.headers["cache-control"]
    assert resp.media_type == "text/event-stream"


def test_mock_is_off_by_default(monkeypatch):
    monkeypatch.delenv("MOCK_TUTOR_STREAM", raising=False)
    monkeypatch.setattr(main, "OrchestratorAgent", _FakeAgent)
    events = _events(main.tutor_stream_endpoint(_request(), code="P01"))
    assert [e.get("text") for e in events if e["type"] == "token"] == ["real"]


def test_mock_stream_never_builds_the_agent(monkeypatch):
    monkeypatch.setenv("MOCK_TUTOR_STREAM", "1")
    monkeypatch.setattr(mock_stream.time, "sleep", lambda s: None)

    def _no_agent():
        raise AssertionError("mock mode must not build the orchestrator")
    monkeypatch.setattr(main, "OrchestratorAgent", _no_agent)

    resp = main.tutor_stream_endpoint(_request(), code="P01")
    assert resp.headers["x-accel-buffering"] == "no"
    events = _events(resp)
    assert events[-1] == {"type": "done"}
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["student_model"] == {"level": 1}
    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert text == mock_stream.MOCK_REPLY


def test_mock_reply_has_inline_and_display_math():
    assert "$$" in mock_stream.MOCK_REPLY
    assert mock_stream.MOCK_REPLY.replace("$$", "").count("$") >= 2


def test_mock_bursts_are_irregular():
    sleeps = []
    events = list(mock_stream.mock_events({}, rng=random.Random(7), sleep=sleeps.append))
    tokens = [e for e in events if e["type"] == "token"]
    assert len(tokens) > 50
    gaps = sleeps[2:]  # after the two status pauses
    assert len(gaps) < len(tokens)       # tokens arrive in clumps, not one by one
    assert max(gaps) >= 0.4 and min(gaps) <= 0.15   # occasional stalls, mostly short gaps
