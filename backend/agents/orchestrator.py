"""
Orchestrator Agent - 7-agent pipeline for 2D rigid body statics tutoring.

Pipeline:
  input_parser -> student_modeler -> pedagogical_planner
    -> (solver -> validator -> visualizer)  [only when planner decides SOLVE]
    -> conversationalist
"""

#uvicorn main:app --reload
#npm run dev

import json
import os
import anthropic
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import io
import base64
from .fbd_renderer import render_fbd, render_schematic, stack_images_vertical
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

INPUT_PARSER_PROMPT = """You extract structured problem data from student descriptions of 2D dynamics problems (particles and rigid bodies).

INPUT: Raw student text (and possibly an image, if provided separately).
OUTPUT: Strict JSON matching this schema:

{
  "problem_type": "dynamics" | "out_of_scope" | "unclear",
  "family": "kinetics" | "kinematics" | "energy_momentum" | "unclear",
  "body_description": "brief description (e.g., '12 kg block on a 25-degree frictionless incline')",
  "scenario": {
    "bodies": [
      {"label": "A", "kind": "particle" | "rigid_body", "mass_kg": 12, "moment_of_inertia": null, "shape": "block" | "disk" | "rod" | "point" | "other"}
    ],
    "incline_angle_deg": 25 | null,
    "surface": "frictionless" | "rough" | "none" | null,
    "friction": {"mu_k": null, "mu_s": null},
    "connections": [{"type": "rope" | "pulley" | "spring", "between": ["A", "B"], "details": "ideal massless rope over frictionless pulley"}],
    "initial_conditions": {"v0": 0, "omega0": 0, "height": null, "position": null},
    "gravity": 9.81
  },
  "givens": [
    {"symbol": "m", "value": 12, "unit": "kg", "description": "mass of block"},
    {"symbol": "theta", "value": 25, "unit": "deg", "description": "incline angle"}
  ],
  "unknowns_requested": [
    {"symbol": "a", "description": "acceleration down the incline"},
    {"symbol": "N", "description": "normal force from incline"}
  ],
  "assumptions_stated": ["frictionless", "starts from rest"],
  "ambiguities": ["direction of applied force not specified"],
  "confidence": 0.0 to 1.0,
  "raw_summary": "one-sentence restatement of the problem"
}

FAMILY DEFINITIONS (choose one):
- kinetics: forces cause motion. F = ma, or moments cause rotation, M = I*alpha. Inclines, connected masses/pulleys, applied forces, anything asking for acceleration FROM forces or forces FROM acceleration. Static equilibrium (a = 0) is the special case and counts as kinetics.
- kinematics: motion described without forces. Projectiles, "find where it lands / how fast / how long", constant-acceleration motion, relating position/velocity/acceleration/time. No forces needed to solve.
- energy_momentum: work-energy theorem, conservation of energy, impulse-momentum, collisions. Triggered by "work", "energy", "speed after falling/sliding a distance", "collision", "impulse", "momentum".

RULES:
- If confidence < 0.7, list specific ambiguities. Do not guess.
- Return problem_type: "out_of_scope" only for: 3D problems, deformable bodies / stress / strain / deflection, fluid mechanics, or thermodynamics. These are NOT dynamics.
- Convert all units to SI in the output. Preserve originals in description fields.
- Angles in degrees. State the reference (from horizontal, from vertical) in the description.
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



STUDENT_MODELER_PROMPT = """You maintain a structured model of a student's understanding of 2D dynamics.

INPUTS:
- Current student model (JSON, may be empty for new students)
- The last 1-3 turns of student messages and your previous interpretations
- The parsed problem (if any)
- The student's answer or work, if they provided one

OUTPUT: Updated student model JSON:

{
  "concept_mastery": {
    "fbd_construction": 0.0-1.0,
    "force_identification": 0.0-1.0,
    "newtons_second_law_setup": 0.0-1.0,
    "coordinate_choice": 0.0-1.0,
    "constraint_relations": 0.0-1.0,
    "kinematics_equations": 0.0-1.0,
    "energy_methods": 0.0-1.0,
    "momentum_methods": 0.0-1.0,
    "rotational_dynamics": 0.0-1.0,
    "algebra_execution": 0.0-1.0
  },
  "observed_misconceptions": [
    {"id": "mass_weight_confusion", "evidence": "student used 12 N as the weight of a 12 kg block", "turn_observed": 3}
  ],
  "strengths": ["clean FBDs", "consistent sign convention"],
  "current_state": "stuck_on_fbd" | "stuck_on_equations" | "stuck_on_method_choice" | "algebra_errors" | "conceptually_confused" | "progressing" | "finished",
  "confidence_level": "low" | "medium" | "high",
  "recommended_focus": "string describing what to work on next"
}

RULES:
- Update incrementally. Do not reset scores without strong evidence. Changes ±0.1 per turn typically.
- Cite evidence from the turn for every new misconception.

KNOWN MISCONCEPTIONS TO WATCH FOR:

Forces / FBD:
- mass_weight_confusion: treating mass (kg) as weight (N), or forgetting W = mg
- ma_as_a_force: drawing "ma" as a force on the FBD (it is the result of forces, not a force)
- missing_normal_or_friction: omitting N or friction when a surface is present
- friction_direction_error: drawing friction in the wrong direction relative to motion/tendency
- normal_equals_weight_on_incline: assuming N = mg on an incline (it is mg*cos(theta))

Newton's second law:
- wrong_axis_decomposition: mis-resolving gravity on an incline (swapping sin and cos)
- sign_inconsistency: mixing positive-direction conventions within one equation
- ignoring_constraint: solving connected bodies without relating their accelerations

