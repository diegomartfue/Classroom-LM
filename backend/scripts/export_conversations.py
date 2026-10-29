"""
Export every saved pilot conversation for research review.

    cd backend
    python scripts/export_conversations.py                    # everything
    python scripts/export_conversations.py --since 2026-10-01 # turns on/after a UTC date

Writes to backend/exports/ (gitignored):
  conversations_<UTC timestamp>.csv    one row per tutor turn
  conversations_<UTC timestamp>.json   the same turns with every feedback
                                       and check-work entry in full
  transcripts_<UTC timestamp>/         one readable HTML transcript per
                                       participant (<CODE>.html, with the
                                       diagrams they were shown) plus an
                                       index.html; skip with --no-transcripts

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
import base64
import csv
import html
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
            # Transcripts only (see _TRANSCRIPT_ONLY). Turns saved before the
            # SVG was recorded have diagram_rendered but no diagram_svg.
            "diagram_rendered": bool(data.get("diagram_rendered")),
            "diagram_svg": data.get("diagram_svg") or "",
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
        for field in ("student_message", "tutor_reply", "error", "diagram_svg"):
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


# Turn fields used by the HTML transcripts but kept out of the CSV and JSON,
# so those two files stay exactly as they were.
_TRANSCRIPT_ONLY = ("diagram_rendered", "diagram_svg")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_export(export: dict, out_dir: Path, stamp: str | None = None) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = stamp or _utc_stamp()
    csv_path = out_dir / f"conversations_{stamp}.csv"
    json_path = out_dir / f"conversations_{stamp}.json"
    # utf-8-sig so Excel opens accented (e.g. Spanish) text correctly.
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for t in export["turns"]:
            writer.writerow({col: _csv_safe(t.get(col)) for col in CSV_COLUMNS})
    json_export = {**export, "turns": [
        {k: v for k, v in t.items() if k not in _TRANSCRIPT_ONLY} for t in export["turns"]]}
    json_path.write_text(json.dumps(json_export, indent=2, ensure_ascii=False, default=str),
                         encoding="utf-8")
    return csv_path, json_path


# --- HTML transcripts ------------------------------------------------------------
# Every piece of student, tutor and diagram text goes through _esc() or is
# base64-encoded into an <img> (where SVG scripts never run), so nothing a
# student typed or a model produced can execute in the reviewer's browser.

_KATEX = "https://cdn.jsdelivr.net/npm/katex@0.16.47/dist"
_KATEX_HEAD = f"""<link rel="stylesheet" href="{_KATEX}/katex.min.css"
  integrity="sha384-nH0MfJ44wi1dd7w6jinlyBgljjS8EJAh2JBoRad8a3VDw2K69vfaaqm4WnR+gXtA" crossorigin="anonymous">
<script defer src="{_KATEX}/katex.min.js"
  integrity="sha384-CwjPRVHTvLiMBFjEoij+QZViMV5rhTOIp7CJzl24JEqpRDA1sJFHVXXLURktbYYp" crossorigin="anonymous"></script>
<script defer src="{_KATEX}/contrib/auto-render.min.js"
  integrity="sha384-bjyGPfbij8/NDKJhSGZNP/khQVgtHUE5exjm4Ydllo42FwIgYsdLO2lXGmRBf5Mz" crossorigin="anonymous"
  onload="renderMathInElement(document.body, {{delimiters: [
    {{left: '$$', right: '$$', display: true}}, {{left: '$', right: '$', display: false}}],
    throwOnError: false}});"></script>"""

