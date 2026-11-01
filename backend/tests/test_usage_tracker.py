"""
Pilot item 2 — real per-call token logging + a daily spending limit.
Never touches the real Anthropic API: UsageTrackingClient wraps a fake
"real client" throughout.
"""
import json

import pytest

from utils.usage_tracker import (
    DailyLimitReached,
    DailyUsageTracker,
    UsageTrackingClient,
    _cost_usd,
)


class FakeUsage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeResponse:
    def __init__(self, input_tokens=100, output_tokens=200):
        self.usage = FakeUsage(input_tokens, output_tokens)


class FakeRealClient:
    """Records whether create()/stream() was actually invoked — the whole
    point of DailyLimitReached is that it never reaches this."""
    def __init__(self):
        self.messages = self
        self.create_calls = 0
        self.stream_calls = 0

    def create(self, **kw):
        self.create_calls += 1
        return FakeResponse()

    def stream(self, **kw):
        self.stream_calls += 1
        return FakeStreamCtxWithFinal()


class FakeFinalMessage:
    def __init__(self):
        self.usage = FakeUsage(50, 75)


class FakeStreamCtxWithFinal:
    """Mimics the real SDK: usable as `with ...stream() as s: for c in
    s.text_stream: ...`, and s.get_final_message() after consumption."""
    def __init__(self):
        self.text_stream = iter(["hello ", "world"])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return FakeFinalMessage()


# --- DailyUsageTracker ------------------------------------------------------

def test_record_and_today_total(tmp_path):
    tracker = DailyUsageTracker(usage_dir=str(tmp_path), daily_limit_usd=100.0)
    tracker.record(model="claude-sonnet-5", input_tokens=1000, output_tokens=500, agent="router")
    tracker.record(model="claude-haiku-4-5-20251001", input_tokens=200, output_tokens=100, agent="input_parser")

    total = tracker.today_total()
    assert total["calls"] == 2
    assert total["tokens_input"] == 1200
    assert total["tokens_output"] == 600
    assert total["cost_usd"] > 0


def test_usage_file_is_one_json_line_per_call(tmp_path):
    tracker = DailyUsageTracker(usage_dir=str(tmp_path))
    tracker.record(model="claude-sonnet-5", input_tokens=10, output_tokens=20)
    tracker.record(model="claude-sonnet-5", input_tokens=30, output_tokens=40)
    with open(tracker._path()) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    assert len(rows) == 2
    assert rows[0]["input_tokens"] == 10
    assert rows[1]["input_tokens"] == 30


def test_limit_not_reached_when_under(tmp_path):
    tracker = DailyUsageTracker(usage_dir=str(tmp_path), daily_limit_usd=10.0)
    tracker.record(model="claude-haiku-4-5-20251001", input_tokens=100, output_tokens=100)
    assert tracker.limit_reached() is False


def test_limit_reached_when_at_or_over(tmp_path):
    tracker = DailyUsageTracker(usage_dir=str(tmp_path), daily_limit_usd=0.001)
    tracker.record(model="claude-opus-5", input_tokens=100_000, output_tokens=100_000)
    assert tracker.limit_reached() is True


def test_env_var_sets_default_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("DAILY_COST_LIMIT_USD", "5.5")
    tracker = DailyUsageTracker(usage_dir=str(tmp_path))
    assert tracker.daily_limit_usd == 5.5


def test_malformed_env_var_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.setenv("DAILY_COST_LIMIT_USD", "not-a-number")
    tracker = DailyUsageTracker(usage_dir=str(tmp_path))
    assert tracker.daily_limit_usd > 0  # falls back, doesn't raise


def test_unknown_model_falls_back_to_conservative_rate():
    cheap = _cost_usd("claude-haiku-4-5-20251001", 1_000_000, 1_000_000)
    unknown = _cost_usd("some-future-model-nobody-added-yet", 1_000_000, 1_000_000)
    assert unknown > cheap  # falls back to the expensive rate, never under-counts


def test_corrupt_usage_line_is_skipped_not_fatal(tmp_path):
    tracker = DailyUsageTracker(usage_dir=str(tmp_path))
    tracker.record(model="claude-sonnet-5", input_tokens=10, output_tokens=20)
    with open(tracker._path(), "a") as fh:
        fh.write("not valid json\n")
    total = tracker.today_total()  # must not raise
    assert total["calls"] == 1


def test_missing_usage_file_returns_zeros(tmp_path):
    tracker = DailyUsageTracker(usage_dir=str(tmp_path))
    assert tracker.today_total() == {"calls": 0, "tokens_input": 0, "tokens_output": 0, "cost_usd": 0.0}


# --- UsageTrackingClient -----------------------------------------------------

def test_create_records_usage_and_returns_the_real_response(tmp_path):
    tracker = DailyUsageTracker(usage_dir=str(tmp_path), daily_limit_usd=100.0)
    real = FakeRealClient()
    client = UsageTrackingClient(real, tracker)

    response = client.messages.create(model="claude-sonnet-5", max_tokens=100,
                                       messages=[{"role": "user", "content": "hi"}])
    assert real.create_calls == 1
    assert response.usage.input_tokens == 100
    assert tracker.today_total()["calls"] == 1


def test_create_raises_before_calling_real_client_once_limit_hit(tmp_path):
    tracker = DailyUsageTracker(usage_dir=str(tmp_path), daily_limit_usd=0.000001)
    real = FakeRealClient()
    client = UsageTrackingClient(real, tracker)
    # Push the tracker over its (tiny) limit first.
    tracker.record(model="claude-opus-5", input_tokens=1000, output_tokens=1000)

    with pytest.raises(DailyLimitReached):
        client.messages.create(model="claude-sonnet-5", max_tokens=100, messages=[])
    assert real.create_calls == 0  # the real API was never reached


def test_stream_records_usage_via_get_final_message(tmp_path):
    tracker = DailyUsageTracker(usage_dir=str(tmp_path), daily_limit_usd=100.0)
    real = FakeRealClient()
    client = UsageTrackingClient(real, tracker)

    with client.messages.stream(model="claude-sonnet-5", max_tokens=100, messages=[]) as stream:
        chunks = list(stream.text_stream)
    assert chunks == ["hello ", "world"]
    assert real.stream_calls == 1
    assert tracker.today_total()["calls"] == 1
    assert tracker.today_total()["tokens_input"] == 50


def test_stream_raises_before_calling_real_client_once_limit_hit(tmp_path):
    tracker = DailyUsageTracker(usage_dir=str(tmp_path), daily_limit_usd=0.000001)
    real = FakeRealClient()
    client = UsageTrackingClient(real, tracker)
    tracker.record(model="claude-opus-5", input_tokens=1000, output_tokens=1000)

    with pytest.raises(DailyLimitReached):
        client.messages.stream(model="claude-sonnet-5", max_tokens=100, messages=[])
    assert real.stream_calls == 0
