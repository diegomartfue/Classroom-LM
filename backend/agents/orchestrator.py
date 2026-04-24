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
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import io
import base64
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
- SOLVE: choose this if ANY of the following are true:
  * Student uses words like "solve", "find", "calculate", "give me the solution", "full solution", "complete solution", "show me", "draw the free body diagram", "FBD"
  * Student explicitly asks for the answer
  * Student's intent is "solve" in the parsed input
  * Problem is well-defined with known supports, loads, and clear unknowns
- HINT: ONLY if student is clearly struggling AND has NOT asked for a full solution
- CLARIFY: problem is ambiguous or missing key information
- EXPLAIN: student is asking a conceptual question with no specific problem
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
You extract and structure the visual elements of a free body diagram (FBD) from a solved problem.

Given:
- The parsed problem (JSON)
- The validated solution (JSON)

Return a JSON object with exactly two fields:

{
  "description": "<plain-text description of the complete FBD: body shape, all forces, all moments, supports, and coordinate axes>",
  "elements": [
    {
      "type": "force" | "moment" | "support" | "body" | "axis",
      "label": "<symbol or name, e.g. 'Ax', 'P', 'w'>",
      "magnitude": "<numeric value with units, or null if unknown>",
      "direction": "<e.g. 'up', 'down', 'left', 'right', '+x', '-y', 'clockwise', 'counterclockwise', or angle in degrees>",
      "location": "<description of where on the body this element acts, e.g. 'pin A at left end', 'midspan'>",
      "is_known": true | false
    }
  ]
}

Include one element entry for every:
- Applied force (known or unknown magnitude)
- Applied moment
- Reaction force component (x and y separately)
- Reaction moment
- Support (pin, roller, fixed, cable, contact)
- The rigid body itself (type "body")
- Coordinate axes (type "axis", one entry)

Respond with ONLY the JSON object."""

DIAGRAM_RENDERER_PROMPT = """You are the Diagram Renderer agent for a 2D rigid body statics tutoring system.
Your job is to generate Python matplotlib code that renders a free body diagram based on the visualizer's structured output.

You will receive:
- The visualizer agent's output (JSON describing FBD elements)
- The solver's solution (for reference values)

You must output ONLY executable Python code — no explanation, no markdown fences, just raw Python.

Your code MUST follow these STRICT drawing rules:

COORDINATE SETUP:
- Place the beam horizontally. Its left end is at x=0, right end at x=beam_length (parse from body element).
- Beam sits at y=0.
- Use ax.set_xlim(-2, beam_length + 2) and ax.set_ylim(-3, 3).

BEAM/BODY:
- Draw as a thick horizontal line from (0,0) to (beam_length, 0) with navy color #041E42, linewidth=8.

PIN SUPPORT:
- Located at the beam's left end (x=0, y=0).
- Draw a triangle BELOW the beam: vertices at (0, 0), (-0.3, -0.6), (0.3, -0.6).
- Add hatching marks below the triangle base.
- Label "A" BELOW the hatching.

ROLLER SUPPORT:
- Located at the beam's right end.
- Draw a triangle BELOW the beam with a small circle at the bottom.
- Label "B" BELOW it.

REACTION FORCES (the ones computed by the solver, e.g. Ay, By, Ax):
- Arrows ORIGINATE at the support point and POINT IN THE DIRECTION given.
- If direction is "up" or "+y": arrow goes from support point (x, 0) upward to (x, 0.8).
- If direction is "down" or "-y": arrow goes from (x, 0) downward to (x, -0.8).
- If direction is "right" or "+x": arrow from (x, 0) to (x+0.8, 0).
- If direction is "left" or "-x": arrow from (x, 0) to (x-0.8, 0).
- If magnitude is "0 N" or 0: DO NOT draw the arrow. Just write a small text "Ax = 0" near the support.
- Place the label at the arrow's TIP, offset slightly.

APPLIED LOADS (like P, external forces on the body):
- Arrow ENDS at the point of application on the beam.
- If direction is "down": arrow from (x, 1.2) downward to (x, 0.05). Label "P = 100 N" ABOVE the arrow tail.

AXES:
- Draw in lower-left corner at (-1.5, -2): small x-axis (arrow to right, labeled "x") and y-axis (arrow up, labeled "y").

COLORS:
- Beam: navy #041E42
- All forces (applied AND reactions): orange #FF8200, linewidth=2
- Support symbols and labels: black #0a0a0a
- Axes: gray #555555

Use matplotlib's ax.annotate() with arrowstyle="-|>" for all arrows.

Required ending of your code:
buf = io.BytesIO()
fig.savefig(buf, format='png', bbox_inches='tight', dpi=120, facecolor='white')
plt.close(fig)
buf.seek(0)
result = base64.b64encode(buf.read()).decode('utf-8')"""


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
        
    def diagram_renderer(self, visualizer_output: dict, solution: dict) -> str:
        """
        Generates matplotlib code from visualizer output and executes it.
        Returns a base64-encoded PNG string, or empty string on failure.
        """
        user_content = (
            f"Visualizer output:\n{json.dumps(visualizer_output, indent=2)}\n\n"
            f"Solver solution (for reference):\n{json.dumps(solution, indent=2)}"
        )
        response = self.client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=3000,
            temperature=0,
            system=DIAGRAM_RENDERER_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        code = response.content[0].text.strip()

        # Strip markdown fences if Claude adds them anyway
        if code.startswith("```"):
            lines = code.splitlines()
            code = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        # Execute the generated code in a sandboxed namespace
        try:
            namespace = {}
            exec(code, namespace)
            return namespace.get("result", "")
        except Exception as e:
            print(f"Diagram renderer error: {e}")
            return ""

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
            diagram_image = self.diagram_renderer(visualization, solution)

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
            "diagram_image": diagram_image if plan.get("action") == "SOLVE" else "",
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
