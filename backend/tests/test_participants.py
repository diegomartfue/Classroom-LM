"""
Participant codes: the allowlist, the global gate on every API route, and
configurable CORS. Goes through FastAPI's TestClient so the real dependency
and middleware stack runs. No Anthropic client is ever constructed: the
gated routes used here either fail at the gate or never reach an agent.
"""
import sys
import types

import pytest

if "rag_pipeline" not in sys.modules:
    _fake = types.ModuleType("rag_pipeline")
    _fake.ingest_document = lambda *a, **k: {}
    _fake.query_rag = lambda *a, **k: {}
    sys.modules["rag_pipeline"] = _fake

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import participants  # noqa: E402


@pytest.fixture(autouse=True)
def allowlist(monkeypatch, tmp_path):
    monkeypatch.setenv("PILOT_PARTICIPANT_CODES", "P07, p08")
    f = tmp_path / "participants.txt"
    f.write_text("# pilot cohort\nP09\n  p10  # late joiner\n\nnot a code!\n")
    monkeypatch.setenv("PILOT_PARTICIPANTS_FILE", str(f))
    return f


@pytest.fixture
def client():
    return TestClient(main.app)


# --- Allowlist ----------------------------------------------------------------

def test_codes_from_env_and_file_are_normalized():
    assert participants.allowed_codes() == {"P07", "P08", "P09", "P10"}


@pytest.mark.parametrize("raw, expected", [
    ("P07", "P07"), (" p07 ", "P07"), ("P99", None), ("", None), (None, None),
    ("../etc", None), ("P07; DROP", None), ("x" * 40, None),
])
def test_verify(raw, expected):
    assert participants.verify(raw) == expected


def test_empty_allowlist_rejects_everyone(monkeypatch, tmp_path):
    monkeypatch.setenv("PILOT_PARTICIPANT_CODES", "")
    monkeypatch.setenv("PILOT_PARTICIPANTS_FILE", str(tmp_path / "missing.txt"))
    assert participants.verify("P07") is None


def test_file_edits_apply_without_restart(allowlist):
    assert participants.verify("P11") is None
    allowlist.write_text("P11\n")
    assert participants.verify("P11") == "P11"


# --- Gate ---------------------------------------------------------------------

def test_public_paths_need_no_code(client):
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200


def test_verify_endpoint(client):
    ok = client.post("/participant/verify", json={"code": " p09 "})
    assert ok.status_code == 200 and ok.json() == {"code": "P09", "role": "participant"}
    assert client.post("/participant/verify", json={"code": "P99"}).status_code == 401


@pytest.mark.parametrize("method, path, body", [
    ("post", "/tutor/stream", {"message": "hi"}),
    ("post", "/tutor", {"message": "hi"}),
    ("post", "/check-work", {"lines": ["m = 1"], "parsed_input": {"givens": [1]}}),
    ("post", "/feedback", {"session_id": "s", "turn_number": 0, "rating": "up"}),
    ("post", "/chat", {"message": "hi"}),
    ("post", "/query", {"question": "hi"}),
    ("get", "/documents", None),
    ("post", "/documents/summarize", {"doc_id": "x"}),
])
@pytest.mark.parametrize("headers", [{}, {"X-Participant-Code": "P99"},
                                     {"X-Participant-Code": ""}])
def test_every_api_route_rejects_missing_or_unknown_code(client, method, path, body, headers):
    kwargs = {"headers": headers}
    if body is not None:
        kwargs["json"] = body
    resp = getattr(client, method)(path, **kwargs)
    assert resp.status_code == 401


def test_valid_code_reaches_the_route_and_is_what_gets_saved(client, monkeypatch):
    saved = []
    monkeypatch.setattr(main, "record_feedback",
                        lambda **kw: saved.append(kw) or kw)
    resp = client.post("/feedback",
                       headers={"X-Participant-Code": "p07"},
                       json={"session_id": "s1", "turn_number": 2, "rating": "up",
                             # A client-sent id is ignored by the model.
                             "student_id": "Jane Doe"})
    assert resp.status_code == 200
    assert saved[0]["student_id"] == "P07"
    assert "Jane Doe" not in str(saved)


def test_tutor_stream_saves_under_code_not_client_student_id(client, monkeypatch):
    seen = {}

    class FakeAgent:
        def run_stream(self, message, history, model, source_text, **kw):
            seen.update(kw)
            yield {"type": "done"}

    monkeypatch.setattr(main, "OrchestratorAgent", FakeAgent)
    resp = client.post("/tutor/stream", headers={"X-Participant-Code": "P08"},
                       json={"message": "hi", "student_id": "jane@school.edu"})
    assert resp.status_code == 200
    assert seen["student_id"] == "P08"


def test_401_still_carries_cors_headers(client):
    # Otherwise the browser reports a CORS failure instead of "bad code",
    # and the frontend can't send the student back to the code screen.
    resp = client.post("/tutor/stream", json={"message": "hi"},
                       headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 401
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_preflight_needs_no_code(client):
    resp = client.options("/tutor/stream", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-participant-code",
    })
    assert resp.status_code == 200


# --- CORS origins ---------------------------------------------------------------

def test_cors_default_is_local_dev(monkeypatch):
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    assert "http://localhost:5173" in main._cors_origins()


def test_cors_origins_from_env(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS",
                       " https://tutor.school.edu/ , http://localhost:5173,, ")
    assert main._cors_origins() == ["https://tutor.school.edu", "http://localhost:5173"]
