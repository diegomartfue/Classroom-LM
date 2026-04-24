"""
Test each agent individually.
Run: python test_agents.py
Or: python test_agents.py <agent_name>
"""
import sys
import json
from agents.orchestrator import OrchestratorAgent

agent = OrchestratorAgent()

# ============= TEST INPUTS =============
test_message = "A 5m beam is pinned at A on the left and has a roller at B on the right. A 100N downward force is at midspan. Find the reactions."

test_parsed_input = {
    "problem_type": "statics",
    "body_description": "5m horizontal beam",
    "supports": [
        {"type": "pin", "location": "A, left end"},
        {"type": "roller", "location": "B, right end"}
    ],
    "loads": [
        {"type": "force", "magnitude": "100 N", "location": "midspan", "direction": "down"}
    ],
    "unknowns": ["Ax", "Ay", "By"],
    "given_values": {"beam_length": "5 m", "load": "100 N"},
    "student_intent": "solve",
    "is_in_scope": True
}

test_student_model = {
    "mastered": [],
    "struggling": [],
    "confidence_level": "unknown"
}

test_plan = {"action": "SOLVE", "reason": "Student wants to solve"}

# ============= AGENT TESTS =============
def test_input_parser():
    print("\n=== INPUT PARSER ===")
    result = agent.input_parser(test_message, [])
    print(json.dumps(result, indent=2))

def test_student_modeler():
    print("\n=== STUDENT MODELER ===")
    result = agent.student_modeler(test_parsed_input, test_student_model, [])
    print(json.dumps(result, indent=2))

def test_pedagogical_planner():
    print("\n=== PEDAGOGICAL PLANNER ===")
    result = agent.pedagogical_planner(test_parsed_input, test_student_model, [])
    print(json.dumps(result, indent=2))

def test_solver():
    print("\n=== SOLVER ===")
    result = agent.solver(test_parsed_input)
    print(json.dumps(result, indent=2))
    return result

def test_validator():
    print("\n=== VALIDATOR ===")
    solution = agent.solver(test_parsed_input)
    result = agent.validator(test_parsed_input, solution)
    print(json.dumps(result, indent=2))

def test_visualizer():
    print("\n=== VISUALIZER ===")
    solution = agent.solver(test_parsed_input)
    validation = agent.validator(test_parsed_input, solution)
    result = agent.visualizer(test_parsed_input, validation)
    print(json.dumps(result, indent=2))

def test_conversationalist():
    print("\n=== CONVERSATIONALIST ===")
    result = agent.conversationalist(
        student_message=test_message,
        parsed_input=test_parsed_input,
        student_model=test_student_model,
        plan=test_plan,
        solution=None,
        validation=None,
        visualization=None
    )
    print(result)

def test_diagram_renderer():
    print("\n=== DIAGRAM RENDERER ===")
    solution = agent.solver(test_parsed_input)
    validation = agent.validator(test_parsed_input, solution)
    visualization = agent.visualizer(test_parsed_input, validation)
    diagram_b64 = agent.diagram_renderer(visualization, solution)

    if not diagram_b64:
        print("❌ Failed to generate diagram")
        return

    import base64
    with open("test_diagram.png", "wb") as f:
        f.write(base64.b64decode(diagram_b64))
    print(f"✅ Saved to test_diagram.png ({len(diagram_b64)} chars base64)")
# ============= RUN =============
tests = {
    "parser": test_input_parser,
    "modeler": test_student_modeler,
    "planner": test_pedagogical_planner,
    "solver": test_solver,
    "validator": test_validator,
    "visualizer": test_visualizer,
    "conversationalist": test_conversationalist,
    "diagram": test_diagram_renderer,
}

if __name__ == "__main__":
    if len(sys.argv) > 1:
        agent_name = sys.argv[1]
        if agent_name in tests:
            tests[agent_name]()
        else:
            print(f"Unknown agent. Choose from: {list(tests.keys())}")
    else:
        # Run all
        for name, test_fn in tests.items():
            test_fn()