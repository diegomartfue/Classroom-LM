"""
Pilot item 6 — thumbs up/down on tutor replies. Pure file-based storage, no
LLM involved anywhere in this module or its tests.
"""
import pytest

from feedback_store import FeedbackError, read_feedback, record_feedback


def test_record_feedback_writes_and_returns_an_entry(tmp_path):
    path = str(tmp_path / "feedback.jsonl")
    entry = record_feedback("s1", 3, "stu1", "up", path=path)
    assert entry["session_id"] == "s1"
    assert entry["turn_number"] == 3
    assert entry["student_id"] == "stu1"
    assert entry["rating"] == "up"
    assert "timestamp" in entry


def test_read_feedback_returns_entries_in_order(tmp_path):
    path = str(tmp_path / "feedback.jsonl")
    record_feedback("s1", 1, "stu1", "up", path=path)
    record_feedback("s1", 2, "stu1", "down", path=path)
    entries = read_feedback(path=path)
    assert len(entries) == 2
    assert entries[0]["turn_number"] == 1
    assert entries[1]["rating"] == "down"


def test_read_feedback_missing_file_returns_empty_list(tmp_path):
    assert read_feedback(path=str(tmp_path / "nope.jsonl")) == []


def test_invalid_rating_raises_feedback_error(tmp_path):
    path = str(tmp_path / "feedback.jsonl")
    with pytest.raises(FeedbackError):
        record_feedback("s1", 1, "stu1", "sideways", path=path)
    # Nothing written on a rejected rating.
    assert read_feedback(path=path) == []


def test_corrupt_line_is_skipped_not_fatal(tmp_path):
    path = str(tmp_path / "feedback.jsonl")
    record_feedback("s1", 1, "stu1", "up", path=path)
    with open(path, "a") as fh:
        fh.write("not valid json\n")
    entries = read_feedback(path=path)
    assert len(entries) == 1
