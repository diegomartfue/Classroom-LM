"""
Pilot item 1 — run_stream() must log every turn and save the student model,
mirroring run()'s existing guarantee. Previously it never touched
self.memory at all.
"""
from agents.orchestrator import OrchestratorAgent
from test_run_stream_integration import RoutingClient


class RecordingMemory:
    """Records every memory call instead of touching disk."""
    def __init__(self):
        self.created_sessions = []
        self.logged_turns = []       # (session_id, turn_number, data)
        self.saved_models = []       # (student_id, model)
        self.logged_errors = []

    def create_session(self, session_id):
        self.created_sessions.append(session_id)
        return f"/fake/{session_id}"

    def log_turn(self, session_id, turn_number, data):
        self.logged_turns.append((session_id, turn_number, data))
        return f"/fake/{session_id}/{turn_number}.json"

    def save_student_model(self, student_id, model):
        self.saved_models.append((student_id, model))
        return f"/fake/{student_id}.json"

    def log_error(self, session_id, error, fix_attempted, success):
        self.logged_errors.append((session_id, error, fix_attempted, success))

    def get_student_model(self, student_id):
        return {}


def _agent(route, decision="HINT"):
    agent = OrchestratorAgent()
    agent.client = RoutingClient(route, decision)
    agent.memory = RecordingMemory()
    return agent


def test_run_stream_logs_a_turn_and_saves_the_student_model():
    agent = _agent("CONCEPT")
    events = list(agent.run_stream("what is torque?", [], {}, session_id="s1", student_id="stu1"))
    assert events[-1]["type"] == "done"

    assert agent.memory.created_sessions == ["s1"]
    assert len(agent.memory.logged_turns) == 1
    session_id, turn_number, data = agent.memory.logged_turns[0]
    assert session_id == "s1"
    assert turn_number == 0  # no prior user messages in an empty history
    assert data["route"] == "CONCEPT"
    assert "response_text" in data and data["response_text"]

    assert len(agent.memory.saved_models) == 1
    student_id, model = agent.memory.saved_models[0]
    assert student_id == "stu1"


def test_run_stream_generates_session_and_student_ids_when_omitted():
    agent = _agent("CONCEPT")
    list(agent.run_stream("what is torque?", [], {}))
    assert len(agent.memory.created_sessions) == 1
    assert agent.memory.created_sessions[0]  # non-empty auto-generated id
    assert agent.memory.saved_models[0][0] == "default"


def test_run_stream_turn_number_counts_prior_user_messages():
    agent = _agent("CONCEPT")
    history = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "c"},
    ]
    list(agent.run_stream("what is torque?", history, {}, session_id="s1"))
    _, turn_number, _ = agent.memory.logged_turns[0]
    assert turn_number == 2


def test_run_stream_still_logs_and_saves_after_an_upstream_failure():
    class Boom(RoutingClient):
        def create(self, **kw):
            import agents.orchestrator as o
            if kw["system"] is o.STUDENT_MODELER_PROMPT:
                raise RuntimeError("boom")
            return super().create(**kw)

    agent = OrchestratorAgent()
    agent.client = Boom("CREATE")
    agent.memory = RecordingMemory()

    events = list(agent.run_stream("make a problem", [], {}, session_id="s1", student_id="stu1"))
    assert events[-2]["type"] == "error"
    assert events[-1]["type"] == "done"

    # The turn is still logged (with the error captured) and the model saved
    # — a mid-stream failure must never mean silently losing the research
    # data for that turn.
    assert len(agent.memory.logged_turns) == 1
    assert agent.memory.logged_turns[0][2]["error"]
    assert len(agent.memory.saved_models) == 1
    assert len(agent.memory.logged_errors) == 1


def test_run_stream_meta_student_model_is_what_gets_saved():
    # The DRAW route's "meta" event passes student_model through unchanged
    # (DRAW never runs the modeler) — confirm that's what lands in
    # save_student_model, not some other value.
    agent = _agent("DRAW")
    marker_model = {"concept_mastery": {"fbd_construction": 0.42}}
    list(agent.run_stream("draw the FBD", [], marker_model, session_id="s1", student_id="stu1"))
    assert agent.memory.saved_models[-1] == ("stu1", marker_model)
