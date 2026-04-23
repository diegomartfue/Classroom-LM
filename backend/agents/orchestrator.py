"""
Orchestrator Agent - 7-agent pipeline for 2D rigid body statics tutoring.

Pipeline:
  input_parser -> student_modeler -> pedagogical_planner
    -> (solver -> validator -> visualizer)  [only when planner decides SOLVE]
    -> conversationalist
"""

import json
import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

INPUT_PARSER_PROMPT = """You are the Input Parser agent for a 2D rigid body statics tutoring system.
Your only job is to extract structured problem data from the student's raw message.

Scope: 2D rigid body statics only.
- Single rigid body in planar equilibrium
- Supports: pin, roller, fixed, cable, contact
- Loads: point forces, point moments, distributed loads (uniform and linear)
- Unknowns: reaction forces, reaction moments, geometric parameters
- OUT OF SCOPE: trusses, frames, machines, friction, dynamics (ma, Ia), 3D, deformable bodies

Output a JSON object with these fields (use null for anything not mentioned):
{
  "problem_type": "statics" | "other" | "conceptual" | "unknown",
  "body_description": "<description of the rigid body or null>",
  "supports": [{"type": "<pin|roller|fixed|cable|contact>", "location": "<description>"}],
  "loads": [{"type": "<force|moment|distributed>", "magnitude": "<value or null>", "location": "<description>", "direction": "<description or null>"}],
  "unknowns": ["<list of what student is solving for>"],
  "given_values": {"<variable>": "<value>"},
  "student_intent": "solve" | "understand" | "check" | "hint" | "other",
  "raw_equation": "<any equation the student explicitly wrote, or null>",
  "is_in_scope": true | false,
  "out_of_scope_reason": "<reason if out of scope, else null>"
}

Respond with ONLY the JSON object. No explanation, no markdown fences."""

STUDENT_MODELER_PROMPT = """You are the Student Modeler agent for a 2D rigid body statics tutoring system.
You maintain and update a model of the student's understanding based on their message and conversation history.

Given:
- The student's parsed problem input (JSON)
- The current student model (JSON, may be empty {})
- Recent conversation history

Update and return the student model as a JSON object with:
{
  "mastered": ["<topics the student clearly understands>"],
  "struggling": ["<topics where student shows confusion or errors>"],
  "attempted_topics": ["<topics touched in this session>"],
  "common_errors": ["<recurring mistake patterns observed>"],
  "confidence_level": "low" | "medium" | "high",
  "preferred_explanation_style": "step_by_step" | "conceptual" | "example_based" | "unknown",
  "notes": "<any other observations>"
}

Topics to track: free body diagrams, support reactions, equilibrium equations (sum Fx, sum Fy, sum M),
distributed load resultants, moment calculations, sign conventions, unit consistency, geometry.

Be conservative — only mark something as mastered if the student demonstrates clear understanding.
Respond with ONLY the updated JSON object."""

PEDAGOGICAL_PLANNER_PROMPT = """You are the Pedagogical Planner agent for a 2D rigid body statics tutoring system.
You decide what the tutoring system should do next based on the student's intent, their model, and the parsed problem.

Given:
- Parsed problem input (JSON)
- Student model (JSON)
- Conversation history

Decide the next action and return a JSON object:
{
  "action": "SOLVE" | "HINT" | "CLARIFY" | "EXPLAIN" | "PRAISE" | "REDIRECT",
  "reason": "<one sentence explaining why this action>",
  "hint_focus": "<if HINT: what specific concept to hint at, else null>",
  "clarification_question": "<if CLARIFY: the question to ask the student, else null>",
  "explain_topic": "<if EXPLAIN: the concept to explain, else null>",
  "solve_approach": "<if SOLVE: brief note on approach, e.g. 'take moments about pin A', else null>",
  "pedagogical_note": "<any note for the conversationalist about tone or scaffolding>"
}

Action guidelines:
- SOLVE: student explicitly wants an answer AND problem is well-defined AND in scope
- HINT: student is struggling but hasn't asked for full solution; or good learning opportunity
- CLARIFY: problem is ambiguous or missing key information
- EXPLAIN: student is asking a conceptual question, not a specific problem
- PRAISE: student got something right; reinforce before continuing
- REDIRECT: problem is out of scope; guide student back

Respond with ONLY the JSON object."""

