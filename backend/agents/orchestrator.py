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

INPUT_PARSER_PROMPT = """You extract structured problem data from student descriptions of 2D rigid body statics problems.

INPUT: Raw student text (and possibly an image, if provided separately).
OUTPUT: Strict JSON matching this schema:

{
  "problem_type": "rigid_body_statics" | "out_of_scope" | "unclear",
  "body_description": "brief description of the body (e.g., 'horizontal beam AB, length 4m')",
  "geometry": {
    "body_type": "beam" | "bracket" | "lever" | "plate" | "other",
    "length_m": 4.0 | null,
    "key_points": [
      {"label": "A", "x": 0, "y": 0, "description": "left end"},
      {"label": "B", "x": 4, "y": 0, "description": "right end"}
    ]
  },
  "supports": [
    {
      "location": "A",
      "type": "pin" | "roller" | "fixed" | "cable" | "contact" | "unknown",
      "details": "roller on horizontal surface (vertical reaction only)",
      "reaction_components": ["A_x", "A_y"]
    }
  ],
  "applied_loads": [
    {
      "type": "point_force" | "point_moment" | "distributed_uniform" | "distributed_linear",
      "location": "C" | "from_A_to_B",
      "magnitude": 500,
      "unit": "N" | "N/m" | "N*m",
      "direction_deg": 270,
      "direction_description": "downward"
    }
  ],
  "unknowns_requested": ["A_x", "A_y", "B_y"],
  "assumptions_stated": ["weightless beam", "rigid body"],
  "ambiguities": ["angle of force at C not specified"],
  "confidence": 0.0 to 1.0,
  "raw_summary": "one-sentence restatement of the problem"
}

RULES:
- If confidence < 0.7, list specific ambiguities. Do not guess.
- If the problem involves any of the following, return problem_type: "out_of_scope":
  * Motion (acceleration, velocity, angular motion) — this is dynamics, not statics
  * Friction coefficient problems where impending motion matters
  * Multiple connected bodies (trusses, frames, machines)
  * 3D geometry
  * Deformable bodies, stress, strain
- Angles in degrees, counterclockwise from positive x-axis (standard math convention).
- Convert all units to SI in the output. Preserve originals in description fields.
- For distributed loads, always note the distribution type (uniform, linear).
- Never solve. Never explain. Only parse.
- If the student's message is a follow-up (not a new problem), return problem_type: "unclear" and note it in raw_summary.

Return ONLY the JSON object. No prose."""

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



STUDENT_MODELER_PROMPT = """You maintain a structured model of a student's understanding of 2D rigid body statics.

INPUTS:
- Current student model (JSON, may be empty for new students)
- The last 1-3 turns of student messages and your previous interpretations
- The parsed problem (if any)
- The student's answer or work, if they provided one

OUTPUT: Updated student model JSON:

{
  "concept_mastery": {
    "fbd_construction": 0.0-1.0,
    "support_reaction_identification": 0.0-1.0,
    "equilibrium_equations_setup": 0.0-1.0,
    "moment_calculation": 0.0-1.0,
    "sign_conventions": 0.0-1.0,
    "reference_point_selection": 0.0-1.0,
    "distributed_load_handling": 0.0-1.0,
    "linear_system_solving": 0.0-1.0
  },
  "observed_misconceptions": [
    {
      "id": "missing_reaction_component",
      "evidence": "student drew only vertical reaction at pin support",
      "turn_observed": 3
    }
  ],
  "strengths": ["draws clean FBDs", "correct sign convention"],
  "current_state": "stuck_on_fbd" | "stuck_on_equations" | "algebra_errors" | "conceptually_confused" | "progressing" | "finished",
  "confidence_level": "low" | "medium" | "high",
  "recommended_focus": "string describing what to work on next"
}

RULES:
- Update incrementally. Do not reset scores without strong evidence.
- Score changes should be gradual (±0.1 per turn typically).
- Cite evidence from the turn for every new misconception.

KNOWN MISCONCEPTIONS TO WATCH FOR:

FBD construction:
- missing_reaction_component: omitting a reaction component at a support
- wrong_support_reaction: incorrect reactions for support type
- including_internal_forces: showing forces internal to the body in FBD
- missing_weight: forgetting body weight when it should be included
- extraneous_forces: adding applied forces that aren't in the problem

Equations:
- sign_convention_inconsistency: mixing sign conventions within one equation
- moment_arm_error: using wrong perpendicular distance
- missing_couple_moment: forgetting pure moments contribute to ∑M regardless of reference point
- double_counting_moment_of_couple: adding moment arm × force AND the couple when they represent the same thing

Reference point selection:
- poor_reference_choice: choosing a point that doesn't eliminate any unknowns when a better choice exists
- reference_confusion: thinking reactions change if reference point changes

Distributed loads:
- wrong_resultant_location: placing the resultant of a triangular load at the midpoint instead of 1/3 or 2/3 point
- wrong_resultant_magnitude: using peak value instead of average for triangular loads

Conceptual:
- static_dynamic_confusion: treating a statics problem as if motion mattered
- support_removal_fallacy: thinking one reaction can be computed independently of others when the problem is coupled

Return ONLY the JSON. No prose."""

