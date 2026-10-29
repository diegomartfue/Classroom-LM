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


# --- HTML transcripts ----------------------------------------------------------

import base64  # noqa: E402
import re  # noqa: E402

_SVG = ('<svg viewBox="0 0 40 20"><text x="2" y="12">mg</text>'
        '<script>alert("svg")</script></svg>')


@pytest.fixture
def transcript_data(tmp_path, monkeypatch):
    """One participant, two sessions (ids sort opposite to their time order):
    a math turn, an HTML-characters turn, a turn with a saved diagram, and an
    older turn whose diagram was shown but not saved."""
    monkeypatch.setenv("PILOT_PROFESSOR_CODES", "")
    monkeypatch.setenv("PILOT_PROFESSORS_FILE", str(tmp_path / "none.txt"))
    traces, state = tmp_path / "traces", tmp_path / "state"
    memory = SessionMemory(base_dir=str(traces), state_dir=str(state))

    def turn(session, n, message, reply, logged_at, **extra):
        path = memory.log_turn(session, n, {
            "participant_code": "EAGLE1234", "student_message": message,
            "hint_level": extra.get("hint_level"), "route": "PROBLEM", "decision": "HINT",
            "response_text": reply, "error": None,
            **{k: v for k, v in extra.items() if k != "hint_level"},
        })
        record = json.loads(Path(path).read_text())
        record["logged_at"] = logged_at
        Path(path).write_text(json.dumps(record))

    turn("zz-first", 0, "What is Newton's second law?", "It says $F = ma$, and $$\\sum M = I\\alpha$$.",
         "2026-10-01T09:00:00+00:00", diagram_rendered=False, diagram_svg="")
    turn("zz-first", 1, 'Is <script>alert("x")</script> & 5 < 6 > 4 ok?', "Yes, 5 < 6.",
         "2026-10-01T09:05:00+00:00", hint_level=2)
    turn("aa-second", 0, "Draw the FBD", "Here is the diagram.",
         "2026-10-03T14:30:00+00:00", diagram_rendered=True, diagram_svg=_SVG)
    turn("aa-second", 1, "And the old one?", "Shown earlier.",
         "2026-10-03T14:35:00+00:00", diagram_rendered=True)  # saved before diagram_svg existed
    record_feedback("aa-second", 0, "EAGLE1234", "down", path=str(state / "feedback.jsonl"))
    record_check_work("zz-first", 1, "EAGLE1234", [
        {"line": "F = m*a", "status": "correct", "detail": ""},
        {"line": "a < 0", "status": "incorrect", "detail": "sign <flipped>"},
    ], path=str(state / "check_work.jsonl"))
    return {"traces": traces, "state": state, "out": tmp_path / "exports"}


def _run_transcripts(d, *extra):
    assert export.main(["--traces-dir", str(d["traces"]), "--state-dir", str(d["state"]),
                        "--out-dir", str(d["out"]), *extra]) == 0
    [folder] = d["out"].glob("transcripts_*")
    return folder


def test_transcript_files_and_index(transcript_data):
    folder = _run_transcripts(transcript_data)
    [csv_path] = transcript_data["out"].glob("conversations_*.csv")
    # Same UTC timestamp as the CSV/JSON pair.
    assert folder.name == "transcripts_" + csv_path.stem.removeprefix("conversations_")
    assert sorted(p.name for p in folder.iterdir()) == ["EAGLE1234.html", "index.html"]
    index = (folder / "index.html").read_text()
    assert '<a href="EAGLE1234.html">EAGLE1234</a>' in index
    assert "<td>2</td><td>4</td>" in index


def test_transcript_header_sessions_and_turn_details(transcript_data):
    page = (_run_transcripts(transcript_data) / "EAGLE1234.html").read_text()
    assert "Participant EAGLE1234" in page
    assert "2 sessions &middot; 4 turns &middot; 2026-10-01 to 2026-10-03" in page
    # Sessions in time order, not session-id order.
    assert page.index("started 2026-10-01 09:00 UTC") < page.index("started 2026-10-03 14:30 UTC")
    assert page.index("Newton&#x27;s second law") < page.index("Draw the FBD")
    assert "2026-10-01 09:05 UTC" in page
    assert "Hint level 2" in page
    assert "Rated &#128078; not helpful" in page
    # The check sits under the turn it belongs to (turn 1 of the first session).
    check_at = page.index("Show your work check")
    assert page.index("Is &lt;script&gt;") < check_at < page.index("Draw the FBD")
    assert "a &lt; 0" in page and "sign &lt;flipped&gt;" in page


