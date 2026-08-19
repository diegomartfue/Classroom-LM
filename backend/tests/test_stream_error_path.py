"""
ADDITIONAL FINDING #2 — /tutor/stream error observability.

On an unexpected exception the frontend must get a SAFE, generic SSE error
(no stack trace, no raw exception detail), while the server logs the failure.
"""
import sys
import types
import asyncio
import logging

# Shim the heavy rag_pipeline (chromadb) so `import main` works in CI/offline.
# main only uses ingest_document/query_rag from it, which this test never calls.
if "rag_pipeline" not in sys.modules:
    _fake = types.ModuleType("rag_pipeline")
    _fake.ingest_document = lambda *a, **k: {}
    _fake.query_rag = lambda *a, **k: {}
    sys.modules["rag_pipeline"] = _fake

import main  # noqa: E402


def _consume(resp):
    async def _run():
        out = []
        async for chunk in resp.body_iterator:
            out.append(chunk if isinstance(chunk, str) else chunk.decode())
        return out
    return asyncio.run(_run())


def test_stream_error_is_generic_and_logged(monkeypatch, caplog):
    class FailingAgent:
        def run_stream(self, message, conversation_history, student_model, source_text):
            raise RuntimeError("SECRET internal detail: content[0].text boom")
            yield {}  # unreachable; marks this function a generator

    monkeypatch.setattr(main, "OrchestratorAgent", lambda: FailingAgent())

    req = main.TutorRequest(message="hi", conversation_history=[],
                            student_model={}, doc_ids=[])
    resp = main.tutor_stream_endpoint(req)

    with caplog.at_level(logging.ERROR):
        body = "".join(_consume(resp))

    # Frontend receives an SSE error frame with a safe, generic message + ref id.
    assert '"type": "error"' in body
    assert "unexpected error" in body
    assert "ref " in body
    # The raw exception / stack trace is NOT leaked to the client.
    assert "SECRET internal detail" not in body
    assert "Traceback" not in body
    # The server logged the failure for diagnosis.
    assert any("tutor/stream failed" in r.message for r in caplog.records)