_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #fff; color: #1a1a1a;
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
main { max-width: 820px; margin: 0 auto; padding: 32px 20px 64px; }
header { border-bottom: 2px solid #1a1a1a; padding-bottom: 12px; margin-bottom: 24px; }
h1 { font-size: 22px; margin: 0 0 6px; }
h2 { font-size: 16px; margin: 32px 0 12px; padding-bottom: 4px; border-bottom: 1px solid #ccc; }
h2 .when { font-weight: normal; color: #555; font-size: 13px; margin-left: 8px; }
.meta { color: #444; font-size: 13px; margin: 0; }
.turn { margin: 0 0 18px; break-inside: avoid; page-break-inside: avoid; }
.msg { border: 1px solid #ddd; border-radius: 8px; padding: 10px 14px; margin: 6px 0; }
.msg.student { background: #f4f6f8; }
.who { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: #555; }
.text { white-space: pre-wrap; overflow-wrap: anywhere; margin-top: 2px; }
.turn-meta { font-size: 12px; color: #555; display: flex; flex-wrap: wrap; gap: 4px 14px; }
.tag { border: 1px solid #bbb; border-radius: 4px; padding: 0 6px; }
.diagram { margin-top: 10px; break-inside: avoid; page-break-inside: avoid; }
/* A model SVG often has only a viewBox, so give it a width rather than letting
   it stretch to the page. */
.diagram img { display: block; width: 100%; max-width: 560px; height: auto; border: 1px solid #ddd;
  border-radius: 6px; background: #fff; padding: 6px; margin-top: 6px; }
.note { font-size: 13px; color: #666; font-style: italic; margin-top: 8px; }
.error { font-size: 13px; color: #8a1c1c; margin-top: 8px; }
.check { border-left: 3px solid #888; margin: 6px 0 0 14px; padding: 4px 12px; font-size: 13px;
  break-inside: avoid; page-break-inside: avoid; }
.check ul { margin: 4px 0 0; padding-left: 18px; }
.check .status { font-weight: 600; }
.check .correct { color: #1d6b2c; } .check .incorrect { color: #8a1c1c; }
.katex-display { overflow-x: auto; overflow-y: hidden; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #ddd; }
a { color: #0b4f9c; }
@page { margin: 16mm 14mm; }
@media print {
  main { max-width: none; padding: 0; }
  .msg.student { background: none; }
  h2 { break-after: avoid; page-break-after: avoid; }
  a { color: inherit; text-decoration: none; }
  .katex-display { overflow: visible; }
}
"""


def _esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _parse_ts(timestamp):
    try:
        ts = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return None
    return ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _fmt_ts(timestamp) -> str:
    ts = _parse_ts(timestamp)
    return ts.strftime("%Y-%m-%d %H:%M UTC") if ts else str(timestamp or "")


def _svg_img(svg: str) -> str:
    """One <img> per <svg> (a multi-problem DRAW turn concatenates several,
    which isn't valid as a single image). An SVG loaded as an image needs its
    namespace declared, which inline-in-HTML SVG from the model often omits."""
    parts = re.findall(r"<svg\b.*?</svg>", svg, flags=re.S | re.I) or [svg]
    imgs = []
    for part in parts:
        open_tag = re.match(r"<svg\b[^>]*>", part, flags=re.I)
        if open_tag:
            tag = open_tag.group(0)
            new_tag = tag
            if "xmlns=" not in tag:
                new_tag = new_tag[:4] + ' xmlns="http://www.w3.org/2000/svg"' + new_tag[4:]
            if "xlink:" in part and "xmlns:xlink" not in tag:
                new_tag = new_tag[:4] + ' xmlns:xlink="http://www.w3.org/1999/xlink"' + new_tag[4:]
            part = new_tag + part[len(tag):]
        data = base64.b64encode(part.encode("utf-8")).decode("ascii")
        imgs.append(f'<img src="data:image/svg+xml;base64,{data}" alt="Diagram shown to the student">')
    return "".join(imgs)


def _check_html(check: dict) -> str:
    items = []
    for r in check.get("results") or []:
        status = str(r.get("status") or "")
        detail = f" &mdash; {_esc(r.get('detail'))}" if r.get("detail") else ""
        items.append(f'<li><span class="status {_esc(status)}">{_esc(status)}</span>: '
                     f'<span class="text">{_esc(r.get("line"))}</span>{detail}</li>')
    when = f" ({_esc(_fmt_ts(check.get('timestamp')))})" if check.get("timestamp") else ""
    return (f'<div class="check"><div class="who">Show your work check{when}</div>'
            f'<ul>{"".join(items)}</ul></div>')


def _turn_html(t: dict) -> str:
    meta = [f"<span>Turn {_esc(t['turn_number'])}</span>",
            f"<span>{_esc(_fmt_ts(t['timestamp']))}</span>"]
    if t.get("hint_level") is not None:
        meta.append(f'<span class="tag">Hint level {_esc(t["hint_level"])}</span>')
    if t.get("feedback") == "up":
        meta.append('<span class="tag">Rated &#128077; helpful</span>')
    elif t.get("feedback") == "down":
        meta.append('<span class="tag">Rated &#128078; not helpful</span>')
    if t.get("diagram_svg"):
        diagram = f'<div class="diagram">{_svg_img(t["diagram_svg"])}</div>'
    elif t.get("diagram_rendered"):
        diagram = '<div class="note">(diagram shown, not saved)</div>'
    else:
        diagram = ""
    error = f'<div class="error">Error: {_esc(t["error"])}</div>' if t.get("error") else ""
    checks = "".join(_check_html(c) for c in t.get("check_work_entries") or [])
    return (f'<div class="turn"><div class="turn-meta">{"".join(meta)}</div>'
            f'<div class="msg student"><div class="who">Student</div>'
            f'<div class="text">{_esc(t["student_message"])}</div></div>'
            f'<div class="msg tutor"><div class="who">Tutor</div>'
            f'<div class="text">{_esc(t["tutor_reply"])}</div>{diagram}{error}</div>'
            f'{checks}</div>')


def _page(title: str, body: str, math: bool) -> str:
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{_esc(title)}</title><style>{_CSS}</style>'
            f'{_KATEX_HEAD if math else ""}</head>\n<body><main>{body}</main></body></html>\n')


def _sessions(turns: list[dict]) -> list[list[dict]]:
    """Turns grouped by session, sessions in time order, turns in turn order."""
    grouped = defaultdict(list)
    for t in turns:
        grouped[t["session_id"]].append(t)
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    sessions = [sorted(ts, key=lambda t: t["turn_number"]) for ts in grouped.values()]
    return sorted(sessions, key=lambda ts: min(_parse_ts(t["timestamp"]) or epoch for t in ts))


def _date_range(turns: list[dict]) -> str:
    dates = sorted(ts.date() for ts in (_parse_ts(t["timestamp"]) for t in turns) if ts)
    if not dates:
        return "unknown dates"
    return dates[0].isoformat() if dates[0] == dates[-1] else f"{dates[0]} to {dates[-1]}"


def _transcript_filename(code: str, taken: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9_-]", "_", code) or "participant"
    name, n = f"{base}.html", 2
    while name.lower() in taken or name.lower() == "index.html":
        name, n = f"{base}_{n}.html", n + 1
    taken.add(name.lower())
    return name


def write_transcripts(export: dict, out_dir: Path, stamp: str | None = None) -> Path:
    """One HTML transcript per participant, plus index.html. Returns the folder."""
    folder = out_dir / f"transcripts_{stamp or _utc_stamp()}"
    folder.mkdir(parents=True, exist_ok=True)
    by_code = defaultdict(list)
    for t in export["turns"]:
        by_code[t["participant_code"]].append(t)

    rows, taken = [], set()
    for code in sorted(by_code):
        turns = by_code[code]
        sessions = _sessions(turns)
        summary = (f"{len(sessions)} session{'s' * (len(sessions) != 1)} &middot; "
                   f"{len(turns)} turn{'s' * (len(turns) != 1)} &middot; {_date_range(turns)}")
        body = [f"<header><h1>Participant {_esc(code)}</h1><p class=\"meta\">{summary}</p></header>"]
        for i, session in enumerate(sessions, 1):
            body.append(f'<section><h2>Session {i}<span class="when">started '
                        f'{_esc(_fmt_ts(session[0]["timestamp"]))}</span></h2>')
            body.extend(_turn_html(t) for t in session)
            body.append("</section>")
        filename = _transcript_filename(code, taken)
        (folder / filename).write_text(_page(f"Transcript {code}", "".join(body), math=True),
                                       encoding="utf-8")
        rows.append(f'<tr><td><a href="{_esc(filename)}">{_esc(code)}</a></td>'
                    f"<td>{len(sessions)}</td><td>{len(turns)}</td>"
                    f"<td>{_esc(_date_range(turns))}</td></tr>")

    since = f" &middot; turns since {_esc(export['since'])}" if export.get("since") else ""
    index = (f"<header><h1>Pilot transcripts</h1><p class=\"meta\">Exported "
             f"{_esc(_fmt_ts(export['exported_at']))} &middot; {len(by_code)} participants "
             f"&middot; {export['turn_count']} turns{since}</p></header>"
             f"<table><thead><tr><th>Participant</th><th>Sessions</th><th>Turns</th>"
             f"<th>Dates</th></tr></thead><tbody>{''.join(rows)}</tbody></table>")
    (folder / "index.html").write_text(_page("Pilot transcripts", index, math=False),
                                       encoding="utf-8")
    return folder


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Export pilot conversations for research.")
    parser.add_argument("--since", type=date.fromisoformat, metavar="YYYY-MM-DD",
                        help="only turns saved on or after this UTC date")
    parser.add_argument("--traces-dir", type=Path, default=BACKEND / "traces")
    parser.add_argument("--state-dir", type=Path, default=BACKEND / "state")
    parser.add_argument("--out-dir", type=Path, default=BACKEND / "exports")
    parser.add_argument("--uploads-dir", type=Path, default=BACKEND / "uploads")
    parser.add_argument("--no-transcripts", action="store_true",
                        help="skip the per-participant HTML transcripts")
    args = parser.parse_args(argv)

    export = build_export(args.traces_dir,
                          args.state_dir / "feedback.jsonl",
                          args.state_dir / "check_work.jsonl",
                          since=args.since, uploads_dir=args.uploads_dir)
    stamp = _utc_stamp()
    csv_path, json_path = write_export(export, args.out_dir, stamp)
    transcripts = None if args.no_transcripts else write_transcripts(export, args.out_dir, stamp)
    print(f"{export['turn_count']} turns from {export['participant_count']} participants")
    if export["skipped_without_participant_code"]:
        print(f"skipped {export['skipped_without_participant_code']} turns with no "
              "participant code (saved before participant codes existed)")
    if export["skipped_professor_turns"]:
        print(f"skipped {export['skipped_professor_turns']} of the professor's own turns")
    print(f"CSV:  {csv_path}")
    print(f"JSON: {json_path}")
    if transcripts:
        print(f"HTML: {transcripts / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