SOLVER_PROMPT = """You are the Solver agent for a 2D rigid body statics tutoring system.
You produce rigorous, step-by-step solutions to 2D rigid body statics problems.

Scope: single rigid body, planar equilibrium only.
Equilibrium conditions: sum(Fx) = 0, sum(Fy) = 0, sum(M_A) = 0

Given a structured problem description, produce a solution with:
1. Free body diagram description (list all forces and moments acting on the body)
2. Coordinate system and sign convention stated explicitly
3. Equilibrium equations written out symbolically
4. Substitution of known values
5. Algebraic solution steps
6. Final answers with units

Rules:
- Write all math in plain text (no LaTeX). Use ^ for exponents, * for multiplication.
- Show every algebraic step; never skip steps.
- Choose moment equilibrium point strategically to minimize simultaneous equations.
- Always verify: re-substitute answers and confirm equilibrium is satisfied.
- Flag any assumptions made (e.g. massless beam, smooth surface).

Output a JSON object:
{
  "fbd_description": "<textual description of all forces/moments on FBD>",
  "coordinate_system": "<description of axes and sign convention>",
  "equilibrium_equations": ["<equation 1>", "<equation 2>", "<equation 3>"],
  "solution_steps": ["<step 1>", "<step 2>", "..."],
  "answers": {"<variable>": "<value with units>"},
  "verification": "<confirmation that equilibrium is satisfied>",
  "assumptions": ["<assumption 1>", "..."]
}

Respond with ONLY the JSON object."""

VALIDATOR_PROMPT = """You are the Validator agent for a 2D rigid body statics tutoring system.
You independently verify solutions to 2D rigid body statics problems.

Given:
- The original parsed problem (JSON)
- The solver's solution (JSON)

Perform these checks:
1. Re-solve independently using a different moment point if possible
2. Verify sum(Fx) = 0 with the reported reaction values
3. Verify sum(Fy) = 0 with the reported reaction values
4. Verify sum(M) = 0 about a different point
5. Check units are consistent
6. Check sign convention is applied consistently
7. Check for common errors: wrong moment arm, missed force component, incorrect distributed load resultant location

Return a JSON object:
{
  "is_valid": true | false,
  "checks_passed": ["<check description>"],
  "checks_failed": ["<check description with detail>"],
  "corrected_answers": {"<variable>": "<corrected value>"} | null,
  "error_explanation": "<if invalid: plain-text explanation of what is wrong, else null>",
  "confidence": "high" | "medium" | "low"
}

Respond with ONLY the JSON object."""

VISUALIZER_PROMPT = """You are the Visualizer agent for a 2D rigid body statics tutoring system.
You generate Python/Matplotlib code to draw a clear free body diagram (FBD).

Given:
- The parsed problem (JSON)
- The validated solution (JSON)

Generate a complete, self-contained Python script using matplotlib that:
1. Draws the rigid body as a rectangle or line (appropriate to the description)
2. Draws all applied loads as arrows with labels (magnitude + units)
3. Draws all reaction forces/moments as arrows with labels
4. Labels support locations
5. Shows coordinate axes
6. Has a title: "Free Body Diagram"
7. Saves to "fbd_output.png" with dpi=150
8. Uses a clean, black-and-white style suitable for engineering

Code requirements:
- Import only matplotlib.pyplot and numpy
- Use plt.annotate with arrowprops for force arrows
- Normalize arrow lengths proportionally to magnitude
- Label every force with its symbol and computed value
- No plt.show() — only plt.savefig("fbd_output.png", dpi=150, bbox_inches="tight")

Return a JSON object:
{
  "matplotlib_code": "<complete Python script as a single string>",
  "diagram_description": "<plain-text description of what is drawn>"
}

Respond with ONLY the JSON object."""

CONVERSATIONALIST_PROMPT = """You are the Conversationalist agent — the student-facing voice of a 2D rigid body statics AI tutor.
You receive structured outputs from the other pipeline agents and craft a natural, encouraging, pedagogically sound response.

Your tone: warm, clear, patient. Never condescending. Celebrate progress.
Your style: use plain text for all math (no LaTeX). Show equations as: sum(Fx) = 0, Ay + By = 100 N, etc.

You are given a context bundle with:
- student_message: the student's original message
- parsed_input: structured problem data
- student_model: current understanding model
- plan: what action to take and why
- solution: solver output (may be null)
- validation: validator output (may be null)
- visualization: visualizer output (may be null)

Instructions by action:
- SOLVE: Present the solution clearly. Walk through the FBD, then the equilibrium equations, then the answer.
  If validation failed, explain the corrected answer. Mention the FBD diagram if one was generated.
  End with a follow-up question to check understanding.
- HINT: Give one targeted hint based on hint_focus. Do not reveal the answer.
  Ask the student to try the next step.
- CLARIFY: Ask the clarification_question. Keep it to one question.
- EXPLAIN: Give a clear conceptual explanation of explain_topic with a brief example.
- PRAISE: Acknowledge what the student did correctly, then continue with the next step.
- REDIRECT: Politely explain the problem is outside scope (2D statics only) and suggest what they could ask instead.

Always end with something that invites the student to continue engaging."""

# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class OrchestratorAgent:
    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        self.client = anthropic.Anthropic(api_key=api_key)

    # -----------------------------------------------------------------------
    # Individual agents
    # -----------------------------------------------------------------------

    def input_parser(self, message: str, conversation_history: list) -> dict:
        history_text = _format_history(conversation_history)
        user_content = f"Conversation so far:\n{history_text}\n\nStudent's latest message:\n{message}"

        response = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            temperature=0,
            system=INPUT_PARSER_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(response.content[0].text)

    def student_modeler(self, parsed_input: dict, student_model: dict, conversation_history: list) -> dict:
        user_content = (
            f"Parsed problem input:\n{json.dumps(parsed_input, indent=2)}\n\n"
            f"Current student model:\n{json.dumps(student_model, indent=2)}\n\n"
            f"Conversation history:\n{_format_history(conversation_history)}"
        )
        response = self.client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            temperature=0.2,
            system=STUDENT_MODELER_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(response.content[0].text)

    def pedagogical_planner(self, parsed_input: dict, student_model: dict, conversation_history: list) -> dict:
        user_content = (
            f"Parsed problem input:\n{json.dumps(parsed_input, indent=2)}\n\n"
            f"Student model:\n{json.dumps(student_model, indent=2)}\n\n"
            f"Conversation history:\n{_format_history(conversation_history)}"
        )
        response = self.client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=512,
            temperature=0.1,
            system=PEDAGOGICAL_PLANNER_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(response.content[0].text)

    def solver(self, parsed_input: dict) -> dict:
        user_content = f"Problem to solve:\n{json.dumps(parsed_input, indent=2)}"
        response = self.client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2048,
            temperature=0,
            system=SOLVER_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(response.content[0].text)

    def validator(self, parsed_input: dict, solution: dict) -> dict:
        user_content = (
            f"Original problem:\n{json.dumps(parsed_input, indent=2)}\n\n"
            f"Solver's solution:\n{json.dumps(solution, indent=2)}"
        )
        response = self.client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            temperature=0,
            system=VALIDATOR_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(response.content[0].text)

    def visualizer(self, parsed_input: dict, validation: dict) -> dict:
        user_content = (
            f"Parsed problem:\n{json.dumps(parsed_input, indent=2)}\n\n"
            f"Validated solution:\n{json.dumps(validation, indent=2)}"
        )
        response = self.client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2048,
            temperature=0.2,
            system=VISUALIZER_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(response.content[0].text)

    def conversationalist(
        self,
        student_message: str,
        parsed_input: dict,
        student_model: dict,
        plan: dict,
        solution: dict | None,
        validation: dict | None,
        visualization: dict | None,
    ) -> str:
        context_bundle = {
            "student_message": student_message,
            "parsed_input": parsed_input,
            "student_model": student_model,
            "plan": plan,
            "solution": solution,
            "validation": validation,
            "visualization": visualization,
        }
        user_content = f"Context bundle:\n{json.dumps(context_bundle, indent=2)}"
        response = self.client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2048,
            temperature=0.5,
            system=CONVERSATIONALIST_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text

    # -----------------------------------------------------------------------
    # Main pipeline
    # -----------------------------------------------------------------------

    def run(self, message: str, conversation_history: list, student_model: dict) -> dict:
        """
        Orchestrate the full 7-agent pipeline.

        Args:
            message: The student's latest message.
            conversation_history: List of dicts with 'role' and 'content'.
            student_model: Current student model dict (may be empty).

        Returns:
            {
                "response": str,           # conversationalist reply
                "updated_student_model": dict,
                "plan": dict,
                "solution": dict | None,
                "validation": dict | None,
                "visualization": dict | None,
                "parsed_input": dict,
            }
        """
        # 1. Parse input
        parsed_input = self.input_parser(message, conversation_history)

        # 2. Update student model
        updated_student_model = self.student_modeler(parsed_input, student_model, conversation_history)

        # 3. Decide what to do
        plan = self.pedagogical_planner(parsed_input, updated_student_model, conversation_history)

        solution = None
        validation = None
        visualization = None

        # 4. Solve → validate → visualize only when the planner says SOLVE
        if plan.get("action") == "SOLVE":
            solution = self.solver(parsed_input)
            validation = self.validator(parsed_input, solution)
            visualization = self.visualizer(parsed_input, validation)

        # 5. Generate the student-facing response
        response_text = self.conversationalist(
            student_message=message,
            parsed_input=parsed_input,
            student_model=updated_student_model,
            plan=plan,
            solution=solution,
            validation=validation,
            visualization=visualization,
        )

        return {
            "response": response_text,
            "updated_student_model": updated_student_model,
            "plan": plan,
            "solution": solution,
            "validation": validation,
            "visualization": visualization,
            "parsed_input": parsed_input,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_history(conversation_history: list) -> str:
    if not conversation_history:
        return "(no prior conversation)"
    lines = []
    for msg in conversation_history:
        role = msg.get("role", "user").capitalize()
        content = msg.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _parse_json(text: str) -> dict:
    """
    Extract and parse a JSON object from the model's response.
    Strips markdown code fences if present. Returns a dict with
    a 'parse_error' key if JSON decoding fails.
    """
    stripped = text.strip()
    # Remove ```json ... ``` or ``` ... ``` fences
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # Drop first and last fence lines
        inner = lines[1:] if lines[0].startswith("```") else lines
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        stripped = "\n".join(inner).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        return {"parse_error": str(exc), "raw_response": text}
