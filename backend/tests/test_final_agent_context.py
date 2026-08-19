"""
TEST GROUP 4 — the final response agents receive conversation history.

Uses a capturing fake client (no real API). Asserts the prompt the final agents
send to Claude contains the prior conversation and the current message.
"""
from agents.orchestrator import OrchestratorAgent
from conftest import FakeResponse, FakeTextBlock, FakeStreamCtx


class CapturingClient:
    """Records every create/stream call's kwargs; returns canned output."""
    def __init__(self):
        self.calls = []
        self.messages = self  # so client.messages.create / .stream both hit here

    def create(self, **kw):
        self.calls.append(kw)
        return FakeResponse([FakeTextBlock("ok")])

    def stream(self, **kw):
        self.calls.append(kw)
        return FakeStreamCtx(["ok"])


def _agent():
    agent = OrchestratorAgent()
    client = CapturingClient()
    agent.client = client
    return agent, client


def _last_user_content(client):
    return client.calls[-1]["messages"][0]["content"]


def test_direct_tutor_receives_history():
    agent, client = _agent()
    hist = [
        {"role": "user", "content": "My name is Diego."},
        {"role": "assistant", "content": "Hi Diego."},
    ]
    agent.direct_tutor("What is my name?", "CONCEPT", hist)
    uc = _last_user_content(client)
    assert "Previous conversation:" in uc
    assert "My name is Diego." in uc
    assert "Current student message:\nWhat is my name?" in uc


def test_direct_tutor_without_history_has_no_previous_block():
    agent, client = _agent()
    agent.direct_tutor("hello", "SMALLTALK", [])
    uc = _last_user_content(client)
    assert "Previous conversation:" not in uc
    assert "Current student message:\nhello" in uc


def test_conversationalist_receives_history():
    agent, client = _agent()
    hist = [{"role": "user", "content": "My name is Diego."}]
    agent.conversationalist(
        student_message="continue",
        parsed_input={}, student_model={}, plan={},
        solution=None, validation=None, visualization=None,
        conversation_history=hist,
    )
    uc = _last_user_content(client)
    assert "Previous conversation:" in uc
    assert "My name is Diego." in uc
    assert "Context bundle:" in uc  # history precedes the existing bundle


def test_conversationalist_history_not_duplicated_into_bundle():
    # History appears exactly once (as the labeled block), not also inside the
    # JSON context bundle.
    agent, client = _agent()
    hist = [{"role": "user", "content": "UNIQUE_MARKER_123"}]
    agent.conversationalist(
        student_message="hi", parsed_input={}, student_model={}, plan={},
        solution=None, validation=None, visualization=None,
        conversation_history=hist,
    )
    uc = _last_user_content(client)
    assert uc.count("UNIQUE_MARKER_123") == 1
