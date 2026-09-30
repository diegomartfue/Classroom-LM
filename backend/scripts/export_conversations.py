"""
Export every saved pilot conversation for research review.

    cd backend
    python scripts/export_conversations.py                    # everything
    python scripts/export_conversations.py --since 2026-10-01 # turns on/after a UTC date

Writes two files to backend/exports/ (gitignored):
  conversations_<UTC timestamp>.csv    one row per tutor turn
  conversations_<UTC timestamp>.json   the same turns with every feedback
                                       and check-work entry in full

Sources, all written by the running backend:
  traces/{session_id}/{turn}.json   the turn itself (agents/memory.py)
  state/feedback.jsonl              thumbs up/down (feedback_store.py)
  state/check_work.jsonl            show-your-work checks (check_work_store.py)

Participants are identified only by their pilot code. Turns saved without
one (development data from before participant codes existed) are skipped
and counted, as are the professor's own turns (codes in the current
professor list). File names of participants' private uploads can identify
a student (JaneSmith_HW3.pdf); any that appear in a message or reply are
replaced with "[uploaded file]". No API calls; read-only on the data folders.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import participants  # noqa: E402
from check_work_store import read_check_work  # noqa: E402
from feedback_store import read_feedback  # noqa: E402

REDACTED_FILE = "[uploaded file]"

CSV_COLUMNS = [
    "participant_code", "session_id", "timestamp", "turn_number",
    "student_message", "tutor_reply", "route", "decision", "hint_level",
    "feedback", "check_work", "error",
]

# The non-streaming /tutor path logs per-agent output instead of one
# response_text; the reply is whichever of these agents produced it.
_REPLY_AGENTS = ("conversationalist", "direct_tutor", "draw_clarify")


def _reply_from(data: dict) -> str:
    if isinstance(data.get("response_text"), str):
        return data["response_text"]
    agents = data.get("agents") if isinstance(data.get("agents"), dict) else {}
    for name in _REPLY_AGENTS:
        out = agents.get(name)
        if isinstance(out, dict) and isinstance(out.get("response"), str):
            return out["response"]
    return ""


def _decision_from(data: dict):
    if data.get("decision") is not None:
        return data["decision"]
    agents = data.get("agents") if isinstance(data.get("agents"), dict) else {}
    plan = agents.get("pedagogical_planner")
    return plan.get("decision") if isinstance(plan, dict) else None


def _on_or_after(timestamp, since: date | None) -> bool:
    if since is None:
        return True
    try:
        ts = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return False
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc)
    return ts.date() >= since


def load_turns(traces_dir: Path, since: date | None) -> tuple[list[dict], int]:
    """(turns, number skipped for having no participant code)."""
    turns, skipped = [], 0
    if not traces_dir.is_dir():
        return turns, skipped
    for turn_file in sorted(traces_dir.glob("*/*.json")):
        if not turn_file.stem.isdigit():
            continue
        try:
            record = json.loads(turn_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        code = data.get("participant_code")
        if not code:
            skipped += 1
            continue
        timestamp = record.get("logged_at")
        if not _on_or_after(timestamp, since):
            continue
        turns.append({
            "participant_code": code,
            "session_id": record.get("session_id", turn_file.parent.name),
            "timestamp": timestamp,
            "turn_number": int(record.get("turn", turn_file.stem)),
            "student_message": data.get("student_message", data.get("message", "")),
            "tutor_reply": _reply_from(data),
            "route": data.get("route"),
            "decision": _decision_from(data),
            "hint_level": data.get("hint_level"),
            "error": data.get("error"),
        })
    turns.sort(key=lambda t: (t["participant_code"], t["session_id"], t["turn_number"]))
    return turns, skipped


def private_upload_names(uploads_dir: Path) -> list[str]:
    """Every participant upload's original name, plus its name without the
    extension (a student may type "JaneSmith_HW3"). Longest first, so the
    full name is replaced before its stem."""
    names: set[str] = set()
    for index in uploads_dir.glob("participants/*/index.json"):
        try:
            records = json.loads(index.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for r in records if isinstance(records, list) else []:
            name = r.get("filename") if isinstance(r, dict) else None
            if isinstance(name, str) and name.strip():
                names.add(name.strip())
                stem = Path(name.strip()).stem
                if len(stem) >= 4:  # "hw" or "a1" would redact ordinary words
                    names.add(stem)
    return sorted(names, key=len, reverse=True)


def _redact(text, names: list[str]):
    if not isinstance(text, str) or not names:
        return text
    for name in names:
        text = re.sub(re.escape(name), REDACTED_FILE, text, flags=re.IGNORECASE)
    return text


def _by_turn(entries: list[dict]) -> dict:
    grouped = defaultdict(list)
    for e in entries:
        if isinstance(e, dict):
            grouped[(e.get("session_id"), e.get("turn_number"))].append(e)
    return grouped


def _summarize_checks(checks: list[dict]) -> str:
    """One readable CSV cell: every line of every check on this turn."""
    parts = []
    for check in checks:
        parts.append("; ".join(f"{r.get('status')}: {r.get('line')}"
                               for r in check.get("results") or []))
    return " || ".join(p for p in parts if p)


def build_export(traces_dir: Path, feedback_path: Path, check_work_path: Path,
                 since: date | None = None, uploads_dir: Path | None = None) -> dict:
    turns, skipped = load_turns(traces_dir, since)
    professors = participants.professor_codes()
    professor_turns = sum(t["participant_code"] in professors for t in turns)
    turns = [t for t in turns if t["participant_code"] not in professors]
    names = private_upload_names(uploads_dir) if uploads_dir else []
    for t in turns:
        for field in ("student_message", "tutor_reply", "error"):
            t[field] = _redact(t[field], names)
    feedback = _by_turn(read_feedback(path=str(feedback_path)))
    checks = _by_turn(read_check_work(path=str(check_work_path)))
    for t in turns:
        key = (t["session_id"], t["turn_number"])
        t["feedback_entries"] = feedback.get(key, [])
        t["check_work_entries"] = checks.get(key, [])
        # Feedback is append-only, so a changed mind is a later entry.
        t["feedback"] = t["feedback_entries"][-1]["rating"] if t["feedback_entries"] else ""
        t["check_work"] = _summarize_checks(t["check_work_entries"])
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "since": since.isoformat() if since else None,
        "turn_count": len(turns),
        "participant_count": len({t["participant_code"] for t in turns}),
        "skipped_without_participant_code": skipped,
        "skipped_professor_turns": professor_turns,
        "turns": turns,
    }


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value) -> str:
    """Spreadsheets run a cell starting with '=' as a formula — and students
    type equations. Prefix those with a quote so Excel shows the text. The
    JSON file keeps the exact original."""
    if value is None:
        return ""
    s = str(value)
    return "'" + s if s.startswith(_FORMULA_PREFIXES) else s


def write_export(export: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    csv_path = out_dir / f"conversations_{stamp}.csv"
    json_path = out_dir / f"conversations_{stamp}.json"
    # utf-8-sig so Excel opens accented (e.g. Spanish) text correctly.
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for t in export["turns"]:
            writer.writerow({col: _csv_safe(t.get(col)) for col in CSV_COLUMNS})
    json_path.write_text(json.dumps(export, indent=2, ensure_ascii=False, default=str),
                         encoding="utf-8")
    return csv_path, json_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Export pilot conversations for research.")
    parser.add_argument("--since", type=date.fromisoformat, metavar="YYYY-MM-DD",
                        help="only turns saved on or after this UTC date")
    parser.add_argument("--traces-dir", type=Path, default=BACKEND / "traces")
    parser.add_argument("--state-dir", type=Path, default=BACKEND / "state")
    parser.add_argument("--out-dir", type=Path, default=BACKEND / "exports")
    parser.add_argument("--uploads-dir", type=Path, default=BACKEND / "uploads")
    args = parser.parse_args(argv)

    export = build_export(args.traces_dir,
                          args.state_dir / "feedback.jsonl",
                          args.state_dir / "check_work.jsonl",
                          since=args.since, uploads_dir=args.uploads_dir)
    csv_path, json_path = write_export(export, args.out_dir)
    print(f"{export['turn_count']} turns from {export['participant_count']} participants")
    if export["skipped_without_participant_code"]:
        print(f"skipped {export['skipped_without_participant_code']} turns with no "
              "participant code (saved before participant codes existed)")
    if export["skipped_professor_turns"]:
        print(f"skipped {export['skipped_professor_turns']} of the professor's own turns")
    print(f"CSV:  {csv_path}")
    print(f"JSON: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
