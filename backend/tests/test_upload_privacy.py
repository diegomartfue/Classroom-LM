"""
Upload privacy, end to end through FastAPI's TestClient and the real
document_store (in a temp folder, via conftest). Participant A's uploads are
invisible and unusable to participant B; professor uploads are shared with
both. The tutor, summarize and quiz are faked at their model-call boundary
so we can see exactly which document text they were given. No API calls:
uploads are .txt files, which never go to a vision model.
"""
import json
import sys
import types
from pathlib import Path

import pytest

if "rag_pipeline" not in sys.modules:
    _fake = types.ModuleType("rag_pipeline")
    _fake.ingest_document = lambda *a, **k: {}
    _fake.query_rag = lambda *a, **k: {}
    sys.modules["rag_pipeline"] = _fake

from fastapi.testclient import TestClient  # noqa: E402

import document_features  # noqa: E402
import document_store  # noqa: E402
import main  # noqa: E402
from conftest import FakeResponse, FakeTextBlock  # noqa: E402

A, B, PROF = "P01", "P02", "PROF-7Q"
A_TEXT = "Participant A's private homework. " * 10
B_TEXT = "Participant B's private notes. " * 10
PROF_TEXT = "Shared lecture notes on friction and inclines. " * 10


@pytest.fixture(autouse=True)
def codes(monkeypatch, tmp_path):
    monkeypatch.setenv("PILOT_PARTICIPANT_CODES", f"{A},{B}")
    monkeypatch.setenv("PILOT_PARTICIPANTS_FILE", str(tmp_path / "none.txt"))
    monkeypatch.setenv("PILOT_PROFESSOR_CODES", PROF)
    monkeypatch.setenv("PILOT_PROFESSORS_FILE", str(tmp_path / "none.txt"))
    monkeypatch.setattr(document_store, "UPLOAD_ROOT", str(tmp_path / "uploads"))


@pytest.fixture
def client():
    return TestClient(main.app)


def h(code):
    return {"X-Participant-Code": code}


def upload(client, code, name, text):
    resp = client.post("/documents", headers=h(code),
                       files={"file": (name, text.encode(), "text/plain")})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def docs(client):
    return {
        "prof": upload(client, PROF, "Week3_Friction.txt", PROF_TEXT),
        "a": upload(client, A, "JaneSmith_HW3.txt", A_TEXT),
        "b": upload(client, B, "b_notes.txt", B_TEXT),
    }


def ids(client, code):
    resp = client.get("/documents", headers=h(code))
    assert resp.status_code == 200
    return {d["doc_id"]: d for d in resp.json()["documents"]}


# --- Listing and reading ------------------------------------------------------

def test_each_participant_lists_shared_plus_only_their_own(client, docs):
    a_list, b_list = ids(client, A), ids(client, B)
    assert set(a_list) == {docs["prof"]["doc_id"], docs["a"]["doc_id"]}
    assert set(b_list) == {docs["prof"]["doc_id"], docs["b"]["doc_id"]}
    # Owner sees their own original name; shared material shows its name.
    assert a_list[docs["a"]["doc_id"]]["filename"] == "JaneSmith_HW3.txt"
    assert a_list[docs["a"]["doc_id"]]["scope"] == "private"
    assert b_list[docs["prof"]["doc_id"]]["scope"] == "shared"
    assert "JaneSmith" not in json.dumps(b_list)
    # The owner field never leaves the server.
    assert all("owner" not in d for d in list(a_list.values()) + list(b_list.values()))


def test_professor_sees_shared_but_not_participants_private_files(client, docs):
    assert set(ids(client, PROF)) == {docs["prof"]["doc_id"]}


def test_b_cannot_read_a_file_and_it_looks_nonexistent(client, docs):
    a_id = docs["a"]["doc_id"]
    theirs = client.get(f"/documents/{a_id}", headers=h(B))
    missing = client.get("/documents/0123456789ab", headers=h(B))
    assert theirs.status_code == missing.status_code == 404
    assert A_TEXT not in theirs.text and "JaneSmith" not in theirs.text
    assert client.get(f"/documents/{a_id}", headers=h(A)).json()["text"] == A_TEXT


def test_both_can_read_professor_material(client, docs):
    for code in (A, B):
        resp = client.get(f"/documents/{docs['prof']['doc_id']}", headers=h(code))
        assert resp.status_code == 200 and resp.json()["text"] == PROF_TEXT


@pytest.mark.parametrize("bad_id", ["..%2F..%2Fdocuments", "ABCDEF123456", "x" * 12])
def test_malformed_ids_are_not_found(client, docs, bad_id):
    assert client.get(f"/documents/{bad_id}", headers=h(A)).status_code == 404


@pytest.mark.parametrize("bad_id", ["..", "../P02/index", "../../shared", "", None])
def test_path_like_ids_never_reach_the_filesystem(docs, bad_id):
    # Called directly: an HTTP client would normalize ".." out of the URL.
    import participants
    with pytest.raises(document_store.DocumentError):
        document_store.get_document(bad_id, participants.Identity(A, "participant"))


# --- Deleting -------------------------------------------------------------------

def test_b_cannot_delete_a_file(client, docs):
    a_id = docs["a"]["doc_id"]
    assert client.delete(f"/documents/{a_id}", headers=h(B)).status_code == 404
    assert a_id in ids(client, A)


def test_participants_cannot_delete_shared_material_but_professor_can(client, docs):
    prof_id = docs["prof"]["doc_id"]
    assert client.delete(f"/documents/{prof_id}", headers=h(A)).status_code == 403
    assert prof_id in ids(client, B)
    assert client.delete(f"/documents/{prof_id}", headers=h(PROF)).status_code == 200
    assert prof_id not in ids(client, A)