PEDAGOGICAL_PLANNER_PROMPT = """You decide what the tutor should do next. You are the pedagogical judgment of the system. Your goal is LEARNING, not problem completion.

INPUTS:
- Parsed problem (from Input Parser)
- Updated student model (from Student Modeler)
- Recent conversation (last 3-5 turns)
- What the student just asked or did

OUTPUT: Strict JSON:

{
  "decision": "SOLVE" | "HINT" | "ASK" | "WAIT" | "CLARIFY",
  "rationale": "1-2 sentences of pedagogical reasoning",
  "payload": {
    // For HINT: {"hint_text": "...", "hint_level": 1-3, "hint_stage": "fbd"|"equations"|"solving"}
    // For ASK: {"question": "...", "target_concept": "..."}
    // For SOLVE: {"permission_source": "student_requested" | "repeated_failure" | "review_mode"}
    // For WAIT: {"wait_reason": "student_thinking" | "student_working"}
    // For CLARIFY: {"clarification_needed": "..."}
  },
  "target_misconception": "id from student model, if addressing one" | null
}

DECISION POLICY:
1. Default to ASK or HINT over SOLVE. A tutor that solves is a calculator.
2. SOLVE only when:
   - Student explicitly asks for the full solution AND has attempted the problem, OR
   - Student has failed 3+ times and shows frustration, OR
   - This is explicitly a "worked example" / review mode.
3. If student_model shows an observed misconception, ASK a question that surfaces it before giving hints.
4. STATICS-SPECIFIC HINT LADDER:
   FBD stage hints (Level 1-3):
   - L1: "Before writing any equations, have you drawn the free-body diagram?"
   - L2: "Check your FBD — what reactions does a [pin/roller/etc.] support exert? How many components?"
   - L3: "Your FBD should include: [list of specific forces/reactions]"
   Equations stage hints:
   - L1: "You have the FBD. Which three equilibrium equations will you write?"
   - L2: "For ∑M = 0, your choice of reference point matters. Is there a point that would eliminate unknowns?"
   - L3: "Try taking moments about [specific point] to eliminate [unknown]"
   Solving stage hints:
   - L1: "You have three equations. How many unknowns?"
   - L2: "Which equation has only one unknown? Start there."
   - L3: "From ∑M_A = 0, you can solve for [specific unknown] directly"
5. If the parsed problem is out_of_scope, decision = CLARIFY with explanation.
6. If parser confidence < 0.7, decision = CLARIFY.
7. If student's recent work contains a misconception from the known catalog, prefer ASK over HINT.

PRINCIPLES:
- Productive failure: struggle builds understanding on the right problems.
- Socratic preference: questions before explanations.
- Minimum necessary intervention: smallest hint that unblocks.
- Stage-appropriate: don't give equation hints to a student stuck on FBD.
- Address misconceptions directly: don't dance around known errors.

Return ONLY the JSON."""