def test_transcript_escapes_student_text(transcript_data):
    page = (_run_transcripts(transcript_data) / "EAGLE1234.html").read_text()
    assert ("Is &lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; 5 &lt; 6 &gt; 4 ok?"
            in page)
    # The only <script> tags are the KaTeX loaders.
    assert all("cdn.jsdelivr.net/npm/katex" in tag
               for tag in re.findall(r"<script[^>]*>", page))


def test_transcript_math_is_left_for_katex(transcript_data):
    page = (_run_transcripts(transcript_data) / "EAGLE1234.html").read_text()
    assert "It says $F = ma$, and $$\\sum M = I\\alpha$$." in page
    assert "cdn.jsdelivr.net/npm/katex@" in page and "auto-render.min.js" in page
    assert "renderMathInElement" in page and "left: '$', right: '$'" in page


def test_transcript_diagrams_are_base64_images(transcript_data):
    page = (_run_transcripts(transcript_data) / "EAGLE1234.html").read_text()
    [encoded] = re.findall(r'<img src="data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)"', page)
    svg = base64.b64decode(encoded).decode()
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox')
    assert "<text" in svg
    # Never inlined: the SVG's own markup (and its script) isn't in the page.
    assert "<svg" not in page and 'alert("svg")' not in page
    assert page.count("(diagram shown, not saved)") == 1


def test_no_transcripts_flag(transcript_data):
    args = ["--traces-dir", str(transcript_data["traces"]),
                             "--state-dir", str(transcript_data["state"]),
                             "--out-dir", str(transcript_data["out"]), "--no-transcripts"]
    assert export.main(args) == 0
    assert sorted(p.suffix for p in transcript_data["out"].iterdir()) == [".csv", ".json"]


def test_csv_and_json_carry_no_diagram_fields(transcript_data):
    _run_transcripts(transcript_data)
    [csv_path] = transcript_data["out"].glob("*.csv")
    [json_path] = transcript_data["out"].glob("*.json")
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        assert list(next(csv.reader(fh))) == export.CSV_COLUMNS
    for turn in json.loads(json_path.read_text())["turns"]:
        assert "diagram_svg" not in turn and "diagram_rendered" not in turn


def test_transcripts_redact_uploads_and_skip_professor_and_codeless(tmp_path, monkeypatch):
    monkeypatch.setenv("PILOT_PROFESSOR_CODES", "PROF-7Q")
    monkeypatch.setenv("PILOT_PROFESSORS_FILE", str(tmp_path / "none.txt"))
    traces, state, uploads = tmp_path / "traces", tmp_path / "state", tmp_path / "uploads"
    memory = SessionMemory(base_dir=str(traces), state_dir=str(state))
    (uploads / "participants" / "P07").mkdir(parents=True)
    (uploads / "participants" / "P07" / "index.json").write_text(json.dumps([
        {"doc_id": "0123456789ab", "filename": "JaneSmith_HW3.pdf", "scope": "private"}]))
    _turn(memory, "conv-a", 0, "P07", "I uploaded JaneSmith_HW3.pdf", "Reading janesmith_hw3 now.")
    _turn(memory, "conv-p", 0, "PROF-7Q", "testing the tutor", "hello professor")
    memory.log_turn("old-dev", 0, {"route": "PROBLEM", "response_text": "hi"})

    out = tmp_path / "exports"
    assert export.main(["--traces-dir", str(traces), "--state-dir", str(state),
                        "--uploads-dir", str(uploads), "--out-dir", str(out)]) == 0
    [folder] = out.glob("transcripts_*")
    assert sorted(p.name for p in folder.iterdir()) == ["P07.html", "index.html"]
    everything = "".join(p.read_text() for p in folder.iterdir())
    assert "janesmith" not in everything.lower() and "PROF-7Q" not in everything
    assert "I uploaded [uploaded file]" in everything


def test_empty_export_writes_an_empty_index(tmp_path):
    out = tmp_path / "exports"
    assert export.main(["--traces-dir", str(tmp_path / "none"), "--state-dir",
                        str(tmp_path / "none"), "--out-dir", str(out)]) == 0
    [folder] = out.glob("transcripts_*")
    assert [p.name for p in folder.iterdir()] == ["index.html"]