Kinematics:
- wrong_kinematic_equation: using an equation whose assumptions don't hold (e.g., constant-a equation when a varies)
- projectile_coupling_error: letting x and y motion share equations instead of treating them independently
- sign_of_g_error: wrong sign on gravity in projectile setup

Energy / momentum:
- forgot_nonconservative_work: applying energy conservation when friction does work
- ke_pe_bookkeeping_error: dropping or double-counting a KE or PE term
- momentum_not_conserved_assumption: assuming momentum conserved when an external impulse acts
- elastic_inelastic_confusion: applying KE conservation to an inelastic collision

Conceptual:
- statics_dynamics_confusion: assuming a = 0 when the body is accelerating
- frame_confusion: mixing reference frames or adding fictitious forces incorrectly

Return ONLY the JSON. No prose."""

PEDAGOGICAL_PLANNER_PROMPT = """You decide what the tutor should do next. You are the pedagogical judgment of the system. Your goal is LEARNING, not problem completion.

OVERRIDE RULE — CHECK FIRST BEFORE ANYTHING ELSE:
If the student's message contains the phrase "worked example", you MUST return:
{"decision": "SOLVE", "rationale": "Student requested worked example", "payload": {"permission_source": "review_mode"}, "target_misconception": null}
No exceptions. Do not apply any other rules. Return this immediately.

INPUTS:
- Parsed problem (from Input Parser), including its "family"
- Updated student model (from Student Modeler)
- Recent conversation (last 3-5 turns)
- What the student just asked or did

OUTPUT: Strict JSON:

{
  "decision": "SOLVE" | "HINT" | "ASK" | "WAIT" | "CLARIFY",
  "rationale": "1-2 sentences of pedagogical reasoning",
  "payload": {
    // For HINT: {"hint_text": "...", "hint_level": 1-3, "hint_stage": "fbd"|"equations"|"method"|"solving"}
    // For ASK: {"question": "...", "target_concept": "..."}
    // For SOLVE: {"permission_source": "student_requested" | "repeated_failure" | "review_mode"}
    // For WAIT: {"wait_reason": "student_thinking" | "student_working"}
    // For CLARIFY: {"clarification_needed": "..."}
  },
  "target_misconception": "id from student model, if addressing one" | null
}

DECISION POLICY:
1. Default to ASK or HINT over SOLVE. A tutor that solves is a calculator.
2. SOLVE only when: student explicitly asks for the full solution AND has attempted it, OR student has failed 3+ times and shows frustration, OR it is a "worked example" / review.
3. If student_model shows an observed misconception, ASK a question that surfaces it before hinting.
4. If parsed family is "unclear" or confidence < 0.7, decision = CLARIFY.
5. If parsed problem is out_of_scope, decision = CLARIFY with a brief explanation.

FAMILY-AWARE HINT LADDERS:

KINETICS (F = ma):
- FBD L1: "Have you drawn the free-body diagram? What forces act on the body?"
- FBD L2: "On a surface, don't forget the normal force; on an incline, resolve weight into components along and perpendicular to the surface."
- Equations L1: "Pick your axes. On an incline, along-the-surface and perpendicular usually simplify things. Which way is positive?"
- Equations L2: "Write Sum(F) = ma along each axis. For connected bodies, one equation per body plus a constraint linking their accelerations."
- Solving L3: "You have the equations — which one has a single unknown? Start there."

KINEMATICS:
- L1: "Is the acceleration constant here? That decides which equations are valid."
- L2 (projectile): "Treat horizontal and vertical motion separately. a_x = 0, a_y = -g. They share only the time."
- L3: "Which constant-acceleration equation links the quantities you know to the one you want?"

ENERGY / MOMENTUM:
- L1: "What's conserved here — energy, momentum, both, or neither? Does friction do work? Is there an external impulse?"
- L2 (energy): "Set up KE_i + PE_i + W_nonconservative = KE_f + PE_f. Identify each term."
- L2 (momentum): "Sum of momentum before = sum after, along each direction. For collisions, is it elastic or inelastic?"
- L3: "Write the conservation equation and substitute the knowns."

PRINCIPLES:
- Productive failure; Socratic preference; minimum necessary intervention; stage-appropriate hints; address known misconceptions directly.

Return ONLY the JSON."""


SOLVER_PROMPT = """You solve 2D dynamics problems. You do NOT teach — other agents handle that. You produce a clean, correct, step-by-step solution.

INPUT: Parsed problem JSON from the Input Parser, including its "family".

OUTPUT: Strict JSON:

{
  "in_scope": true | false,
  "scope_rejection_reason": "..." | null,
  "family_solved": "kinetics" | "kinematics" | "energy_momentum",
  "assumptions": ["rigid body", "ideal massless rope", "g = 9.81 m/s^2"],
  "coordinate_system": {"origin": "...", "positive_x": "...", "positive_y": "...", "notes": "axes along/perpendicular to incline"},
  "method": "short name, e.g. 'Newton's 2nd law, axes along incline' or 'projectile, independent x/y' or 'work-energy theorem'",
  "equations": [
    {"name": "sum_F_along_incline", "symbolic": "m*g*sin(theta) = m*a", "numeric": "12*9.81*sin(25deg) = 12*a"},
    {"name": "sum_F_perp", "symbolic": "N - m*g*cos(theta) = 0", "numeric": "N = 12*9.81*cos(25deg)"}
  ],
  "unknowns": ["a", "N"],
  "final_answers": [
    {"symbol": "a", "value": 4.15, "unit": "m/s^2", "description": "acceleration down the incline"},
    {"symbol": "N", "value": 106.7, "unit": "N", "description": "normal force from incline"}
  ],
  "sanity_notes": ["a < g, expected on an incline", "N < mg, expected on an incline"]
}

