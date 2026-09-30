"""
scripts/export_conversations.py — builds fake saved sessions in a temp
folder using the backend's real writers (SessionMemory, feedback_store,
check_work_store, and one turn produced by actually running run_stream()
with a fake client), exports them, and checks the CSV and JSON are
complete and correct. Covers every CSV column. No API calls.
"""
import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from agents.memory import SessionMemory
from agents.orchestrator import OrchestratorAgent
from check_work_store import record_check_work
from feedback_store import record_feedback
from conftest import FakeResponse, FakeStreamCtx, FakeTextBlock

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))
import export_conversations as export  # noqa: E402


def _turn(memory, session, turn, code, message, reply, route="PROBLEM",
          decision="HINT", hint_level=None, logged_at=None):
    path = memory.log_turn(session, turn, {
        "participant_code": code, "student_message": message, "hint_level": hint_level,
        "route": route, "decision": decision, "response_text": reply,
        "diagram_rendered": False, "error": None,
    })
    if logged_at:
        record = json.loads(Path(path).read_text())
        record["logged_at"] = logged_at
        Path(path).write_text(json.dumps(record))


class _Client:
    """Fake Anthropic client for one real run_stream() CONCEPT turn."""
    def __init__(self):
        self.messages = self

    def create(self, **kw):
        return FakeResponse([FakeTextBlock('{"route": "CONCEPT", "confidence": 0.9}')])

    def stream(self, **kw):
        return FakeStreamCtx(["Friction ", "opposes sliding."])


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("PILOT_PROFESSOR_CODES", "")
    monkeypatch.setenv("PILOT_PROFESSORS_FILE", str(tmp_path / "no-professors.txt"))
    traces, state = tmp_path / "traces", tmp_path / "state"
    memory = SessionMemory(base_dir=str(traces), state_dir=str(state))
    fb, cw = str(state / "feedback.jsonl"), str(state / "check_work.jsonl")

    # P07: a hint session with thumbs (changed mind: down then up) and a
    # show-your-work check on turn 1.
    _turn(memory, "conv-a", 0, "P07", "A 10 kg block on a 30° incline, μk = 0.2. Find a.",
          "What forces act on the block?", decision="ASK")
    _turn(memory, "conv-a", 1, "P07", "Can I get a hint?", "Resolve gravity along the slope.",
          hint_level=1)
    _turn(memory, "conv-a", 2, "P07", "=m*g*sin(30)", "Good, now friction.", hint_level=2)
    record_feedback("conv-a", 1, "P07", "down", path=fb)
    record_feedback("conv-a", 1, "P07", "up", path=fb)
    record_check_work("conv-a", 1, "P07", [
        {"line": "N = m*g*cos(30)", "status": "correct", "detail": ""},
        {"line": "N = 50", "status": "incorrect", "detail": "right side works out to 50"},
    ], path=cw)

    # P08: one turn saved by the real run_stream() wrapper.
    agent = OrchestratorAgent()
    agent.client = _Client()
    agent.memory = memory
    list(agent.run_stream("Why does friction point up the slope?", [], {},
                          session_id="conv-b", student_id="P08"))

    # Development data from before participant codes: must be skipped.
    memory.log_turn("old-dev", 0, {"route": "PROBLEM", "response_text": "hi"})

    # An older P09 turn, for --since.
    _turn(memory, "conv-c", 0, "P09", "Old question", "Old answer",
          logged_at="2026-01-05T10:00:00+00:00")

    return {"traces": traces, "state": state, "out": tmp_path / "exports"}


def _run(data, *extra):
    assert export.main(["--traces-dir", str(data["traces"]), "--state-dir", str(data["state"]),
                        "--out-dir", str(data["out"]), *extra]) == 0
    [csv_path] = data["out"].glob("*.csv")
    [json_path] = data["out"].glob("*.json")
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return rows, json.loads(json_path.read_text(encoding="utf-8"))


def test_csv_has_every_turn_and_every_column(data):
    rows, dump = _run(data)
    assert list(rows[0].keys()) == export.CSV_COLUMNS
    assert [(r["participant_code"], r["session_id"], r["turn_number"]) for r in rows] == [
        ("P07", "conv-a", "0"), ("P07", "conv-a", "1"), ("P07", "conv-a", "2"),
        ("P08", "conv-b", "0"), ("P09", "conv-c", "0"),
    ]
    assert dump["turn_count"] == 5 and dump["participant_count"] == 3
    assert dump["skipped_without_participant_code"] == 1


