"""
Pilot item 4 — "the tutor remembers you": on a fresh session (empty incoming
student_model), run()/run_stream() load whatever was saved for that student
last time via memory.get_student_model(). A non-empty incoming model is
trusted as-is (never silently overwritten mid-conversation), and a failed
load falls back to {} rather than crashing.
"""
from agents.orchestrator import OrchestratorAgent
from test_run_stream_integration import RoutingClient


class FakeMemoryWithSavedModel:
    """Returns a canned saved model for one known student id; {} for any
    other id, matching get_student_model's own real behavior for an
    unknown/never-saved student."""
    def __init__(self, saved_models=None):
        self.saved_models = saved_models or {}
        self.create_session_calls = []
        self.logged_turns = []
        self.saved = []

    def create_session(self, session_id):
        self.create_session_calls.append(session_id)

    def get_student_model(self, student_id):
        return self.saved_models.get(student_id, {})

    def log_turn(self, session_id, turn_number, data):
        self.logged_turns.append((session_id, turn_number, data))

    def save_student_model(self, student_id, model):
        self.saved.append((student_id, model))

    def log_error(self, *a, **kw):
        pass


SAVED_MODEL = {
    "concept_mastery": {"fbd_construction": 0.8},
    "current_state": "progressing",
}


def _agent(route="CONCEPT"):
    agent = OrchestratorAgent()
    agent.client = RoutingClient(route)
    agent.memory = FakeMemoryWithSavedModel({"stu-returning": SAVED_MODEL})
    return agent


def test_run_loads_saved_model_for_a_returning_student_with_empty_model():
    agent = _agent()
    result = agent.run("what is torque?", [], {}, student_id="stu-returning")
    # The loaded model is what everything downstream sees, and what gets
    # (re-)saved at the end of the turn if nothing updates it.
    assert result["updated_student_model"] == SAVED_MODEL


def test_run_stream_loads_saved_model_for_a_returning_student():
    agent = _agent()
    events = list(agent.run_stream("what is torque?", [], {}, student_id="stu-returning"))
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["student_model"] == SAVED_MODEL


def test_new_student_with_no_saved_model_falls_back_to_empty():
    agent = _agent()
    result = agent.run("what is torque?", [], {}, student_id="brand-new-student")
    assert result["updated_student_model"] == {}


def test_nonempty_incoming_model_is_never_overwritten_by_a_saved_one():
    # Mid-conversation the frontend already has a real (non-empty)
    # studentModel from an earlier turn's response — that must win over
    # whatever's on disk, not get silently replaced.
    agent = _agent()
    in_flight_model = {"concept_mastery": {"fbd_construction": 0.1}, "current_state": "stuck_on_fbd"}
    result = agent.run("what is torque?", [], in_flight_model, student_id="stu-returning")
    assert result["updated_student_model"] == in_flight_model


def test_a_failed_load_falls_back_to_empty_not_a_crash():
    class BrokenMemory(FakeMemoryWithSavedModel):
        def get_student_model(self, student_id):
            raise OSError("disk read failed")

    agent = OrchestratorAgent()
    agent.client = RoutingClient("CONCEPT")
    agent.memory = BrokenMemory()
    result = agent.run("what is torque?", [], {}, student_id="stu1")  # must not raise
    assert result["updated_student_model"] == {}


def test_default_student_id_without_student_model_still_loads():
    # No student_id given at all -> "default" -> still goes through the
    # same load path (useful for the legacy no-auth callers).
    agent = _agent()
    agent.memory.saved_models["default"] = SAVED_MODEL
    result = agent.run("what is torque?", [], {})
    assert result["updated_student_model"] == SAVED_MODEL