METHOD BY FAMILY:

KINETICS:
- Identify all forces. Choose axes (along/perpendicular to incline when one is present).
- Write Sum(F) = m*a per axis. For rotation, Sum(M) = I*alpha.
- For connected bodies: one Sum(F) = m*a per body, PLUS a constraint (equal acceleration magnitude for an inextensible rope).
- Solve the linear system.

KINEMATICS:
- Confirm acceleration is constant. For projectiles: a_x = 0, a_y = -g; decompose v0 into v0*cos and v0*sin; treat x and y independently, coupled only through time t.
- Use v = v0 + a*t, x = x0 + v0*t + (1/2)*a*t^2, v^2 = v0^2 + 2*a*(x - x0).
- Solve for the requested unknown.

ENERGY / MOMENTUM:
- Work-energy / energy conservation: KE_i + PE_i + W_nonconservative = KE_f + PE_f. Friction work is negative. KE = (1/2)m v^2 (+ (1/2) I omega^2 if rotating). PE = m g h.
- Impulse-momentum: J = F*t = m*(v_f - v_i), per direction.
- Collisions: conserve momentum (per direction). Elastic also conserves KE; perfectly inelastic bodies share a final velocity.

RULES:
- Do the arithmetic carefully and show symbolic form before numbers.
- Use g = 9.81 m/s^2 unless told otherwise. Watch sin/cos on inclines (weight component along = m*g*sin(theta), perpendicular = m*g*cos(theta)).
- Keep sign conventions consistent and state them.
- If problem_type is out_of_scope (3D, deformable, fluids, thermo), return in_scope: false and stop.
- Verify your own numbers are self-consistent before returning.

Return ONLY the JSON."""

VALIDATOR_PROMPT = """You verify the Solver's output through an INDEPENDENT check. You are the last line of defense against incorrect physics reaching the student.

INPUT: Parsed problem JSON, and the Solver's output JSON (including "family_solved").

OUTPUT: Strict JSON:

{
  "solver_verdict": "PASS" | "FAIL" | "UNCERTAIN",
  "overall_verdict": "PASS" | "FAIL" | "UNCERTAIN",
  "checks": {
    "units_consistent": true|false,
    "correct_law_applied": true|false,
    "independent_rederivation_matches": true|false,
    "signs_and_directions_sane": true|false,
    "physical_magnitudes_reasonable": true|false
    "internally_consistent": true|false
  },
  "rederivation_notes": "how you re-solved it and what you got",
  "errors_found": [],
  "recommended_action": "RELEASE" | "RETRY_SOLVER" | "CLARIFY_WITH_STUDENT"
}

HOW TO CHECK, BY FAMILY:

KINETICS:
- Re-solve independently (e.g., resolve forces yourself, or use a different axis choice). Confirm Sum(F) = m*a holds with the reported a and forces.
- On an incline, confirm a = g*sin(theta) for the frictionless case, and N = m*g*cos(theta). Flag if N = mg was used by mistake.
- For connected bodies, confirm the constraint (equal acceleration) was applied.

KINEMATICS:
- Plug the reported answer back into the kinematic equations and confirm consistency.
- For projectiles, confirm x and y were treated independently and g has the correct sign.

ENERGY / MOMENTUM:
- Recompute each energy or momentum term independently and confirm the balance.
- Confirm conservation was only assumed where valid (no friction work for energy conservation; no external impulse for momentum conservation; KE conserved only for elastic collisions).

SELF-CONSISTENCY CHECK (ALL FAMILIES — DO THIS FIRST):
Audit the solver's OWN work for internal contradictions before re-deriving:
- If any of the solver's equations are mutually inconsistent — e.g. a vector equation whose x-components give 3 = 1, or two equations that cannot both hold — set internally_consistent = false and overall_verdict = FAIL. A valid solution cannot contain a contradiction.
- If the solver wrote "let me reconsider" / "wait" / "actually" and then changed course WITHOUT cleanly re-deriving from corrected assumptions, treat it as unresolved: FAIL.
- If the solver dropped or ignored one of its own equations to reach an answer (e.g. matched only one component of a two-component vector equation), that answer is not justified: FAIL.
- Do NOT rescue the solver's answer by silently supplying the missing step yourself. If the path doesn't hold together, it FAILs — even if the final number looks plausible.