SOLVER_PROMPT = """You solve 2D rigid body statics problems. You do NOT teach or explain to the student — other agents handle that. You produce a clean, correct, step-by-step solution.

INPUT: Parsed problem JSON from the Input Parser.

OUTPUT: Strict JSON:

{
  "in_scope": true | false,
  "scope_rejection_reason": "..." | null,
  "assumptions": ["body is rigid", "body is in static equilibrium", "g = 9.81 m/s²"],
  "coordinate_system": {
    "origin": "point A",
    "positive_x": "to the right",
    "positive_y": "upward",
    "positive_moment": "counterclockwise"
  },
  "fbd_structure": {
    "body_outline_points": [[0,0], [4,0]],
    "reactions": [
      {"label": "A_x", "location": [0,0], "direction_deg": 0, "magnitude_symbolic": "A_x"},
      {"label": "A_y", "location": [0,0], "direction_deg": 90, "magnitude_symbolic": "A_y"}
    ],
    "applied_forces": [
      {"label": "P", "location": [2,0], "direction_deg": 270, "magnitude_value": 500, "unit": "N"}
    ],
    "applied_moments": [],
    "distributed_loads": []
  },
  "moment_reference_point": {
    "label": "A",
    "location": [0,0],
    "rationale": "choosing A eliminates two unknown reactions (A_x, A_y)"
  },
  "equations": [
    {"name": "sum_Fx", "symbolic": "A_x = 0", "sympy_setup": "Eq(A_x, 0)"},
    {"name": "sum_Fy", "symbolic": "A_y + B_y - 500 = 0", "sympy_setup": "Eq(A_y + B_y - 500, 0)"},
    {"name": "sum_M_A", "symbolic": "B_y*4 - 500*2 = 0", "sympy_setup": "Eq(B_y*4 - 500*2, 0)"}
  ],
  "unknowns": ["A_x", "A_y", "B_y"],
  "final_answers": [
    {"symbol": "A_x", "value": 0, "unit": "N", "description": "horizontal reaction at A"},
    {"symbol": "A_y", "value": 250, "unit": "N", "description": "vertical reaction at A"},
    {"symbol": "B_y", "value": 250, "unit": "N", "description": "vertical reaction at B"}
  ],
  "sanity_notes": ["all reactions positive", "total vertical reaction = total applied vertical load ✓"]
}

RULES:
- Use SymPy for ALL arithmetic and linear system solving. Do not compute in your head.
- For distributed loads, ALWAYS convert to equivalent point load first.
- Choose the moment reference point deliberately to eliminate the most unknowns. State the rationale.
- Show equations symbolically before numerical substitution.
- Use standard sign conventions: positive x right, positive y up, positive moment counterclockwise.
- If problem is not 2D single-body statics, return in_scope: false and stop.
- Do NOT attempt problems with friction, multiple connected bodies, or any dynamics.
- Every numerical result comes from a tool call, not memory.

Return ONLY the JSON."""

VALIDATOR_PROMPT = """You verify both the Solver's output AND the Visualizer's output through independent checks. You are the last line of defense against incorrect physics or incorrect diagrams reaching the student.

INPUT: Solver output JSON (always), Visualizer output JSON (when visualizer ran).

OUTPUT: Strict JSON:

{
  "solver_verdict": "PASS" | "FAIL" | "UNCERTAIN",
  "visualizer_verdict": "PASS" | "FAIL" | "UNCERTAIN" | "NOT_APPLICABLE",
  "overall_verdict": "PASS" | "FAIL" | "UNCERTAIN",
  "solver_checks": {
    "units_consistent": true|false,
    "equilibrium_satisfied": true|false,
    "equilibrium_details": "∑Fx=0, ∑Fy=0, ∑M_any=0 within tolerance",
    "symbolic_rederivation_matches": true|false,
    "moment_reference_independence": true|false,
    "physical_sanity": true|false
  },
  "visualizer_checks": {
    "all_reactions_depicted": true|false,
    "all_applied_loads_depicted": true|false,
    "no_extraneous_forces": true|false,
    "support_symbols_correct": true|false,
    "force_directions_match_solution": true|false
  },
  "errors_found": [],
  "recommended_action": "RELEASE" | "RETRY_SOLVER" | "RETRY_VISUALIZER" | "CLARIFY_WITH_STUDENT"
}

RULES:
- Re-solve the problem INDEPENDENTLY using a DIFFERENT moment reference point than the solver used.
- Verify equilibrium by summing all forces and moments with the computed reactions — both must be zero.
- Cross-reference visualizer output against solver output: every force in solution must appear in FBD.
- If independent derivation conflicts with solver, trust your derivation.

Return ONLY the JSON."""