def test_owner_can_delete_own_file(client, docs):
    a_id = docs["a"]["doc_id"]
    assert client.delete(f"/documents/{a_id}", headers=h(A)).status_code == 200
    assert a_id not in ids(client, A)


# --- Storage layout ---------------------------------------------------------------

def test_files_are_stored_under_each_owner(docs):
    root = Path(document_store.UPLOAD_ROOT)
    assert (root / "shared" / f"{docs['prof']['doc_id']}.txt").exists()
    assert (root / "participants" / A / f"{docs['a']['doc_id']}.txt").exists()
    assert (root / "participants" / B / f"{docs['b']['doc_id']}.txt").exists()
    assert not (root / "participants" / B / f"{docs['a']['doc_id']}.txt").exists()
    # Nothing stored under the original (identifying) name, nothing loose.
    assert not list(root.rglob("*JaneSmith*"))
    assert not [p for p in root.iterdir() if p.is_file()]


# --- The tutor using documents ------------------------------------------------------

@pytest.fixture
def tutor_sources(monkeypatch):
    seen = []

    class FakeAgent:
        def run_stream(self, message, history, model, source_text, **kw):
            seen.append(source_text)
            yield {"type": "done"}

    monkeypatch.setattr(main, "OrchestratorAgent", FakeAgent)
    return seen


def test_tutor_never_uses_another_participants_file(client, docs, tutor_sources):
    resp = client.post("/tutor/stream", headers=h(B), json={
        "message": "use these", "doc_ids": [docs["a"]["doc_id"], docs["prof"]["doc_id"]]})
    assert resp.status_code == 200
    [source] = tutor_sources
    assert A_TEXT.strip() not in source and "JaneSmith" not in source
    assert PROF_TEXT.strip() in source  # B still gets the shared material


def test_tutor_uses_own_file_without_its_name_and_shared_with_its_name(client, docs, tutor_sources):
    client.post("/tutor/stream", headers=h(A), json={
        "message": "use these", "doc_ids": [docs["a"]["doc_id"], docs["prof"]["doc_id"]]})
    [source] = tutor_sources
    assert A_TEXT.strip() in source and PROF_TEXT.strip() in source
    assert "JaneSmith" not in source
    assert "Your uploaded document 1" in source
    assert "Course material: Week3_Friction.txt" in source


def test_both_participants_tutor_can_use_professor_material(client, docs, tutor_sources):
    for code in (A, B):
        client.post("/tutor/stream", headers=h(code),
                    json={"message": "use it", "doc_ids": [docs["prof"]["doc_id"]]})
    assert all(PROF_TEXT.strip() in s for s in tutor_sources) and len(tutor_sources) == 2


# --- Summarize / quiz ------------------------------------------------------------------

class _CapturingClient:
    def __init__(self, reply):
        self.prompts, self.messages, self.reply = [], self, reply

    def create(self, **kw):
        self.prompts.append(kw["messages"][0]["content"])
        resp = FakeResponse([FakeTextBlock(self.reply)])
        resp.usage = types.SimpleNamespace(input_tokens=1, output_tokens=1)
        return resp


@pytest.fixture
def model(monkeypatch):
    fake = _CapturingClient("summary")
    monkeypatch.setattr(document_features, "_client", lambda: fake)
    return fake


@pytest.mark.parametrize("path, body", [
    ("/documents/summarize", {}),
    ("/documents/quiz", {"num_questions": 3}),
])
def test_b_cannot_summarize_or_quiz_a_file(client, docs, model, path, body):
    resp = client.post(path, headers=h(B), json={"doc_ids": [docs["a"]["doc_id"]], **body})
    assert resp.status_code == 404
    assert model.prompts == []  # never reached the model


def test_summarize_own_and_shared(client, docs, model):
    for code, doc in ((A, "a"), (A, "prof"), (B, "prof")):
        resp = client.post("/documents/summarize", headers=h(code),
                           json={"doc_ids": [docs[doc]["doc_id"]]})
        assert resp.status_code == 200
    assert A_TEXT.strip() in model.prompts[0] and "JaneSmith" not in model.prompts[0]
    assert PROF_TEXT.strip() in model.prompts[1] and PROF_TEXT.strip() in model.prompts[2]


# --- Professor role and legacy upload ----------------------------------------------------

def test_verify_reports_role(client):
    assert client.post("/participant/verify", json={"code": PROF}).json()["role"] == "professor"
    assert client.post("/participant/verify", json={"code": A}).json()["role"] == "participant"


def test_code_on_both_lists_is_only_a_participant(monkeypatch, client):
    monkeypatch.setenv("PILOT_PROFESSOR_CODES", f"{PROF},{A}")
    assert client.post("/participant/verify", json={"code": A}).json()["role"] == "participant"
    upload(client, A, "mine.txt", A_TEXT)
    assert all(d["scope"] == "private" for d in ids(client, A).values())


def test_legacy_rag_upload_is_professor_only(client, monkeypatch):
    ingested = []
    monkeypatch.setattr(main, "ingest_document", lambda path: ingested.append(path) or {"ok": True})
    files = {"file": ("../../evil.pdf", b"%PDF-1.4", "application/pdf")}
    assert client.post("/upload", headers=h(A), files=files).status_code == 403
    assert ingested == []
    assert client.post("/upload", headers=h(PROF), files=files).status_code == 200
    # Temp file path never built from the uploaded name.
    assert "evil" not in ingested[0] and ".." not in ingested[0]