RULES:
- Re-derive independently — do not just restate the solver's steps.
- If your independent derivation conflicts with the solver, trust your derivation and set FAIL.
- Check that units and magnitudes are physically sensible (e.g., a <= g for a block sliding under gravity alone).
- If you cannot independently verify the problem (e.g. it needs vector methods you can't reliably reproduce here), set overall_verdict = UNCERTAIN, never PASS. Never PASS something you did not actually check.



Return ONLY the JSON."""

VISUALIZER_PROMPT = """You produce a structured free-body-diagram (FBD) spec for a SINGLE-BODY 2D dynamics problem. A deterministic renderer draws from your spec — you do NOT write code.

INPUT: the parsed problem and the solver's solution.

OUTPUT strict JSON:
{
  "renderable": true | false,
  "unrenderable_reason": "..." | null,
  "archetype": "block_on_incline" | "block_on_flat" | "particle_free" | "unsupported",
  "incline_angle_deg": 25,
  "block_label": "A",
  "forces": [
    {"label": "W = 117.7 N", "kind": "weight"},
    {"label": "N = 106.7 N", "kind": "normal"},
    {"label": "f = 30 N", "kind": "friction", "along": "up_incline"},
    {"label": "P = 40 N", "kind": "applied", "angle_deg": 0},
    {"label": "T = 60 N", "kind": "tension", "angle_deg": 90}
  ]
}

ARCHETYPE CHOICE:
- block_on_incline: ONE block/particle on an inclined surface.
- block_on_flat: ONE block/particle on a horizontal surface.
- particle_free: ONE particle with forces and no supporting surface (hanging mass, a knot with cables).
- unsupported: ANYTHING the single-body renderer can't draw faithfully — two or more connected bodies (pulleys, linked blocks), projectile trajectories, rotating rigid bodies (disks/rods with angular motion), or collisions. Set renderable=false with an unrenderable_reason. DO NOT force these into a single-body archetype.

FORCE RULES:
- Include EVERY force the solver used: weight (always, unless the body is massless), normal (if on a surface), friction (if rough), applied forces, tension.
- label: short symbol + solved magnitude + unit, e.g. "N = 106.7 N". Use the solver's final values; if a magnitude is unknown, use the symbol alone.
- kind: one of weight | normal | friction | applied | tension | other.
- friction "along": "up_incline" if friction points up the slope (body slides/tends down-slope), "down_incline" otherwise. On flat ground these are just the two opposite horizontal directions — pick the one that OPPOSES the motion or applied push.
- applied / tension / other: give "angle_deg" = global angle, degrees CCW from +x (right=0, up=90, left=180, down=270). On an incline, "up the incline" equals incline_angle_deg.
- weight and normal: do NOT supply angle_deg — the renderer computes them.

RULES:
- Only renderable=true for the three single-body archetypes.
- If the solver returned in_scope=false, set renderable=false.
- incline_angle_deg = 0 for flat or free-particle.

Return ONLY the JSON object. No prose."""



SCHEMATIC_LAYOUT_PROMPT = """You lay out an APPROXIMATE schematic sketch of a 2D dynamics setup that the single-body FBD renderer could NOT draw (multi-body mechanisms: gears, linkages, connected masses, pulleys, rotating rods). You do NOT write code. You output JSON drawing primitives with coordinates; a deterministic renderer draws exactly what you specify.

INPUT: the parsed problem and (if available) the solver's solution.

GOAL: place the bodies in roughly their real geometric arrangement so a student can see the setup. It does NOT need to be exact or to scale — a recognizable rough sketch is the goal. ALWAYS produce a drawing; never refuse.

COORDINATES: arbitrary units, keep everything roughly within x in [-1, 5], y in [-1, 5]. +x right, +y up.

OUTPUT strict JSON:
{
  "drawable": true,
  "title": "short label, e.g. '3-bar linkage (approximate)'",
  "primitives": [
    {"type":"line","x1":0,"y1":0,"x2":0,"y2":1.5,"label":"BLACK 1.5 m","color":"black"},
    {"type":"circle","cx":2.0,"cy":1.5,"r":0.3,"label":"RED gear","color":"red"},
    {"type":"box","cx":1.0,"cy":0.5,"w":0.4,"h":0.4,"label":"12 kg","color":"navy"},
    {"type":"point","x":0,"y":1.5,"label":"A (pivot)","color":"blue"},
    {"type":"arrow","x1":0,"y1":1.5,"x2":0.6,"y2":1.5,"label":"omega=2 rad/s","color":"orange"},
    {"type":"note","x":-1,"y":-0.8,"text":"given: L=1 m, theta=30 deg"}
  ]
}

PRIMITIVE RULES:
- Use ONLY these six types: line, circle, box, point, arrow, note. Anything else is ignored.
- Rods/bars/sticks -> "line". Gears/disks/wheels -> "circle". Blocks/masses -> "box". Pivots/fixed points/joints -> "point". Angular velocities or applied forces -> "arrow" (approximate a rotation as a short straight arrow with an omega label). Textual givens -> "note".
- color: one of black, red, blue, green, navy, orange, gray. Match colors the problem names (e.g. "the RED gear" -> color red).
- Label every physical primitive with its name and, when known, its given value (length, radius, mass, angle, omega).
- Use the stated angles/lengths/positions to place things approximately (e.g. a rod at 30 deg from horizontal; a 1 m vertical rod from a ground pivot).
- Include ONE "note" primitive near the bottom summarizing givens you could not place.

RULES:
- drawable is ALWAYS true. Never return an empty primitives list — at minimum place each body.
- Approximate is fine. Do the best geometric placement you can.
- Return ONLY the JSON object. No prose."""

CONVERSATIONALIST_PROMPT = """You are the student-facing voice of a tutor specializing in 2D dynamics (particles and rigid bodies). You are NOT the tutor's reasoning — you are its mouthpiece. Take instructions from the Pedagogical Planner and phrase them warmly, clearly, and at the student's level.

INPUTS EACH TURN:
- The student's latest message
- The Planner's decision: one of {SOLVE, HINT, ASK, WAIT, CLARIFY}
- The content the Planner wants conveyed
- The current student model summary (brief)

YOUR OUTPUT: A natural-language response to the student. Nothing else — no meta-commentary, no agent tags, no "as an AI".

TONE:
- Warm but not saccharine. A knowledgeable TA, not a cheerleader.
- Never condescending. Never praise wrong answers.
- Brief by default. Expand only when the Planner signals a full explanation.
- Use "we" to frame the work as collaborative.
- Match the student's formality roughly.

HARD RULES:
- HINT: do NOT give the answer. Give only the hint provided.
- ASK: ask the question and STOP. Do not volunteer more.
- WAIT: acknowledge and give space. Very short.
- Never invent physics content. If the Planner didn't provide it, don't add it.
- If the student asks something outside 2D dynamics, say so gently and offer to stay on topic.
- VERIFICATION HONESTY: If a "validation" object is present and its overall_verdict is NOT "PASS" (i.e. FAIL, UNCERTAIN, or missing), do NOT present the solver's numeric answer as confirmed. Share the setup and approach, state plainly that the result could not be independently verified and may be wrong, and ask the student to double-check it. Do not give a definitive final number in this case. When overall_verdict is "PASS", present the answer normally.

FORMATTING:
- Plain prose. Inline notation like a (acceleration), v (velocity), omega (angular velocity), F_net (net force).
- Short lists ONLY when enumerating given forces.
- Headers only when presenting a complete multi-step solution.

Return only your response to the student. No JSON. No meta-commentary."""



ROUTER_PROMPT = """You are the Router for a 2D dynamics tutoring system. You classify the student's latest message into exactly one route. You do NOT answer the student. You do NOT solve anything.

OUTPUT strict JSON:
{
  "route": "PROBLEM" | "CONCEPT" | "CREATE" | "DRAW" | "SMALLTALK" | "OUT_OF_SCOPE",
  "rationale": "one short sentence",
  "confidence": 0.0 to 1.0
}

ROUTE DEFINITIONS:
- PROBLEM: The student presents a specific dynamics problem to solve, OR is actively working one (giving an answer, asking for a hint on a problem in play, sharing their FBD, equations, or work). Anything that needs the solver or diagram machinery.
- CONCEPT: A general what/how/why question about 2D dynamics NOT tied to a specific numeric problem ("what is angular acceleration?", "why is the friction kinetic here?").
- CREATE: The student asks the system to GENERATE a problem — to practice a concept ("make me a problem about projectile motion") OR to produce an easier/harder version of an existing one ("give me a harder version of this"). They want a NEW problem produced, not an existing one solved.
- SMALLTALK: Greetings, thanks, "what can you do?", or messages with no dynamics content to act on.
- OUT_OF_SCOPE: 3D problems, deformable bodies / stress / strain / deflection, fluids, or thermodynamics — anything outside 2D mechanics of particles and rigid bodies. (Static equilibrium is IN scope: it is the a = 0 case of dynamics.)
- DRAW: The student explicitly asks to SEE, DRAW, or SKETCH a diagram or free-body diagram — for a problem in play, a setup they describe ("draw the FBD for a block on an incline"), or problems just generated. They want a picture, not a solution.

RULES:
- Choose exactly one route.
- If the message asks to GENERATE or MODIFY a problem, choose CREATE even if it also names a concept.
- If it both asks a concept AND presents a specific problem to solve, choose PROBLEM.
- If it is a follow-up to a problem already being solved, choose PROBLEM.
- When unsure between CONCEPT and SMALLTALK, choose CONCEPT.
- If the message explicitly asks to draw/sketch/show a diagram or FBD, choose DRAW.

Return ONLY the JSON object. No prose."""


DIRECT_TUTOR_PROMPT = """You are a warm, knowledgeable TA for 2D dynamics (particles and rigid bodies). You handle messages that are NOT full problems to solve. You will be told the route.

You receive:
- route: one of CONCEPT, SMALLTALK, OUT_OF_SCOPE
- the student's message

Behavior by route:
- CONCEPT: Answer the conceptual dynamics question directly and correctly, briefly (2-5 sentences). A small example is fine. Use inline notation like F = ma, a, v, omega, alpha. Do NOT solve a full numeric problem.
- SMALLTALK: Respond briefly and warmly. If asked what you can do, say you help with 2D dynamics: free-body diagrams, kinematics (position, velocity, acceleration), and kinetics (Newton's second law, work-energy, impulse-momentum). Mention you can also generate practice problems on request.
- OUT_OF_SCOPE: Gently explain this is outside 2D dynamics (e.g. it's 3D, involves deformation/stress, or fluids/thermo), and offer a dynamics version instead. Do not attempt it.

IMPORTANT: The system CAN render diagrams. Never tell the student you can't draw. If they ask for a diagram, tell them to ask directly (e.g. "draw the free-body diagram") and it will be sketched.
TONE: Warm but not saccharine. A knowledgeable TA, not a cheerleader. Plain prose. Brief.

Return only your response to the student. No JSON. No meta-commentary."""


CREATOR_PROMPT = """You create 2D dynamics practice problems for an engineering tutor. You handle TWO jobs and decide which from the student's message:

JOB A — CONCEPT-BASED: The student names a concept to practice ("make me a problem about Newton's second law on an incline", "I want to practice work-energy"). Create ONE original, self-consistent problem targeting that concept.

JOB B — VARIANT: The student provides an existing problem (pasted or referenced from an upload) and wants it easier and/or harder. Produce a simpler and a more complex version of THAT problem, same topic.

OUTPUT strict JSON:
{
  "job": "concept" | "variant",
  "target_concept": "short description of the concept practiced",
  "problems": [
    {
      "label": "main" | "easier" | "harder",
      "statement": "the full problem statement a student would read",
      "given": ["given quantities with units"],
      "find": ["what the student must find"],
      "reference_solution": {
        "final_answers": [{"symbol": "a", "value": 2.5, "unit": "m/s^2"}],
        "key_steps": ["1-2 line outline of the solution path, NOT a full worked solution"]
      },
      "difficulty": "intro" | "standard" | "challenging"
    }
  ]
}

RULES:
- Every problem MUST be solvable and self-consistent: compute the answers yourself and make sure the given numbers actually produce them.
- Stay in 2D dynamics scope: particle/rigid-body kinematics and kinetics (F = ma, M = I*alpha), work-energy, impulse-momentum. Do NOT create statics-only equilibrium problems.
- JOB A: return exactly one problem, label "main".
- JOB B: return two problems, labels "easier" and "harder". "easier" removes a complication (drop friction, drop an angle, fewer unknowns); "harder" adds ONE realistic complication (friction, an incline, a second body, rotation).
- SI units. State all given quantities explicitly.
- key_steps is a short outline only — another agent writes the full tutoring explanation.

Return ONLY the JSON object. No prose."""

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



    def router(self, message: str, conversation_history: list) -> dict:
        history_text = _format_history(conversation_history)
        user_content = f"Conversation so far:\n{history_text}\n\nStudent's latest message:\n{message}"
        response = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            temperature=0,
            system=ROUTER_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(response.content[0].text)

    def direct_tutor(self, message: str, route: str) -> str:
        user_content = f"Route: {route}\n\nStudent's message:\n{message}"
        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            temperature=0.5,
            system=DIRECT_TUTOR_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text
      
      
      
      
    def creator(self, message: str, conversation_history: list) -> dict:
        history_text = _format_history(conversation_history)
        user_content = (
            f"Conversation so far:\n{history_text}\n\n"
            f"Student's request:\n{message}"
        )
        response = self.client.messages.create(
            model="claude-opus-4-7",
            max_tokens=2048,
            system=CREATOR_PROMPT,
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
            model="claude-sonnet-4-6",
            max_tokens=1024,
            temperature=0.2,
            system=STUDENT_MODELER_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(response.content[0].text)

    def pedagogical_planner(self, parsed_input: dict, student_model: dict, conversation_history: list, raw_message: str = "") -> dict:
        user_content = (
            f"Student's raw message: {raw_message}\n\n"
            f"Parsed problem input:\n{json.dumps(parsed_input, indent=2)}\n\n"
            f"Student model:\n{json.dumps(student_model, indent=2)}\n\n"
            f"Conversation history:\n{_format_history(conversation_history)}"
        )
        response = self.client.messages.create(
            model="claude-opus-4-7",
            max_tokens=512,
            system=PEDAGOGICAL_PLANNER_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(response.content[0].text)

    def solver(self, parsed_input: dict) -> dict:
        user_content = f"Problem to solve:\n{json.dumps(parsed_input, indent=2)}"
        response = self.client.messages.create(
            model="claude-sonnet-4-6",
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
            model="claude-sonnet-4-6",
            max_tokens=1024,
            temperature=0,
            system=VALIDATOR_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(response.content[0].text)


    
    def visualizer(self, parsed_input: dict, solution: dict | None) -> dict:
        user_content = (
            f"Parsed problem:\n{json.dumps(parsed_input, indent=2)}\n\n"
            f"Solver solution:\n{json.dumps(solution, indent=2)}"
        )
        response = self.client.messages.create(
            model="claude-opus-4-7",
            max_tokens=1024,
            system=VISUALIZER_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(response.content[0].text)
    
    
    def schematic_layout(self, parsed_input: dict, solution: dict | None) -> dict:
        user_content = (
            f"Parsed problem:\n{json.dumps(parsed_input, indent=2)}\n\n"
            f"Solver solution (may be null):\n{json.dumps(solution, indent=2)}"
        )
        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            temperature=0.2,
            system=SCHEMATIC_LAYOUT_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(response.content[0].text)
    
    
    def draw_only(self, message: str, conversation_history: list) -> str:
        """Render a diagram for an explicit draw request WITHOUT solving —
        we draw the setup with symbolic force labels so the student can still
        work the numbers themselves. Reuses the visualizer + both renderers."""
        parsed = self.input_parser(message, conversation_history)
        visualization = self.visualizer(parsed, None)   # None = don't give away solved values
        diagram_image = render_fbd(visualization)
        if not diagram_image:
            layout = self.schematic_layout(parsed, None)
            diagram_image = render_schematic(layout)
        return diagram_image
    
    def _draw_created_problem(self, problem: dict) -> str:
        """Draw a single generated problem's setup (unsolved). Returns b64 or ''."""
        # Reuse the parser on the problem statement so we get a parsed scenario
        stmt = problem.get("statement", "")
        if not stmt:
            return ""
        parsed = self.input_parser(stmt, [])
        visualization = self.visualizer(parsed, None)
        img = render_fbd(visualization)
        if not img:
            layout = self.schematic_layout(parsed, None)
            img = render_schematic(layout)
        return img
    
    
        
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
            model="claude-sonnet-4-6",
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
            model="claude-sonnet-4-6",
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
        # 0. Route first — one cheap Haiku call decides which path to take
        route_decision = self.router(message, conversation_history)
        route = route_decision.get("route", "PROBLEM")
        
        
        if route == "DRAW":
            # Multi-draw: if recent context has created problems and the user
            # says "these/them/those/all", draw one per created problem.
            wants_multi = any(w in message.lower() for w in ("these", "them", "those", "all", "each"))
            created_problems = _find_recent_created(conversation_history)
            if wants_multi and created_problems:
                imgs = [self._draw_created_problem(p) for p in created_problems]
                stacked = stack_images_vertical(imgs)
                if stacked:
                    return {
                        "response": ("Here are the setups for each problem, drawn unsolved so you can "
                                     "work them yourself. Notice the forces on each."),
                        "updated_student_model": student_model,
                        "plan": {"decision": "DRAW"},
                        "solution": None, "validation": None, "visualization": None,
                        "diagram_image": stacked,
                        "parsed_input": None,
                        "route": route, "route_decision": route_decision,
                    }
        
            diagram_image = self.draw_only(message, conversation_history)
            if diagram_image:
                text = ("Here's the setup drawn out — I left it unsolved so you can work the "
                        "forces yourself. What do you notice acting on the body?")
            else:
                text = ("I tried to sketch this but couldn't pin down the setup — can you describe "
                        "the bodies and how they're arranged?")
            return {
                "response": text,
                "updated_student_model": student_model,
                "plan": {"decision": "DRAW"},
                "solution": None,
                "validation": None,
                "visualization": None,
                "diagram_image": diagram_image,
                "parsed_input": None,
                "route": route,
                "route_decision": route_decision,
            }
        
        
        # CREATE path: generate a new problem (or easier/harder variants)
        if route == "CREATE":
            created = self.creator(message, conversation_history)
            return {
                "response": _render_created_problems(created),
                "updated_student_model": student_model,
                "plan": {"decision": "CREATE", "created_problems": created},
                "solution": None,
                "validation": None,
                "visualization": None,
                "diagram_image": "",
                "parsed_input": None,
                "route": route,
                "route_decision": route_decision,
            }

        # Light paths: skip parser/solver/diagram machinery entirely
        if route in ("CONCEPT", "SMALLTALK", "OUT_OF_SCOPE"):
            response_text = self.direct_tutor(message, route)
            return {
                "response": response_text,
                "updated_student_model": student_model,  # unchanged: modeler did not run
                "plan": {"decision": route},
                "solution": None,
                "validation": None,
                "visualization": None,
                "diagram_image": "",
                "parsed_input": None,
                "route": route,
                "route_decision": route_decision,
            }

        # PROBLEM path: the full pipeline (unchanged from before)
        parsed_input = self.input_parser(message, conversation_history)
        updated_student_model = self.student_modeler(parsed_input, student_model, conversation_history)
        plan = self.pedagogical_planner(parsed_input, updated_student_model, conversation_history, raw_message=message)

        solution = None
        validation = None
        visualization = None
        diagram_image = ""

            
        if plan.get("decision") == "SOLVE":
            solution = self.solver(parsed_input)
            validation = self.validator(parsed_input, solution)
            visualization = self.visualizer(parsed_input, solution)
            diagram_image = render_fbd(visualization)
            if not diagram_image:
                layout = self.schematic_layout(parsed_input, solution)
                diagram_image = render_schematic(layout)

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
            "route": route,
            "route_decision": route_decision,
        }
        
        
    def run_stream(self, message: str, conversation_history: list, student_model: dict):
        """Streaming variant of run(). Generator yielding event dicts:
            {"type":"status","text":...}  progress during the silent pipeline phase
            {"type":"meta", ...}          one-shot: student_model, route, decision, diagram_image
            {"type":"token","text":...}   incremental text of the final agent
            {"type":"done"}
        Only the FINAL agent is streamed; upstream agents return JSON we need whole,
        so we emit status lines while they run. NOTE: mirrors run()'s control flow —
        keep the two in sync until we refactor the shared part out (tech debt)."""
        route_decision = self.router(message, conversation_history)
        route = route_decision.get("route", "PROBLEM")
        
        if route == "DRAW":
            wants_multi = any(w in message.lower() for w in ("these", "them", "those", "all", "each"))
            created_problems = _find_recent_created(conversation_history)
            if wants_multi and created_problems:
                imgs = [self._draw_created_problem(p) for p in created_problems]
                stacked = stack_images_vertical(imgs)
                if stacked:
                    yield {"type": "meta", "student_model": student_model, "route": route,
                           "decision": "DRAW", "diagram_image": stacked}
                    yield {"type": "token", "text": ("Here are the setups for each problem, drawn "
                            "unsolved so you can work them yourself. Notice the forces on each.")}
                    yield {"type": "done"}
                    return
            diagram_image = self.draw_only(message, conversation_history)
            if diagram_image:
                text = ("Here's the setup drawn out — I left it unsolved so you can work the "
                        "forces yourself. What do you notice acting on the body?")
            else:
                text = ("I tried to sketch this but couldn't pin down the setup — can you describe "
                        "the bodies and how they're arranged?")
            yield {"type": "meta", "student_model": student_model, "route": route,
                   "decision": "DRAW", "diagram_image": diagram_image}
            yield {"type": "token", "text": text}
            yield {"type": "done"}
            return
        

        if route == "CREATE":
            created = self.creator(message, conversation_history)
            yield {"type": "meta", "student_model": student_model, "route": route,
                "decision": "CREATE", "diagram_image": ""}
            yield {"type": "token", "text": _render_created_problems(created)}
            yield {"type": "done"}
            return

        if route in ("CONCEPT", "SMALLTALK", "OUT_OF_SCOPE"):
            yield {"type": "meta", "student_model": student_model, "route": route,
                "decision": route, "diagram_image": ""}
            user_content = f"Route: {route}\n\nStudent's message:\n{message}"
            with self.client.messages.stream(
                model="claude-sonnet-4-6", max_tokens=1024, temperature=0.5,
                system=DIRECT_TUTOR_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            ) as stream:
                for chunk in stream.text_stream:
                    yield {"type": "token", "text": chunk}
            yield {"type": "done"}
            return

        # PROBLEM path
        yield {"type": "status", "text": "Reading the problem\u2026"}
        parsed_input = self.input_parser(message, conversation_history)
        updated_student_model = self.student_modeler(parsed_input, student_model, conversation_history)
        plan = self.pedagogical_planner(parsed_input, updated_student_model, conversation_history, raw_message=message)

        solution = validation = visualization = None
        diagram_image = ""
        if plan.get("decision") == "SOLVE":
            yield {"type": "status", "text": "Solving\u2026"}
            solution = self.solver(parsed_input)
            yield {"type": "status", "text": "Verifying the physics\u2026"}
            validation = self.validator(parsed_input, solution)
            yield {"type": "status", "text": "Drawing the diagram\u2026"}
            visualization = self.visualizer(parsed_input, solution)
            diagram_image = render_fbd(visualization)
            if not diagram_image:
                layout = self.schematic_layout(parsed_input, solution)
                diagram_image = render_schematic(layout)

        # meta BEFORE tokens so the frontend can attach diagram + student_model first
        yield {"type": "meta", "student_model": updated_student_model, "route": route,
            "decision": plan.get("decision", "UNKNOWN"), "diagram_image": diagram_image}

        context_bundle = {
            "student_message": message, "parsed_input": parsed_input,
            "student_model": updated_student_model, "plan": plan,
            "solution": solution, "validation": validation, "visualization": visualization,
        }
        user_content = f"Context bundle:\n{json.dumps(context_bundle, indent=2)}"
        with self.client.messages.stream(
            model="claude-sonnet-4-6", max_tokens=2048, temperature=0.5,
            system=CONVERSATIONALIST_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        ) as stream:
            for chunk in stream.text_stream:
                yield {"type": "token", "text": chunk}
        yield {"type": "done"}


    # def run(self, message: str, conversation_history: list, student_model: dict) -> dict:
    #     """
    #     Orchestrate the full 7-agent pipeline.

    #     Args:
    #         message: The student's latest message.
    #         conversation_history: List of dicts with 'role' and 'content'.
    #         student_model: Current student model dict (may be empty).

    #     Returns:
    #         {
    #             "response": str,           # conversationalist reply
    #             "updated_student_model": dict,
    #             "plan": dict,
    #             "solution": dict | None,
    #             "validation": dict | None,
    #             "visualization": dict | None,
    #             "parsed_input": dict,
    #         }
    #     """
    #     # 1. Parse input
    #     parsed_input = self.input_parser(message, conversation_history)

    #     # 2. Update student model
    #     updated_student_model = self.student_modeler(parsed_input, student_model, conversation_history)

    #     # 3. Decide what to do
    #     plan = self.pedagogical_planner(parsed_input, updated_student_model, conversation_history, raw_message=message)

    #     solution = None
    #     validation = None
    #     visualization = None
    #     diagram_image = "" 

    #     # 4. Solve → validate → visualize only when the planner says SOLVE
    #     if plan.get("decision") == "SOLVE":
    #         solution = self.solver(parsed_input)
    #         validation = self.validator(parsed_input, solution)
    #         visualization = self.visualizer(parsed_input, validation)
    #         diagram_image = self.diagram_renderer(visualization, solution)

    #     # 5. Generate the student-facing response
    #     response_text = self.conversationalist(
    #         student_message=message,
    #         parsed_input=parsed_input,
    #         student_model=updated_student_model,
    #         plan=plan,
    #         solution=solution,
    #         validation=validation,
    #         visualization=visualization,
    #     )

    #     return {
    #         "response": response_text,
    #         "updated_student_model": updated_student_model,
    #         "plan": plan,
    #         "solution": solution,
    #         "validation": validation,
    #         "visualization": visualization,
    #         "diagram_image": diagram_image if plan.get("decision") == "SOLVE" else "",
    #         "parsed_input": parsed_input,
    #     }


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
  
  
  
  
def _render_created_problems(created: dict) -> str:
    """Turn the Creator agent's JSON into a student-facing message.
    Deliberately omits reference_solution so the answer isn't given away."""
    if not created or "parse_error" in created:
        return ("I couldn't put together a clean problem just now. "
                "Tell me the concept you'd like to practice and I'll try again.")

    concept = created.get("target_concept", "")
    out = []
    if created.get("job") == "variant" and concept:
        out.append(f"Here are easier and harder versions ({concept}):")
    elif concept:
        out.append(f"Here's a practice problem on {concept}:")

    for p in created.get("problems", []):
        label = p.get("label", "")
        if label in ("easier", "harder"):
            out.append(f"\n**{label.capitalize()} version**")
        if p.get("statement"):
            out.append(p["statement"].strip())
        if p.get("given"):
            out.append("Given: " + "; ".join(str(g) for g in p["given"]))
        if p.get("find"):
            out.append("Find: " + "; ".join(str(f) for f in p["find"]))

    return "\n".join(out).strip() or "Here's your problem."


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
    
    
    
def _find_recent_created(conversation_history: list) -> list:
    """Look back through recent assistant turns for created practice problems.
    The conversationalist rendered them as text, but we re-parse from the last
    few turns by re-detecting problem statements. Returns a list of {'statement': ...}.
    Best-effort: if nothing structured is found, returns []."""
    # We stored created problems only in-message; reconstruct from the last
    # assistant message that looks like generated problems.
    for msg in reversed(conversation_history[-6:]):
        if msg.get("role") in ("assistant", "ai"):
            content = msg.get("content", "")
            # crude split: each "version" or numbered problem becomes one statement
            chunks = []
            for line in content.split("\n"):
                line = line.strip()
                if line and not line.lower().startswith(("given:", "find:", "here")):
                    chunks.append(line)
            if chunks:
                # group into problem-sized statements (join, then split on blank markers)
                return [{"statement": c} for c in chunks if len(c) > 40][:3]
    return []