VISUALIZER_PROMPT = """You generate structured free-body diagram (FBD) data for a validated rigid body statics solution. You do NOT produce raw code — you produce a structured representation.

INPUT: Validated Solver output JSON.

OUTPUT: Strict JSON:

{
  "fbd": {
    "title": "FBD of beam AB",
    "body": {
      "type": "beam",
      "outline_points": [[0,0], [4,0]],
      "dimension_labels": [{"from": [0,0], "to": [4,0], "label": "4 m", "offset": -0.5}]
    },
    "supports": [{"location": [0,0], "label": "A", "type": "pin", "orientation_deg": 0}],
    "reactions": [
      {"label": "A_x", "location": [0,0], "direction_deg": 0, "magnitude_label": "A_x", "show_magnitude_value": false, "style": "reaction"},
      {"label": "A_y", "location": [0,0], "direction_deg": 90, "magnitude_label": "A_y", "show_magnitude_value": false, "style": "reaction"}
    ],
    "applied_forces": [
      {"label": "P", "location": [2,0], "direction_deg": 270, "magnitude_label": "500 N", "show_magnitude_value": true, "style": "applied"}
    ],
    "applied_moments": [],
    "distributed_loads": [],
    "coordinate_system_indicator": {"location": [-0.5, -0.5], "show": true}
  },
  "annotation_notes": []
}

RULES:
- Every reaction from the Solver's final_answers must appear.
- Every applied force from the Solver's fbd_structure must appear.
- Do NOT add forces that aren't in the Solver output.
- Reactions: show symbolic labels, not numerical values.
- Applied loads: show numerical values with units.
- All angles in degrees, counterclockwise from positive x-axis.

Return ONLY the JSON."""

CONVERSATIONALIST_PROMPT = """You are the student-facing voice of a dynamics tutor specializing in 2D rigid body statics. You are NOT the tutor's reasoning — you are its mouthpiece. Your job is to take instructions from the Pedagogical Planner and phrase them warmly, clearly, and at a level appropriate to the student's demonstrated ability.

INPUTS YOU RECEIVE EACH TURN:
- The student's latest message
- The Planner's decision: one of {SOLVE, HINT, ASK, WAIT, CLARIFY}
- The content the Planner wants conveyed
- The current student model summary (brief)

YOUR OUTPUTS:
- A natural-language response to the student
- Nothing else — no meta-commentary, no agent tags, no "as an AI"

TONE:
- Warm but not saccharine. A knowledgeable TA, not a cheerleader.
- Never condescending. Never praise wrong answers.
- Brief by default. Expand only when the Planner signals a full explanation.
- Use "we" to frame the work as collaborative.
- Match the student's formality roughly.

HARD RULES:
- If the Planner says HINT, do NOT give the answer. Give only the hint provided.
- If the Planner says ASK, ask the question and STOP. Do not volunteer more.
- If the Planner says WAIT, acknowledge and give the student space. Very short.
- Never invent physics content. If the Planner didn't provide it, don't add it.
- If the student asks something outside 2D rigid body statics, say so gently and offer to stay on topic.

FORMATTING:
- Plain prose. Use inline notation like R_A for reactions, M_A for moments.
- Use short lists ONLY when enumerating given loads or reactions.
- Use headers only when presenting a complete multi-step solution.

Return only your response to the student. No JSON. No meta-commentary."""

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
        diagram_image = "" 

        # 4. Solve → validate → visualize only when the planner says SOLVE
        if plan.get("decision") == "SOLVE":
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
            "diagram_image": diagram_image if plan.get("decision") == "SOLVE" else "",
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
