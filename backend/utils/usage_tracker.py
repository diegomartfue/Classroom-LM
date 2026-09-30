"""
utils/usage_tracker.py — real per-call token usage + a daily spending limit.

Unlike utils/cost_tracker.py (a *theoretical* per-route estimator built from
hardcoded average token counts), this module logs the actual
``response.usage`` from every live API call and enforces a real daily dollar
limit — so a pilot running against a shared research key can't run up an
unbounded bill.

Layout (anchored to the backend directory, same pattern as agents/memory.py):

    <backend>/state/usage/{YYYY-MM-DD}.jsonl   one line per API call that day

``DailyUsageTracker.record(...)`` never raises — a usage-logging failure must
never break a real tutoring response. ``UsageTrackingClient`` is the thing
that actually enforces the limit, by raising ``DailyLimitReached`` *before*
the real API call is made once the day's estimated cost is at or over the
limit — the caller (OrchestratorAgent.run/run_stream) catches that
specifically and returns a friendly "resting for today" reply instead.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_USAGE_DIR = os.path.join(_BACKEND_DIR, "state", "usage")

# USD per 1,000,000 tokens. Deliberately a small local constant (not shared
# with utils/cost_tracker.py's MODEL_COSTS) — this module sits on the
# request-blocking path, so it must never fail or drift because an unrelated
# import changed; an unrecognized model just falls back to the most
# expensive known rate (_UNKNOWN_MODEL_COST) rather than under-counting.
_MODEL_COSTS: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-opus-5": {"input": 15.00, "output": 75.00},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00},
}
_UNKNOWN_MODEL_COST = {"input": 15.00, "output": 75.00}
_MILLION = 1_000_000

# Overridable via the DAILY_COST_LIMIT_USD env var (item 2 of the pilot ask).
DEFAULT_DAILY_LIMIT_USD = 20.0


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = _MODEL_COSTS.get(model, _UNKNOWN_MODEL_COST)
    return (input_tokens / _MILLION * rates["input"]
            + output_tokens / _MILLION * rates["output"])


class DailyLimitReached(Exception):
    """Raised by UsageTrackingClient.create()/stream() when today's
    estimated spend is at or over the configured daily limit — raised
    BEFORE the real API call, so no additional spend happens finding out."""


class DailyUsageTracker:
    """Appends one JSON line per API call to state/usage/{date}.jsonl and
    answers "have we hit today's limit" by summing that file."""

    def __init__(self, usage_dir: str = _DEFAULT_USAGE_DIR,
                 daily_limit_usd: float | None = None) -> None:
        self.usage_dir = usage_dir
        os.makedirs(self.usage_dir, exist_ok=True)
        if daily_limit_usd is None:
            try:
                daily_limit_usd = float(
                    os.environ.get("DAILY_COST_LIMIT_USD", DEFAULT_DAILY_LIMIT_USD)
                )
            except ValueError:
                daily_limit_usd = DEFAULT_DAILY_LIMIT_USD
        self.daily_limit_usd = daily_limit_usd

    def _path(self, date: str | None = None) -> str:
        return os.path.join(self.usage_dir, f"{date or _today()}.jsonl")

    def record(self, model: str, input_tokens: int, output_tokens: int,
               agent: str = "") -> float:
        """Append one call's usage. Returns its estimated cost in USD.
        Never raises — a logging failure must never break a real response."""
        cost = _cost_usd(model, input_tokens, output_tokens)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "model": model,
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "cost_usd": round(cost, 6),
        }
        try:
            with open(self._path(), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            logger.warning("usage_tracker: failed to write usage log entry", exc_info=True)
        return cost

    def today_total(self, date: str | None = None) -> dict:
        """{"calls", "tokens_input", "tokens_output", "cost_usd"} for
        ``date`` (default: today, UTC). Corrupt lines are skipped, not
        fatal — matches agents/memory.py's get_error_history."""
        path = self._path(date)
        calls = tokens_input = tokens_output = 0
        cost = 0.0
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    calls += 1
                    tokens_input += entry.get("input_tokens", 0) or 0
                    tokens_output += entry.get("output_tokens", 0) or 0
                    cost += entry.get("cost_usd", 0.0) or 0.0
        return {
            "calls": calls,
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
            "cost_usd": round(cost, 6),
        }

    def limit_reached(self) -> bool:
        return self.today_total()["cost_usd"] >= self.daily_limit_usd


class _UsageTrackingStreamCtx:
    """Wraps the real ``client.messages.stream(...)`` context manager so
    usage is recorded once the stream finishes, without changing how callers
    use it (``with ...stream(...) as stream: for chunk in stream.text_stream``).
    Real Anthropic stream objects expose ``get_final_message()`` for exactly
    this — the complete accumulated Message, usage included, once the
    stream's been consumed."""

    def __init__(self, real_ctx, tracker: DailyUsageTracker, model: str):
        self._real_ctx = real_ctx
        self._tracker = tracker
        self._model = model
        self._stream = None

    def __enter__(self):
        self._stream = self._real_ctx.__enter__()
        return self._stream

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            try:
                final = self._stream.get_final_message()
                usage = getattr(final, "usage", None)
                if usage is not None:
                    self._tracker.record(
                        model=self._model,
                        input_tokens=getattr(usage, "input_tokens", 0) or 0,
                        output_tokens=getattr(usage, "output_tokens", 0) or 0,
                    )
            except Exception:
                # Usage bookkeeping must never break an otherwise-successful
                # streamed response.
                logger.warning("usage_tracker: could not record streamed usage", exc_info=True)
        return self._real_ctx.__exit__(exc_type, exc, tb)


class UsageTrackingClient:
    """Wraps a real Anthropic client. Standalone and unit-testable with a
    fake inner client — no real API access needed to test it.

    .messages.create(...) / .messages.stream(...): check the daily limit
    FIRST (raise DailyLimitReached, never reach the real API, if it's
    already hit), then record response.usage after a successful call."""

    def __init__(self, real_client, tracker: DailyUsageTracker):
        self._real_client = real_client
        self._tracker = tracker
        self.messages = self  # mirrors anthropic.Anthropic().messages.create(...)

    def create(self, **kwargs):
        if self._tracker.limit_reached():
            raise DailyLimitReached(
                f"Daily API spending limit (${self._tracker.daily_limit_usd:.2f}) reached."
            )
        response = self._real_client.messages.create(**kwargs)
        usage = getattr(response, "usage", None)
        if usage is not None:
            self._tracker.record(
                model=kwargs.get("model", "unknown"),
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
            )
        return response

    def stream(self, **kwargs):
        if self._tracker.limit_reached():
            raise DailyLimitReached(
                f"Daily API spending limit (${self._tracker.daily_limit_usd:.2f}) reached."
            )
        return _UsageTrackingStreamCtx(
            self._real_client.messages.stream(**kwargs),
            self._tracker, kwargs.get("model", "unknown"),
        )
