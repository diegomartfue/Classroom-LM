"""
Pilot item 2 — when the daily spending limit is hit, run()/run_stream() must
return the friendly "resting for today" message INSTEAD of calling the API,
not the generic error message and not a raw exception. This is exercised by
making agent.client.messages.create/stream raise DailyLimitReached directly
(simulating UsageTrackingClient with a hit limit) — never a real API call.
"""
from agents.orchestrator import DAILY_LIMIT_MESSAGE, OrchestratorAgent
from utils.usage_tracker import DailyLimitReached


class AlwaysOverLimitClient:
    """Every call raises DailyLimitReached immediately — the real API is
    never reached, exactly what UsageTrackingClient does once the daily
    limit is hit."""
    def __init__(self):
        self.messages = self
        self.calls = 0

    def create(self, **kw):
        self.calls += 1
        raise DailyLimitReached("Daily API spending limit ($20.00) reached.")

    def stream(self, **kw):
        self.calls += 1
        raise DailyLimitReached("Daily API spending limit ($20.00) reached.")


def test_run_returns_resting_message_without_low_confidence():
    agent = OrchestratorAgent()
    agent.client = AlwaysOverLimitClient()
    result = agent.run("what is torque?", [], {})
    assert result["response"] == DAILY_LIMIT_MESSAGE
    assert result["plan"]["decision"] == "RESTING"
    # Distinct from the generic error path — this isn't a "something broke"
    # signal, it's expected, deliberate behavior.
    assert result["low_confidence"] is False
    assert agent.client.calls == 1  # router was the only call attempted


def test_run_stream_yields_resting_message_as_a_normal_reply():
    agent = OrchestratorAgent()
    agent.client = AlwaysOverLimitClient()
    events = list(agent.run_stream("what is torque?", [], {}))

    types = [e["type"] for e in events]
    assert types == ["meta", "token", "done"]  # NOT "error" — a normal-shaped reply
    meta = events[0]
    assert meta["decision"] == "RESTING"
    token = events[1]
    assert token["text"] == DAILY_LIMIT_MESSAGE


def test_run_stream_resting_message_is_still_logged():
    from test_run_stream_memory import RecordingMemory  # reuse the fake
    agent = OrchestratorAgent()
    agent.client = AlwaysOverLimitClient()
    agent.memory = RecordingMemory()

    list(agent.run_stream("what is torque?", [], {}, session_id="s1", student_id="stu1"))
    assert len(agent.memory.logged_turns) == 1
    assert agent.memory.logged_turns[0][2]["decision"] == "RESTING"
    assert len(agent.memory.saved_models) == 1


def test_run_does_not_call_the_api_more_than_once_when_over_limit():
    # The router is the very first call in the pipeline; DailyLimitReached
    # there means nothing downstream ever runs.
    agent = OrchestratorAgent()
    agent.client = AlwaysOverLimitClient()
    agent.run("solve this beam problem", [], {})
    assert agent.client.calls == 1