def test_turn_fields_feedback_and_check_work(data):
    rows, _ = _run(data)
    by_key = {(r["session_id"], r["turn_number"]): r for r in rows}

    first = by_key[("conv-a", "0")]
    assert first["student_message"].startswith("A 10 kg block on a 30° incline, μk")
    assert first["tutor_reply"] == "What forces act on the block?"
    assert first["route"] == "PROBLEM" and first["decision"] == "ASK"
    assert first["hint_level"] == "" and first["feedback"] == "" and first["check_work"] == ""
    assert first["timestamp"]

    hinted = by_key[("conv-a", "1")]
    assert hinted["hint_level"] == "1"
    assert hinted["feedback"] == "up"  # last entry wins
    assert hinted["check_work"] == "correct: N = m*g*cos(30); incorrect: N = 50"

    # A message that starts with '=' must not become a spreadsheet formula.
    assert by_key[("conv-a", "2")]["student_message"] == "'=m*g*sin(30)"

    streamed = by_key[("conv-b", "0")]
    assert streamed["participant_code"] == "P08"
    assert streamed["student_message"] == "Why does friction point up the slope?"
    assert streamed["tutor_reply"] == "Friction opposes sliding."
    assert streamed["route"] == "CONCEPT"
    assert streamed["error"] == ""


def test_json_has_full_entries_and_raw_text(data):
    _, dump = _run(data)
    turn = next(t for t in dump["turns"]
                if t["session_id"] == "conv-a" and t["turn_number"] == 1)
    assert [f["rating"] for f in turn["feedback_entries"]] == ["down", "up"]
    [check] = turn["check_work_entries"]
    assert check["participant_code"] == "P07"
    assert check["results"][1] == {"line": "N = 50", "status": "incorrect",
                                   "detail": "right side works out to 50"}
    raw = next(t for t in dump["turns"] if t["turn_number"] == 2)
    assert raw["student_message"] == "=m*g*sin(30)"


def test_since_filters_by_date(data):
    rows, dump = _run(data, "--since", "2026-02-01")
    assert "P09" not in {r["participant_code"] for r in rows}
    assert dump["since"] == "2026-02-01" and dump["turn_count"] == 4


def test_nothing_identifying_beyond_codes(data):
    _, dump = _run(data)
    for turn in dump["turns"]:
        assert turn["participant_code"] in {"P07", "P08", "P09"}
        for entry in turn["feedback_entries"]:
            assert entry["student_id"] == turn["participant_code"]


def test_empty_data_still_writes_headers(tmp_path):
    out = tmp_path / "exports"
    assert export.main(["--traces-dir", str(tmp_path / "none"), "--state-dir",
                        str(tmp_path / "none"), "--out-dir", str(out)]) == 0
    [csv_path] = out.glob("*.csv")
    assert csv_path.read_text(encoding="utf-8-sig").splitlines() == [",".join(export.CSV_COLUMNS)]


def test_documented_command_runs_from_backend_dir(data):
    # The exact README command shape, as a real subprocess.
    result = subprocess.run(
        [sys.executable, "scripts/export_conversations.py",
         "--traces-dir", str(data["traces"]), "--state-dir", str(data["state"]),
         "--out-dir", str(data["out"]), "--since", "2026-02-01"],
        cwd=BACKEND, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "4 turns from 2 participants" in result.stdout


def test_bad_since_is_a_usage_error(data):
    with pytest.raises(SystemExit):
        export.main(["--since", "last tuesday"])


# --- Upload file names and professor turns ---------------------------------------

def test_private_upload_names_are_redacted_and_professor_turns_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("PILOT_PROFESSOR_CODES", "PROF-7Q")
    monkeypatch.setenv("PILOT_PROFESSORS_FILE", str(tmp_path / "none.txt"))
    traces, state, uploads = tmp_path / "traces", tmp_path / "state", tmp_path / "uploads"
    memory = SessionMemory(base_dir=str(traces), state_dir=str(state))
    (uploads / "participants" / "P07").mkdir(parents=True)
    (uploads / "participants" / "P07" / "index.json").write_text(json.dumps([
        {"doc_id": "0123456789ab", "filename": "JaneSmith_HW3.pdf", "scope": "private"}]))
    (uploads / "shared").mkdir()
    (uploads / "shared" / "index.json").write_text(json.dumps([
        {"doc_id": "ba9876543210", "filename": "Week3_Friction.pdf", "scope": "shared"}]))

    _turn(memory, "conv-a", 0, "P07", "I uploaded JaneSmith_HW3.pdf, see problem 2",
          "Looking at janesmith_hw3 and Week3_Friction.pdf, problem 2 asks for N.")
    _turn(memory, "conv-p", 0, "PROF-7Q", "testing the tutor", "hello professor")

    out = tmp_path / "exports"
    assert export.main(["--traces-dir", str(traces), "--state-dir", str(state),
                        "--uploads-dir", str(uploads), "--out-dir", str(out)]) == 0
    [csv_path] = out.glob("*.csv")
    [json_path] = out.glob("*.json")
    everything = csv_path.read_text(encoding="utf-8-sig") + json_path.read_text()
    assert "JaneSmith" not in everything and "janesmith" not in everything.lower()
    assert "I uploaded [uploaded file], see problem 2" in everything
    # Shared course material names are not identifying and stay.
    assert "Week3_Friction.pdf" in everything
    dump = json.loads(json_path.read_text())
    assert {t["participant_code"] for t in dump["turns"]} == {"P07"}
    assert dump["skipped_professor_turns"] == 1
