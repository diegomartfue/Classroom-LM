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
import logging
import os
import re
import anthropic
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import io
import base64
import uuid
from datetime import datetime, timezone
from .memory import SessionMemory
from .misconceptions import known_misconceptions_block, remediation_for
from . import solution_cache
from .svg_layout import fix_label_collisions
from dotenv import load_dotenv
from model_config import SONNET_MODEL, HAIKU_MODEL, OPUS_MODEL, VISUALIZER_MODEL
from utils.usage_tracker import DailyLimitReached, DailyUsageTracker, UsageTrackingClient

# Shown to the student instead of ever reaching the API once the daily
# spending limit (item 2 of the pilot hardening pass) is hit.
DAILY_LIMIT_MESSAGE = (
    "The tutor is resting for today — we've hit today's usage limit. "
    "Please come back tomorrow and we'll pick up right where you left off!"
)
from response_utils import extract_text

load_dotenv()

logger = logging.getLogger(__name__)

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
"""

# The hand-written list above is dynamics-focused (F=ma, kinematics,
# energy/momentum) and never covered statics (planar equilibrium,
# ΣF=0/ΣM=0), which is explicitly in scope per CLAUDE.md's MVP.
# docs/misconceptions.md catalogs exactly that — FBD construction,
# equilibrium equations, reference point choice, distributed loads — and was
# previously unused anywhere in the pipeline. Appended here (not
# hand-duplicated) so the doc file stays the single source of truth for
# those categories; known_misconceptions_block() returns "" if the doc is
# missing/unparseable, so a broken doc file just leaves the prompt as
# written above rather than breaking detection.
STUDENT_MODELER_PROMPT = (
    STUDENT_MODELER_PROMPT + known_misconceptions_block()
    + "\n\nReturn ONLY the JSON. No prose."
)

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
    //   (hint_level 3 from the Hint button may also carry "worked_step": {"symbol", "value", "unit", "description", "equation"} — one intermediate step, computed by the solver, to be carried out with numbers)
    // For ASK: {"question": "...", "target_concept": "..."}
    // For SOLVE: {"permission_source": "student_requested" | "repeated_failure" | "review_mode" | "hint_ladder_exhausted"}
    // ("hint_ladder_exhausted" is set deterministically by the Hint button's
    // own level-4 tap, in code — not something you need to produce yourself.)
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
  "intermediate_values": [
    {"symbol": "W", "value": 117.7, "unit": "N", "description": "weight, m*g"},
    {"symbol": "f_k", "value": 21.3, "unit": "N", "description": "kinetic friction, mu_k*N"}
  ],
  "sanity_notes": ["a < g, expected on an incline", "N < mg, expected on an incline"]
}

INTERMEDIATE VALUES: list every numeric quantity you computed on the way that is not already in final_answers or the givens — forces (normal force, friction, weight or its components, tension), components, times, etc. Use the conventional short symbol (N, f_k, W, T, F_x, v_0, t). Students check their own work line by line against these, so every force you compute must appear here with its value.

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

VISUALIZER_PROMPT = """You are an expert technical illustrator. Given a physics problem and its solution, draw an accurate, clean, readable SVG diagram. Include: the body/mechanism exactly as described, all forces/reactions with correct labels and directions, support symbols if applicable, and a coordinate system indicator. Output ONLY valid SVG code starting with <svg and ending with </svg>. Use standard physics diagram conventions and a white background.

Keep the SVG compact: no comments, no unnecessary groups or decimals beyond 1 place, reuse arrowhead markers via <defs>.

LAYOUT PROCESS (plan all coordinates before emitting any SVG)
1. viewBox 600x400 unless geometry demands more. 30px margin on all sides for
   every element and label.
2. Body near center, roughly 40% of width, open space around it for arrows.
3. Decide every arrow's start and end point first. Arrows run along their true
   direction, 50 to 80px long.
4. For a particle or single-body problem, all force arrows originate at the
   body's center of mass and point outward. For a rigid body, each force is
   drawn at its actual point of application: reactions at their supports,
   applied loads at their load points, weight at the center of mass. No arrow
   may cross the body outline or any surface line.
5. Labels go at the arrow tip, offset 12px perpendicular, on the side away from
   the body. Never place a label on a surface line, on the body, or on another
   arrow.
6. Label the body outside its outline, not inside it.
7. Angle and dimension labels go outside their arc or dimension line, and must
   not touch any other label. When two labels would collide, move the less
   important one farther out.
8. A support's point label (A, B, C) and any force label at that support must
   not occupy the same region. Place the point label below or inside the
   support symbol, and place force labels at their arrow tips, away from the
   support.
9. Draw all text last so it paints on top.
10. Position every <text> with plain x/y and its own font-size attribute. Never
   put a transform (rotate, translate, scale) on a <text> or on a group
   containing text, and never place a label inside a filled shape such as the
   incline — keep it in open space at least 8px from every edge and arc.

CONTENT — FORCE / FREE-BODY-DIAGRAM PROBLEMS
Only draw arrows for forces acting on the body. Constants such as g belong in
the givens text block, never as a vector.
Never draw an arrow for a force whose magnitude is zero. State it in the
givens block as text instead.
If a force has a numeric value in the solution, show the computed number with
units. Never mix a symbol and a unit in the same expression (writing
"f_k = 0.3 N" when 0.3 is mu is wrong).
These force rules do not apply to a kinematics problem (below) — do not draw
force arrows on a body that has no forces given.

CONTENT — KINEMATICS PROBLEMS (no forces given, or the problem only asks for
positions/velocities/accelerations)
Draw the body (or bodies) in their described configuration: point, block,
disk, rod, or linkage, at the position/angle stated in the problem.
Show position with a labeled coordinate or a dimension line from a fixed
reference (pivot, wall, ground) — not a force arrow.
Show linear velocity/acceleration as arrows from the relevant point (e.g. v_B,
a_B from point B), and angular velocity/acceleration as a curved arrow around
the rotation axis, labeled omega/alpha with correct rotational sense (CW/CCW
matching the problem).
Draw constraint geometry explicitly: a string over a pulley, a rod pinned at
a fixed point, a wheel rolling without slipping on a surface (mark the
contact point) — whatever links the bodies' motions together.
Include a coordinate system or angle reference so vector directions are
unambiguous.

UNKNOWNS — applies to both force and kinematics diagrams
Never compute or derive a quantity yourself. A value may appear as a number
only if it is already present in the parsed problem's givens or in the
solver solution you were given (solution may be null — treat that as "no
solved values are available yet"). For every other quantity the problem asks
to find, write its symbol with a literal question mark instead of a number,
e.g. "omega = ?", "v_B = ?", "N = ?" — never guess, estimate, or silently
solve for it, even if the physics is simple enough that you could. Showing a
number you were not given defeats the point of the exercise for the student.

TEXT
Arial sans-serif, 13px force labels, 11px secondary notes.
Every <text> gets paint-order="stroke" stroke="white" stroke-width="4"
stroke-linejoin="round" as a readability fallback.
text-anchor and dominant-baseline="middle" for precise placement."""



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
- Sometimes "misconception_guidance": one sentence on how to address the
  specific misconception the Planner targeted this turn. When present, weave
  it into your ASK/HINT naturally — don't quote it verbatim or announce "the
  system detected a misconception"; just let it ground and sharpen what you
  already say.

YOUR OUTPUT: A natural-language response to the student. Nothing else — no meta-commentary, no agent tags, no "as an AI".

TONE:
- Warm but not saccharine. A knowledgeable TA, not a cheerleader.
- Never condescending. Never praise wrong answers.
- Brief by default. Expand only when the Planner signals a full explanation.
- Use "we" to frame the work as collaborative.
- Match the student's formality roughly.

HARD RULES:
- HINT: do NOT give the answer. Give only the hint provided.
- HINT with payload.worked_step: carry out exactly that ONE step for the student, with the numbers: write the equation, substitute the values, and state the result it gives (e.g. "N = m*g*cos(30) = 10*9.81*cos(30) = 84.96 N"). Then ask the student to take the next step themselves. Do NOT compute anything beyond that step, and do NOT state or hint at any final answer.
- ASK: ask the question and STOP. Do not volunteer more.
- WAIT: acknowledge and give space. Very short.
- Never invent physics content. If the Planner didn't provide it, don't add it.
- If the student asks something outside 2D dynamics, say so gently and offer to stay on topic.
- Never output SVG, HTML, or diagram code. If a diagram was rendered, it is displayed to the student separately; refer to it in words only.
- VERIFICATION HONESTY: If a "validation" object is present and its overall_verdict is NOT "PASS" (i.e. FAIL, UNCERTAIN, or missing), do NOT present the solver's numeric answer as confirmed. Share the setup and approach, state plainly that the result could not be independently verified and may be wrong, and ask the student to double-check it. Do not give a definitive final number in this case. When overall_verdict is "PASS", present the answer normally.

FORMATTING:
- FORMATTING RULE: Always wrap all mathematical expressions, equations, variables, and units in KaTeX delimiters. Use $...$ for inline math (e.g. $\\omega \\times r = 2$ m/s) and $$...$$ for display equations. Never write math in plain text. Examples: write $\\omega$ not omega, write $\\alpha_{BLACK} = 1$ rad/s² not alpha_BLACK = 1 rad/s².
- Prose for the explanation itself, but every symbol, variable, number-with-unit, and equation goes inside KaTeX delimiters (e.g. $a$, $v$, $\\omega$, $\\alpha$, $F_{net}$).
- Short lists ONLY when enumerating given forces.
- Headers only when presenting a complete multi-step solution.

Return only your response to the student. No JSON. No meta-commentary."""


# Shared math-formatting contract for the user-facing, natural-language response
# agents (Direct Tutor + Conversationalist). Kept in ONE place and appended to
# both prompts so the frontend's Markdown + KaTeX pipeline always receives math
# in a renderable form. NOT applied to JSON-producing agents (it would interfere
# with their strict JSON contracts).
MATH_FORMATTING = """

MATHEMATICAL FORMATTING:
- Use LaTeX for all mathematical expressions, variables, symbols, and units.
- Use $...$ for inline math (e.g. $F = ma$, $v_0$, $\\omega$) and $$...$$ for display equations.
- Do NOT output bare or plain-text LaTeX/math when it is meant to be rendered — always wrap it in the delimiters above (write $\\omega$, not omega).
- Keep mathematical notation inside the appropriate delimiters.
- Do NOT put LaTeX math inside code blocks or inline code unless the student explicitly asks for code.
- Use ordinary text for non-mathematical dollar amounts / currency (e.g. "it costs 20 dollars"), never math delimiters."""


ROUTER_PROMPT = """You are the Router for a 2D dynamics tutoring system. You classify the student's latest message into exactly one route. You do NOT answer the student. You do NOT solve anything.

OUTPUT strict JSON:
{
  "route": "PROBLEM" | "CONCEPT" | "CREATE" | "DRAW" | "SMALLTALK" | "OUT_OF_SCOPE",
  "rationale": "one short sentence",
  "confidence": 0.0 to 1.0,
  "problem_scope": "self_contained" | "referential"
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

PROBLEM_SCOPE (always set this field, regardless of route, but it only matters for DRAW):
- "self_contained": the message states everything needed to draw or solve the setup on its own — its own body and its own numbers — with NO dependency on anything said earlier. A message that only TWEAKS a value from a previous problem is NOT self-contained: it still depends on the prior turn for the rest of the setup.
- "referential": the message depends on the prior conversation to know what to draw — it names no complete setup of its own, or it modifies a previously stated setup rather than restating one.

PROBLEM_SCOPE EXAMPLES:
- "A 25 kg crate slides down a 20 degree incline, mu_k = 0.3. Draw the FBD." -> self_contained (states its own body and every number needed).
- "same thing but with a 10 kg block instead" -> referential (depends on the previous turn for the incline angle, friction, etc.; only the mass changes).
- "draw that again bigger" -> referential (no setup at all here, purely a reference to what came before).
- "also, a 2 kg ball hangs from a 1.5 m string at 30 degrees, what's the tension? by the way what was the answer to the last one" -> self_contained (a full new problem is stated in this message, even though old context is also mentioned).

Return ONLY the JSON object. No prose."""


DIRECT_TUTOR_PROMPT = """You are a warm, knowledgeable TA for 2D dynamics (particles and rigid bodies). You handle messages that are NOT full problems to solve. You will be told the route.

You receive:
- route: one of CONCEPT, SMALLTALK, OUT_OF_SCOPE
- the student's message

Behavior by route:
- CONCEPT: Answer the conceptual dynamics question directly and correctly, briefly (2-5 sentences). A small example is fine. Write any math using LaTeX delimiters (see MATHEMATICAL FORMATTING below). Do NOT solve a full numeric problem.
- SMALLTALK: Respond briefly and warmly. If asked what you can do, say you help with 2D dynamics: free-body diagrams, kinematics (position, velocity, acceleration), and kinetics (Newton's second law, work-energy, impulse-momentum). Mention you can also generate practice problems on request.
- OUT_OF_SCOPE: Gently explain this is outside 2D dynamics (e.g. it's 3D, involves deformation/stress, or fluids/thermo), and offer a dynamics version instead. Do not attempt it.

IF COURSE DOCUMENTS ARE ATTACHED: the student has attached material to this
message. Answer from it when it's relevant, even on a CONCEPT or SMALLTALK
route. If they ask a vague question like "what is this about", they most
likely mean the attached document — answer about the document, not about
yourself.

IMPORTANT: The system CAN render diagrams. Never tell the student you can't draw. If they ask for a diagram, tell them to ask directly (e.g. "draw the free-body diagram") and it will be sketched.
TONE: Warm but not saccharine. A knowledgeable TA, not a cheerleader. Plain prose. Brief.

Return only your response to the student. No JSON. No meta-commentary."""


# Give the two user-facing response agents one consistent math-formatting
# contract (single source of truth in MATH_FORMATTING above).
DIRECT_TUTOR_PROMPT = DIRECT_TUTOR_PROMPT + MATH_FORMATTING
CONVERSATIONALIST_PROMPT = CONVERSATIONALIST_PROMPT + MATH_FORMATTING


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
        # Every agent method below calls self.client.messages.create/stream —
        # wrapping it here is the one place real per-call token usage (item 2
        # of the pilot hardening pass) is logged and the daily spending limit
        # enforced, without touching any individual agent method. Tests
        # replace self.client wholesale with a fake AFTER construction, so
        # this wrapper is never in the way of a mocked test.
        self.usage_tracker = DailyUsageTracker()
        self.client = UsageTrackingClient(
            anthropic.Anthropic(api_key=api_key), self.usage_tracker
        )
        self.memory = SessionMemory()

    # -----------------------------------------------------------------------
    # Individual agents
    # -----------------------------------------------------------------------

    def input_parser(self, message: str, conversation_history: list) -> dict:
        history_text = _format_history(conversation_history)
        user_content = f"Conversation so far:\n{history_text}\n\nStudent's latest message:\n{message}"

        response = self.client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=1024,
            temperature=0,
            system=INPUT_PARSER_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(extract_text(response))



    def router(self, message: str, conversation_history: list) -> dict:
        history_text = _format_history(conversation_history)
        user_content = f"Conversation so far:\n{history_text}\n\nStudent's latest message:\n{message}"
        response = self.client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=256,
            temperature=0,
            system=ROUTER_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(extract_text(response))

    def direct_tutor(self, message: str, route: str,
                     conversation_history: list | None = None) -> str:
        convo = _conversation_block(conversation_history or [])
        user_content = f"Route: {route}\n\n{convo}Current student message:\n{message}"
        response = self.client.messages.create(
            model=SONNET_MODEL,
            max_tokens=1400,
            system=DIRECT_TUTOR_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return extract_text(response)
      
      
      
      
    def creator(self, message: str, conversation_history: list) -> dict:
        history_text = _format_history(conversation_history)
        user_content = (
            f"Conversation so far:\n{history_text}\n\n"
            f"Student's request:\n{message}"
        )
        response = self.client.messages.create(
            model=OPUS_MODEL,
            max_tokens=2048,
            system=CREATOR_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(extract_text(response))
      
      
      
      


    def student_modeler(self, parsed_input: dict, student_model: dict, conversation_history: list) -> dict:
        user_content = (
            f"Parsed problem input:\n{json.dumps(parsed_input, indent=2)}\n\n"
            f"Current student model:\n{json.dumps(student_model, indent=2)}\n\n"
            f"Conversation history:\n{_format_history(conversation_history)}"
        )
        response = self.client.messages.create(
            model=SONNET_MODEL,
            max_tokens=1400,
            # claude-sonnet-5 also runs adaptive thinking on by default when
            # `thinking` is omitted (see response_utils.py's module docstring
            # and the visualizer() call above) — the observed truncation
            # ("Unterminated string" at char 491, well under what 1400 output
            # tokens of pure JSON would allow) is consistent with most of the
            # budget going to an invisible thinking block before the JSON
            # even starts. The output schema itself (concept_mastery floats,
            # a short misconception list, a few strings) comfortably fits
            # well under 1400 tokens on its own — the fix is capping thinking
            # spend, not raising max_tokens further. "low" effort: this is
            # incremental classification/tracking against a fixed rubric, not
            # open-ended reasoning.
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},
            system=STUDENT_MODELER_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(extract_text(response))

    def _student_modeler_safe(self, parsed_input: dict, student_model: dict,
                               conversation_history: list, *, fallback: dict) -> dict:
        """student_modeler(), but a parse failure (e.g. JSON truncated mid
        string) falls back to ``fallback`` instead of propagating the
        {"parse_error": ...} dict. That dict is not a valid student model —
        letting it flow into updated_student_model would silently wipe every
        mastered/struggling concept the student has actually earned, on
        nothing more than one bad Sonnet response. Never let a transient
        parse failure erase real state."""
        result = self.student_modeler(parsed_input, student_model, conversation_history)
        if "parse_error" in result:
            logger.warning(
                "student_modeler returned parse_error; keeping previous value instead "
                "of overwriting it with the failed response"
            )
            return fallback
        return result

    def pedagogical_planner(self, parsed_input: dict, student_model: dict, conversation_history: list, raw_message: str = "") -> dict:
        user_content = (
            f"Student's raw message: {raw_message}\n\n"
            f"Parsed problem input:\n{json.dumps(parsed_input, indent=2)}\n\n"
            f"Student model:\n{json.dumps(student_model, indent=2)}\n\n"
            f"Conversation history:\n{_format_history(conversation_history)}"
        )
        response = self.client.messages.create(
            model=OPUS_MODEL,
            max_tokens=512,
            system=PEDAGOGICAL_PLANNER_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(extract_text(response))

    def solver(self, parsed_input: dict) -> dict:
        user_content = f"Problem to solve:\n{json.dumps(parsed_input, indent=2)}"
        response = self.client.messages.create(
            model=SONNET_MODEL,
            max_tokens=2700,
            system=SOLVER_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(extract_text(response))

    def validator(self, parsed_input: dict, solution: dict) -> dict:
        user_content = (
            f"Original problem:\n{json.dumps(parsed_input, indent=2)}\n\n"
            f"Solver's solution:\n{json.dumps(solution, indent=2)}"
        )
        response = self.client.messages.create(
            model=SONNET_MODEL,
            max_tokens=1400,
            system=VALIDATOR_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(extract_text(response))


    
    def visualizer(self, parsed_input: dict, solution: dict | None) -> str:
        """Draw the problem directly as an SVG string (no separate renderer).

        Returns the extracted SVG markup (<svg ... </svg>), or "" if the
        response was truncated or didn't contain a parseable <svg> element.
        """
        user_content = (
            f"Parsed problem:\n{json.dumps(parsed_input, indent=2)}\n\n"
            f"Solver solution:\n{json.dumps(solution, indent=2)}"
        )
        response = self.client.messages.create(
            model=VISUALIZER_MODEL,
            max_tokens=16000,
            # No temperature: claude-opus-5(.5) rejects the parameter outright
            # ("`temperature` is deprecated for this model", HTTP 400), the
            # same reason it was dropped from the Sonnet calls in 66c8e7c.
            # Layout determinism comes from the explicit LAYOUT PROCESS in
            # VISUALIZER_PROMPT instead.
            #
            # thinking/effort: claude-opus-5-5 runs adaptive thinking
            # ALWAYS ON — unlike Opus 5, `{"type": "disabled"}` is a 400 at
            # every effort level on 5.5, so "adaptive" here isn't a choice
            # among several, it's the only accepted value (omitting the
            # field is equivalent). Thinking tokens still count against
            # max_tokens on 5.5 exactly as they did on Opus 5 — that's what
            # made this call flaky at stop_reason == "max_tokens" in the
            # first place, and the fix is the same: control thinking depth
            # with effort, not by trying to turn it off. "medium" already
            # matches 5.5's own default (Opus 5's default was "high") and is
            # Anthropic's documented starting point for 5.5 — its own
            # testing has medium on 5.5 matching or beating Opus 5's high on
            # comparable generation tasks, using fewer tokens per turn.
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            system=VISUALIZER_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        # getattr(response, "usage", None) first, not just getattr(response.usage,
        # ...): a response missing .usage entirely (some test doubles) would
        # otherwise raise here on the *outer* attribute before the inner
        # getattr's default ever applies.
        output_tokens = getattr(getattr(response, "usage", None), "output_tokens", "?")
        block_types = [getattr(b, "type", "?") for b in response.content]
        logger.info(
            "visualizer response: stop_reason=%s output_tokens=%s block_types=%s",
            response.stop_reason, output_tokens, block_types,
        )
        if response.stop_reason == "max_tokens":
            logger.warning(
                "visualizer response truncated (stop_reason=max_tokens, "
                "output_tokens=%s); discarding output",
                output_tokens,
            )
            return ""
        text = extract_text(response)
        match = _SVG_RE.search(text)
        if not match:
            snippet = text[:200].replace("\n", "\\n")
            logger.warning("visualizer response contained no <svg> element. First 200 chars: %r", snippet)
            return ""
        svg = match.group(0)

        # Deterministic backstop: Opus plans label placement from a text-only
        # spec and cannot self-check bounding boxes, so nudge any colliding
        # labels apart before this ever reaches a student. Never let this
        # pass break a diagram it was only supposed to improve.
        try:
            svg = fix_label_collisions(svg)
        except Exception:
            logger.warning("fix_label_collisions raised; returning unfixed SVG", exc_info=True)
        return svg
    
    
    def schematic_layout(self, parsed_input: dict, solution: dict | None) -> dict:
        user_content = (
            f"Parsed problem:\n{json.dumps(parsed_input, indent=2)}\n\n"
            f"Solver solution (may be null):\n{json.dumps(solution, indent=2)}"
        )
        response = self.client.messages.create(
            model=SONNET_MODEL,
            max_tokens=2000,
            system=SCHEMATIC_LAYOUT_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_json(extract_text(response))
    
    
        
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
            model=SONNET_MODEL,
            max_tokens=4000,
            system=DIAGRAM_RENDERER_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        code = extract_text(response).strip()

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
        conversation_history: list | None = None,
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
        # If the Planner targeted a specific misconception, give the
        # Conversationalist ONE short, grounded remediation snippet from
        # docs/misconceptions.md instead of it improvising an explanation
        # from a bare id string. Omitted entirely (not an empty key) when
        # there's no target or no matching entry, so a normal turn's context
        # bundle is unchanged from before this item.
        guidance = remediation_for(plan.get("target_misconception") if plan else None)
        if guidance:
            context_bundle["misconception_guidance"] = guidance
        convo = _conversation_block(conversation_history or [])
        user_content = f"{convo}Context bundle:\n{json.dumps(context_bundle, indent=2)}"
        response = self.client.messages.create(
            model=SONNET_MODEL,
            max_tokens=2700,
            system=CONVERSATIONALIST_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return extract_text(response)

    # -----------------------------------------------------------------------
    # Main pipeline
    # -----------------------------------------------------------------------

    def _load_student_model_if_empty(self, student_model: dict, student_id: str) -> dict:
        """Pilot item 4 — "the tutor remembers you": on a fresh session the
        frontend always starts studentModel at {}, so an empty incoming
        model means load whatever was saved for this student last time.
        A non-empty incoming model (mid-conversation, already loaded once)
        is trusted as-is — never overwritten mid-session. A failed load
        falls back to {} (get_student_model already guarantees that, see
        agents/memory.py) rather than raising."""
        if student_model:
            return student_model
        try:
            loaded = self.memory.get_student_model(student_id)
        except Exception:
            return {}
        return loaded or {}

    def run(self, message: str, conversation_history: list, student_model: dict,
            session_id: str | None = None, student_id: str | None = None,
            hint_level: int | None = None) -> dict:
        """
        Orchestrate one tutoring turn with file-based session memory.

        Never raises to the caller: on repeated solver/validator failure or any
        unexpected error, returns the best available response with
        ``low_confidence=True``. Each agent's output is logged under
        ``traces/{session_id}/`` and the student model is persisted to
        ``state/{student_id}.json`` at the end of every turn.

        hint_level (pilot item 7): when set (1-4), this is an explicit
        Hint-button tap, not a message needing the Router/Planner's own
        judgment — see _run_turn for how it's handled deterministically.
        """
        session_id = session_id or _new_session_id()
        student_id = student_id or "default"
        student_model = self._load_student_model_if_empty(student_model, student_id)
        turn_number = sum(1 for m in conversation_history if m.get("role") == "user")

        try:
            self.memory.create_session(session_id)
        except Exception:
            pass

        try:
            result = self._run_turn(
                message, conversation_history, student_model,
                session_id, student_id, turn_number, hint_level=hint_level,
            )
        except DailyLimitReached:
            # Caught specifically, before the generic handler below, so the
            # student sees the friendly "resting" message rather than the
            # generic "unexpected problem" one — no API call was made.
            result = {
                "response": DAILY_LIMIT_MESSAGE,
                "updated_student_model": student_model,
                "plan": {"decision": "RESTING"},
                "solution": None,
                "validation": None,
                "visualization": None,
                "diagram_image": "",
                "parsed_input": None,
                "route": "PROBLEM",
                "route_decision": None,
                "low_confidence": False,
            }
        except Exception as exc:  # never propagate an error to the student
            try:
                self.memory.log_error(
                    session_id,
                    error=f"unhandled pipeline exception: {exc!r}",
                    fix_attempted="none",
                    success=False,
                )
            except Exception:
                pass
            result = {
                "response": ("I ran into an unexpected problem working through that. "
                             "Could you rephrase it or add a bit more detail?"),
                "updated_student_model": student_model,
                "plan": {"decision": "ERROR"},
                "solution": None,
                "validation": None,
                "visualization": None,
                "diagram_image": "",
                "parsed_input": None,
                "route": "PROBLEM",
                "route_decision": None,
                "low_confidence": True,
            }

        # Persist the student model at the end of every turn.
        try:
            self.memory.save_student_model(
                student_id, result.get("updated_student_model", student_model)
            )
        except Exception:
            pass

        result.setdefault("low_confidence", False)
        # Guarantee a non-None route so downstream consumers (e.g. the /tutor
        # response model, which types route as str) never receive None. Any
        # error path that could not determine a route defaults to "PROBLEM".
        if result.get("route") is None:
            result["route"] = "PROBLEM"
        result["session_id"] = session_id
        result["turn_number"] = turn_number
        return result

    def _run_turn(self, message: str, conversation_history: list, student_model: dict,
                  session_id: str, student_id: str, turn_number: int,
                  hint_level: int | None = None) -> dict:
        """
        Router-as-orchestrator. The Router classifies the message, then the MCO
        dispatches one of five route-specific agent pipelines. Every agent's
        output is logged to session memory as it completes.

        Routes:
          PROBLEM             Input Parser -> Student Modeler -> Pedagogical Planner
                              -> (if SOLVE: Solver[retry] -> Validator -> Visualizer)
                              -> Conversationalist
          CREATE              Student Modeler (Modeler) -> Pedagogical Planner
                              -> Student Modeler (Identifier: misconceptions)
                              -> Creator -> Visualizer -> Validator
                              -> Conversationalist
          DRAW                Input Parser -> Visualizer -> Schematic Layout
                              -> Validator[retry] -> Conversationalist
          CONCEPT/SMALLTALK   Direct Tutor (single agent)
          OUT_OF_SCOPE        Direct Tutor (explains the scope limitation)

        hint_level (pilot item 7): an explicit Hint-button tap. This is
        known structurally, not something the Router needs to (or reliably
        could) infer from message text, so it forces route=PROBLEM and skips
        the Router call outright — one fewer API call, and no risk of the
        Router misclassifying a plain "can I get a hint?"-style message.
        """
        turn_record: dict = {"participant_code": student_id, "message": message,
                             "hint_level": hint_level, "agents": {}}

        def _log(agent_name: str, output) -> None:
            # Accumulate into a single {turn}.json, rewritten after each agent.
            turn_record["agents"][agent_name] = output
            try:
                self.memory.log_turn(session_id, turn_number, turn_record)
            except Exception:
                pass

        # 0. Router classifies the message. Log the route decision to memory
        #    BEFORE the MCO dispatches to any downstream pipeline.
        if hint_level is not None:
            route_decision = {
                "route": "PROBLEM",
                "rationale": "Hint ladder button — route forced, Router not called.",
                "confidence": 1.0,
            }
        else:
            route_decision = self.router(message, conversation_history)
        route = route_decision.get("route", "PROBLEM")
        turn_record["route"] = route
        _log("router", route_decision)

        # ---------- CONCEPT / SMALLTALK / OUT_OF_SCOPE: single Direct Tutor ----------
        if route in ("CONCEPT", "SMALLTALK", "OUT_OF_SCOPE"):
            response_text = self.direct_tutor(message, route, conversation_history)
            _log("direct_tutor", {"response": response_text})
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
                "low_confidence": False,
            }

        # ---------- DRAW: Input Parser -> Visualizer (SVG)
        #            -> Conversationalist ----------
        if route == "DRAW":
            if _draw_needs_clarification(route_decision, conversation_history):
                _log("draw_clarify", {"response": DRAW_NEEDS_CLARIFICATION_MESSAGE})
                return {
                    "response": DRAW_NEEDS_CLARIFICATION_MESSAGE,
                    "updated_student_model": student_model,
                    "plan": {"decision": "CLARIFY"},
                    "solution": None,
                    "validation": None,
                    "visualization": None,
                    "diagram_image": "",
                    "parsed_input": None,
                    "route": route,
                    "route_decision": route_decision,
                    "low_confidence": False,
                }
            parsed_input = self.input_parser(
                message, _draw_history(route_decision, conversation_history)
            )
            _log("input_parser", parsed_input)

            # A failed parse must not be handed to the visualizer — it can
            # only guess at a diagram from a broken {"parse_error": ...,
            # "raw_response": ...} dict, which is worse than no diagram at
            # all. Skip drawing; svg_ok stays False, which is the same
            # signal already used for a genuinely failed visualizer call.
            if "parse_error" in parsed_input:
                logger.warning(
                    "input_parser failed to parse the DRAW request; skipping visualizer"
                )
                diagram_svg = ""
                svg_ok = False
            else:
                diagram_svg = self.visualizer(parsed_input, None)
                _log("visualizer", diagram_svg)
                # The visualizer now returns SVG directly, so validation is a
                # light non-empty / well-formed check rather than
                # FBD-structure checking.
                svg_ok = _svg_is_valid(diagram_svg)
            validation = {
                "task": "VALIDATE_SVG",
                "non_empty": bool(diagram_svg.strip()),
                "well_formed": svg_ok,
                "overall_verdict": "PASS" if svg_ok else "FAIL",
            }
            _log("validator", validation)
            low_confidence = not svg_ok

            plan = {"decision": "DRAW"}
            response_text = self.conversationalist(
                student_message=message,
                parsed_input=parsed_input,
                student_model=student_model,
                plan=plan,
                solution=None,
                validation=validation,
                visualization=_diagram_status(svg_ok),
                conversation_history=conversation_history,
            )
            _log("conversationalist", {"response": response_text})
            return {
                "response": response_text,
                "updated_student_model": student_model,  # unchanged: modeler did not run
                "plan": plan,
                "solution": None,
                "validation": validation,
                "visualization": diagram_svg,
                "diagram_svg": diagram_svg if svg_ok else "",
                "parsed_input": parsed_input,
                "route": route,
                "route_decision": route_decision,
                "low_confidence": low_confidence,
            }

        # ---------- CREATE: Modeler -> Planner -> Identifier (Student Modeler
        #            again for misconceptions) -> Creator -> Visualizer
        #            -> Validator -> Conversationalist ----------
        if route == "CREATE":
            # No Input Parser on this route; give the modeler/planner minimal context.
            create_context = {"route": "CREATE", "request": message}

            # 1. Modeler: build/refresh the overall student model.
            updated_student_model = self._student_modeler_safe(
                create_context, student_model, conversation_history, fallback=student_model
            )
            _log("student_modeler", updated_student_model)

            # 2. Planner: decide the pedagogical approach for the CREATE request.
            plan = self.pedagogical_planner(
                create_context, updated_student_model, conversation_history, raw_message=message
            )
            _log("pedagogical_planner", plan)

            # 3. Identifier: run the Student Modeler a SECOND time, focused (via the
            #    input payload, so the agent method itself stays unchanged) on
            #    surfacing this student's specific misconceptions and struggling
            #    concepts so the Creator can target them.
            identifier_context = {
                "route": "CREATE",
                "request": message,
                "task": "IDENTIFY_MISCONCEPTIONS",
                "focus": (
                    "Identify this specific student's concrete misconceptions and the "
                    "particular concepts they are struggling with. Return them explicitly "
                    "so targeted practice problems can be generated to address them."
                ),
                "plan": plan,
            }
            misconceptions = self._student_modeler_safe(
                identifier_context, updated_student_model, conversation_history, fallback={}
            )
            _log("identifier", misconceptions)

            # 4. Creator: generate practice problems, passing the identified
            #    misconceptions explicitly (via the message arg, keeping creator()'s
            #    signature unchanged) so the problems target them.
            creator_message = (
                f"{message}\n\n"
                f"[STUDENT MODEL — overall picture of this student]\n"
                f"{json.dumps(updated_student_model, indent=2, default=str)}\n\n"
                f"[MISCONCEPTIONS & STRUGGLING CONCEPTS — target the generated practice "
                f"problems directly at these]\n"
                f"{json.dumps(misconceptions, indent=2, default=str)}"
            )
            created = self.creator(creator_message, conversation_history)
            _log("creator", created)

            # 5. Visualizer: draw the Creator's output directly as SVG.
            diagram_svg = self.visualizer(create_context, created)
            _log("visualizer", diagram_svg)
            svg_ok = _svg_is_valid(diagram_svg)

            # 6. Validator: validate the Creator's problems only. The visualizer
            #    now returns SVG (not structured JSON), so FBD-structure
            #    validation no longer applies.
            validation = self.validator(
                create_context,
                {"created_problems": created},
            )
            _log("validator", validation)
            verdict = (validation.get("overall_verdict")
                       or validation.get("solver_verdict")
                       or "UNCERTAIN")
            low_confidence = verdict == "FAIL"

            # 7. Conversationalist: compose the student-facing response.
            response_text = self.conversationalist(
                student_message=message,
                parsed_input=create_context,
                student_model=updated_student_model,
                plan=plan,
                solution=created,
                validation=validation,
                visualization=_diagram_status(svg_ok),
                conversation_history=conversation_history,
            )
            _log("conversationalist", {"response": response_text})
            return {
                "response": response_text,
                "updated_student_model": updated_student_model,
                "plan": {
                    "decision": "CREATE",
                    "planner": plan,
                    "misconceptions": misconceptions,
                    "created_problems": created,
                },
                "solution": created,
                "validation": validation,
                "visualization": diagram_svg,
                "diagram_svg": diagram_svg if svg_ok else "",
                "parsed_input": create_context,
                "route": route,
                "route_decision": route_decision,
                "low_confidence": low_confidence,
            }

        # ---------- PROBLEM (default): Input Parser -> Student Modeler -> Pedagogical
        #            Planner -> (if SOLVE: Solver[retry] -> Validator -> Visualizer)
        #            -> Conversationalist ----------
        parsed_input = self.input_parser(message, conversation_history)
        _log("input_parser", parsed_input)

        updated_student_model = self._student_modeler_safe(
            parsed_input, student_model, conversation_history, fallback=student_model
        )
        _log("student_modeler", updated_student_model)

        if hint_level is not None:
            plan = _hint_ladder_plan(hint_level, parsed_input)
            if hint_level == 3:
                plan = self._with_worked_step(plan, parsed_input)
        else:
            plan = self.pedagogical_planner(parsed_input, updated_student_model, conversation_history, raw_message=message)
        _log("pedagogical_planner", plan)

        solution = None
        validation = None
        visualization = None
        diagram_svg = ""
        svg_ok = False
        low_confidence = False

        if plan.get("decision") == "SOLVE":
            solution, validation, low_confidence = self._solve_with_retries(
                parsed_input, session_id, turn_number, _log
            )
            visualization = self.visualizer(parsed_input, solution)
            _log("visualizer", visualization)
            svg_ok = _svg_is_valid(visualization)
            diagram_svg = visualization if svg_ok else ""

        response_text = self.conversationalist(
            student_message=message,
            parsed_input=parsed_input,
            student_model=updated_student_model,
            plan=plan,
            solution=solution,
            validation=validation,
            visualization=_diagram_status(svg_ok),
            conversation_history=conversation_history,
        )
        _log("conversationalist", {"response": response_text})

        return {
            "response": response_text,
            "updated_student_model": updated_student_model,
            "plan": plan,
            "solution": solution,
            "validation": validation,
            "visualization": visualization,
            "diagram_svg": diagram_svg if plan.get("decision") == "SOLVE" else "",
            "parsed_input": parsed_input,
            "route": route,
            "route_decision": route_decision,
            "low_confidence": low_confidence,
        }

    def solution_for_work_check(self, parsed_input: dict) -> dict | None:
        """Solver answers for /check-work (pilot item 9). Reuses the
        solution a SOLVE turn already cached for this exact problem; only
        otherwise spends one solver + one validator call, and caches the
        result so later checks of the same problem are free. A solution
        that fails validation is not used — a wrong reference answer would
        mark a student's correct line wrong."""
        cached = solution_cache.get(parsed_input)
        if cached is not None:
            return cached
        solution = self.solver(parsed_input)
        validation = self.validator(parsed_input, solution)
        if _verdict(validation) == "FAIL":
            return None
        solution_cache.remember(parsed_input, solution)
        return solution_cache.get(parsed_input)

    def _with_worked_step(self, plan: dict, parsed_input: dict) -> dict:
        """Hint level 3 ("one worked step"): attach one intermediate step,
        with its value, for the conversationalist to carry out. The solution
        comes from the cache when a SOLVE or /check-work already produced it,
        otherwise from one solver + validator call (cached for later). Only
        the chosen step reaches the conversationalist — never the solution
        or its final answers. Any failure (validation FAIL, solver error, no
        usable step) leaves the plain level-3 text hint in place."""
        try:
            solution = solution_cache.get(parsed_input)
            if solution is None:
                solution = self.solver(parsed_input)
                if _verdict(self.validator(parsed_input, solution)) == "FAIL":
                    return plan
                solution_cache.remember(parsed_input, solution)
        except DailyLimitReached:
            raise
        except Exception:
            logger.warning("worked step: solver unavailable; using the text hint", exc_info=True)
            return plan
        step = _pick_worked_step(solution)
        if step is None:
            return plan
        return {**plan, "payload": {**plan.get("payload", {}), "worked_step": step}}

    # Retry the Solver at most this many times when the Validator returns FAIL.
    MAX_SOLVER_ATTEMPTS = 3

    def _solve_with_retries(self, parsed_input: dict, session_id: str,
                            turn_number: int, log) -> tuple:
        """
        Solve then validate, retrying the Solver (up to ``MAX_SOLVER_ATTEMPTS``)
        whenever the Validator returns FAIL, injecting the validation errors into
        each retry. Returns ``(solution, validation, low_confidence)``.
        """
        solver_input = parsed_input
        solution = None
        validation = None

        for attempt in range(1, self.MAX_SOLVER_ATTEMPTS + 1):
            solution = self.solver(solver_input)
            log(f"solver_attempt_{attempt}", solution)

            validation = self.validator(parsed_input, solution)
            log(f"validator_attempt_{attempt}", validation)

            verdict = (validation.get("overall_verdict")
                       or validation.get("solver_verdict")
                       or "UNCERTAIN")
            if verdict != "FAIL":
                solution_cache.remember(parsed_input, solution)
                return solution, validation, False

            errors = validation.get("errors_found", [])
            is_last = attempt >= self.MAX_SOLVER_ATTEMPTS
            try:
                self.memory.log_error(
                    session_id,
                    error={"attempt": attempt, "verdict": verdict, "errors_found": errors},
                    fix_attempted=("exhausted retries; returning best attempt"
                                   if is_last else
                                   "re-running solver with validation errors injected"),
                    success=False,
                )
            except Exception:
                pass

            if is_last:
                break

            # Immutable copy: feed the validation errors back into the next solve.
            solver_input = {
                **parsed_input,
                "validation_feedback": {
                    "previous_attempt": attempt,
                    "errors_found": errors,
                    "instruction": ("Your previous solution failed independent "
                                    "validation. Fix these specific errors and re-solve."),
                },
            }

        # All attempts failed validation → best attempt, flagged low-confidence.
        return solution, validation, True

    def run_stream(self, message: str, conversation_history: list, student_model: dict,
                   source_text: str = "", session_id: str | None = None,
                   student_id: str | None = None, hint_level: int | None = None):
        """Streaming variant of run() — with the same server-side memory
        guarantee as run(): every turn logged, the student model saved.

        hint_level (pilot item 7): an explicit Hint-button tap — see
        _run_stream_events for how it's handled deterministically.

        Thin wrapper around _run_stream_events(): forwards every event
        untouched while watching the stream for the pieces run() logs
        per-agent via _log() — the final student_model (from whichever
        "meta" event carries it), route/decision, and the streamed response
        text. _run_stream_events() itself never touches self.memory, so this
        is the ONE place a streamed turn is journaled; unlike run()'s
        _run_turn(), which re-logs a growing turn_record after every agent,
        this logs a single consolidated record once the turn ends (normally
        or via a caught exception) — coarser than run()'s per-agent trace,
        but every turn is still captured and the student model is still
        saved, which is what matters for research data. See docs/pilot-plan.md.
        """
        session_id = session_id or _new_session_id()
        student_id = student_id or "default"
        student_model = self._load_student_model_if_empty(student_model, student_id)
        turn_number = sum(1 for m in conversation_history if m.get("role") == "user")

        try:
            self.memory.create_session(session_id)
        except Exception:
            pass

        final_student_model = student_model
        route = None
        decision = None
        diagram_svg = ""
        response_parts: list[str] = []
        error_text: str | None = None

        try:
            for event in self._run_stream_events(
                message, conversation_history, student_model, source_text,
                hint_level=hint_level,
            ):
                etype = event.get("type")
                if etype == "meta":
                    final_student_model = event.get("student_model", final_student_model)
                    route = event.get("route", route)
                    decision = event.get("decision", decision)
                    diagram_svg = event.get("diagram_svg", diagram_svg)
                elif etype == "token":
                    response_parts.append(event.get("text", ""))
                elif etype == "error":
                    error_text = event.get("text")
                yield event
        except DailyLimitReached:
            # Not an error — a normal-looking reply (meta + token + done),
            # same shape as any other successful turn, so the frontend needs
            # no special case for it. No API call was made this turn.
            decision = "RESTING"
            response_parts = [DAILY_LIMIT_MESSAGE]
            yield {"type": "meta", "student_model": final_student_model,
                   "route": route or "PROBLEM", "decision": "RESTING", "diagram_svg": ""}
            yield {"type": "token", "text": DAILY_LIMIT_MESSAGE}
            yield {"type": "done"}
        except Exception as exc:  # never propagate an error to the student
            try:
                self.memory.log_error(
                    session_id,
                    error=f"unhandled run_stream exception: {exc!r}",
                    fix_attempted="none",
                    success=False,
                )
            except Exception:
                pass
            error_text = (
                "I ran into an unexpected problem working through that. "
                "Could you rephrase it or add a bit more detail?"
            )
            yield {"type": "error", "text": error_text}
            yield {"type": "done"}
        finally:
            try:
                # participant_code is the only identity saved: the pilot's
                # anonymous code, never a name (see participants.py).
                self.memory.log_turn(session_id, turn_number, {
                    "participant_code": student_id,
                    "student_message": message,
                    "hint_level": hint_level,
                    "route": route,
                    "decision": decision,
                    "response_text": "".join(response_parts),
                    "diagram_rendered": bool(diagram_svg),
                    "error": error_text,
                })
            except Exception:
                pass
            try:
                self.memory.save_student_model(student_id, final_student_model)
            except Exception:
                pass

    def _run_stream_events(self, message: str, conversation_history: list, student_model: dict,
                   source_text: str = "", hint_level: int | None = None):
        """Streaming variant of run()'s pipeline. Generator yielding event dicts:
            {"type":"status","text":...}  progress during the silent pipeline phase
            {"type":"meta", ...}          one-shot: student_model, route, decision, diagram_image
            {"type":"token","text":...}   incremental text of the final agent
            {"type":"done"}
        Only the FINAL agent is streamed; upstream agents return JSON we need whole,
        so we emit status lines while they run. NOTE: mirrors run()'s control flow —
        keep the two in sync until we refactor the shared part out (tech debt).
        Never touches self.memory directly — run_stream() (the public wrapper
        above) is the one place a streamed turn is journaled.

        hint_level (pilot item 7): an explicit Hint-button tap, forces
        route=PROBLEM and skips the Router call — see _run_turn for the
        matching (non-streaming) logic and full rationale."""
        # Text from documents the student attached to this turn. When empty,
        # source_block is "" and every path below is unchanged.
        source_block = ""
        if source_text and source_text.strip():
            source_block = (
                "\n\n[COURSE DOCUMENTS ATTACHED BY THE STUDENT]\n"
                "Treat this material as the authoritative source for this turn. "
                "Prefer its notation, methods, and worked examples over your own. "
                "If it conflicts with what you would otherwise say, follow the "
                "documents and say so. Content grounded in these documents is not "
                "invented content — you may use it freely. Never repeat a "
                "person's name or other personal details that appear in these "
                "documents: conversations are saved for research.\n"
                f"{source_text}\n"
                "[END COURSE DOCUMENTS]"
            )

        if hint_level is not None:
            route_decision = {
                "route": "PROBLEM",
                "rationale": "Hint ladder button — route forced, Router not called.",
                "confidence": 1.0,
            }
        else:
            route_decision = self.router(message, conversation_history)
        route = route_decision.get("route", "PROBLEM")

        # Labeled prior-conversation block, injected into the FINAL response
        # agents (direct_tutor + conversationalist) so the reply has
        # current-conversation memory. Empty string when there is no history.
        convo = _conversation_block(conversation_history)

        if route == "DRAW":
            wants_multi = any(w in message.lower() for w in ("these", "them", "those", "all", "each"))
            created_problems = _find_recent_created(conversation_history)
            if wants_multi and created_problems:
                # Draw each created problem directly as SVG (unsolved) and
                # concatenate the markup — multiple <svg> blocks render stacked.
                svgs = []
                for p in created_problems:
                    stmt = p.get("statement", "")
                    if not stmt:
                        continue
                    parsed_p = self.input_parser(stmt, [])
                    if "parse_error" in parsed_p:
                        logger.warning(
                            "input_parser failed to parse a created problem for DRAW; "
                            "skipping visualizer for it"
                        )
                        continue
                    svg_p = self.visualizer(parsed_p, None)
                    if _svg_is_valid(svg_p):
                        svgs.append(svg_p)
                if svgs:
                    yield {"type": "meta", "student_model": student_model, "route": route,
                           "decision": "DRAW", "diagram_svg": "\n".join(svgs)}
                    yield {"type": "token", "text": ("Here are the setups for each problem, drawn "
                            "unsolved so you can work them yourself. Notice the forces on each.")}
                    yield {"type": "done"}
                    return

            if _draw_needs_clarification(route_decision, conversation_history):
                yield {"type": "meta", "student_model": student_model, "route": route,
                       "decision": "CLARIFY", "diagram_svg": ""}
                yield {"type": "token", "text": DRAW_NEEDS_CLARIFICATION_MESSAGE}
                yield {"type": "done"}
                return

            # Single-diagram DRAW mirrors run(): Input Parser -> Visualizer (SVG)
            # -> Conversationalist. The visualizer draws SVG directly.
            yield {"type": "status", "text": "Sketching the setup…"}
            parsed_input = self.input_parser(
                message + source_block, _draw_history(route_decision, conversation_history)
            )

            # A failed parse must not be handed to the visualizer — see the
            # matching guard in run(). svg_ok stays False (skips drawing)
            # exactly as it would for a genuinely failed visualizer call.
            if "parse_error" in parsed_input:
                logger.warning(
                    "input_parser failed to parse the DRAW request; skipping visualizer"
                )
                diagram_svg = ""
            else:
                diagram_svg = self.visualizer(parsed_input, None)

            # Lightweight non-empty / well-formed SVG check (no FBD-structure
            # validation, since the output is SVG rather than structured JSON).
            svg_ok = _svg_is_valid(diagram_svg)
            validation = {
                "task": "VALIDATE_SVG",
                "non_empty": bool(diagram_svg.strip()),
                "well_formed": svg_ok,
                "overall_verdict": "PASS" if svg_ok else "FAIL",
            }
            logger.info("DRAW visualizer output (svg_ok=%s): %s", svg_ok, diagram_svg[:500])
            logger.info("DRAW validation: %s", validation)

            yield {"type": "meta", "student_model": student_model, "route": route,
                   "decision": "DRAW", "diagram_svg": diagram_svg if svg_ok else ""}

            context_bundle = {
                "student_message": message, "parsed_input": parsed_input,
                "student_model": student_model, "plan": {"decision": "DRAW"},
                "solution": None, "validation": validation, "visualization": _diagram_status(svg_ok),
                "source_documents": source_block,
            }
            user_content = f"{convo}Context bundle:\n{json.dumps(context_bundle, indent=2)}"
            with self.client.messages.stream(
                model=SONNET_MODEL, max_tokens=2700,
                system=CONVERSATIONALIST_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            ) as stream:
                for chunk in stream.text_stream:
                    yield {"type": "token", "text": chunk}
            yield {"type": "done"}
            return


        if route == "CREATE":
            # Mirrors run(): Modeler -> Planner -> Identifier -> Creator
            # -> Visualizer -> Validator -> Conversationalist.
            create_context = {"route": "CREATE", "request": message}

            yield {"type": "status", "text": "Sizing up where you're at…"}
            updated_student_model = self._student_modeler_safe(
                create_context, student_model, conversation_history, fallback=student_model
            )
            plan = self.pedagogical_planner(
                create_context, updated_student_model, conversation_history, raw_message=message
            )

            # Identifier: second Student Modeler pass focused (via the input
            # payload) on this student's specific misconceptions/struggling concepts.
            identifier_context = {
                "route": "CREATE",
                "request": message,
                "task": "IDENTIFY_MISCONCEPTIONS",
                "focus": (
                    "Identify this specific student's concrete misconceptions and the "
                    "particular concepts they are struggling with. Return them explicitly "
                    "so targeted practice problems can be generated to address them."
                ),
                "plan": plan,
            }
            misconceptions = self._student_modeler_safe(
                identifier_context, updated_student_model, conversation_history, fallback={}
            )

            yield {"type": "status", "text": "Writing practice problems…"}
            # Pass the identified misconceptions explicitly into the Creator.
            creator_message = (
                f"{message}\n\n"
                f"[STUDENT MODEL — overall picture of this student]\n"
                f"{json.dumps(updated_student_model, indent=2, default=str)}\n\n"
                f"[MISCONCEPTIONS & STRUGGLING CONCEPTS — target the generated practice "
                f"problems directly at these]\n"
                f"{json.dumps(misconceptions, indent=2, default=str)}"
            )
            created = self.creator(creator_message, conversation_history)

            # Visualizer draws the Creator's output directly as SVG. The
            # Validator checks the created problems only (SVG isn't structured).
            diagram_svg = self.visualizer(create_context, created)
            svg_ok = _svg_is_valid(diagram_svg)
            validation = self.validator(
                create_context,
                {"created_problems": created},
            )

            yield {"type": "meta", "student_model": updated_student_model, "route": route,
                   "decision": "CREATE", "diagram_svg": diagram_svg if svg_ok else ""}

            context_bundle = {
                "student_message": message, "parsed_input": create_context,
                "student_model": updated_student_model, "plan": plan,
                "solution": created, "validation": validation, "visualization": _diagram_status(svg_ok),
                "source_documents": source_block,
            }
            user_content = f"{convo}Context bundle:\n{json.dumps(context_bundle, indent=2)}"
            with self.client.messages.stream(
                model=SONNET_MODEL, max_tokens=2700,
                system=CONVERSATIONALIST_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            ) as stream:
                for chunk in stream.text_stream:
                    yield {"type": "token", "text": chunk}
            yield {"type": "done"}
            return

        if route in ("CONCEPT", "SMALLTALK", "OUT_OF_SCOPE"):
            yield {"type": "meta", "student_model": student_model, "route": route,
                "decision": route, "diagram_svg": ""}
            user_content = f"Route: {route}\n\n{convo}Current student message:\n{message}{source_block}"
            with self.client.messages.stream(
                model=SONNET_MODEL, max_tokens=1400,
                system=DIRECT_TUTOR_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            ) as stream:
                for chunk in stream.text_stream:
                    yield {"type": "token", "text": chunk}
            yield {"type": "done"}
            return

        # PROBLEM path
        yield {"type": "status", "text": "Reading the problem\u2026"}
        parsed_input = self.input_parser(message + source_block, conversation_history)
        updated_student_model = self._student_modeler_safe(
            parsed_input, student_model, conversation_history, fallback=student_model
        )
        if hint_level is not None:
            plan = _hint_ladder_plan(hint_level, parsed_input)
            if hint_level == 3:
                yield {"type": "status", "text": "Working out one step\u2026"}
                plan = self._with_worked_step(plan, parsed_input)
        else:
            plan = self.pedagogical_planner(parsed_input, updated_student_model,
                                            conversation_history,
                                            raw_message=message + source_block)

        solution = validation = visualization = None
        diagram_svg = ""
        svg_ok = False
        if plan.get("decision") == "SOLVE":
            yield {"type": "status", "text": "Solving\u2026"}
            solution = self.solver(parsed_input)
            yield {"type": "status", "text": "Verifying the physics\u2026"}
            validation = self.validator(parsed_input, solution)
            if _verdict(validation) != "FAIL":
                solution_cache.remember(parsed_input, solution)
            yield {"type": "status", "text": "Drawing the diagram\u2026"}
            visualization = self.visualizer(parsed_input, solution)
            svg_ok = _svg_is_valid(visualization)
            diagram_svg = visualization if svg_ok else ""

        # meta BEFORE tokens so the frontend can attach diagram + student_model first.
        # parsed_input/solution are handed back verbatim (item 9's check-work feature
        # needs them to build known_values without any new LLM call — see
        # agents/work_checker.build_known_values) — no new agent call, this is the
        # same data already computed a few lines above for this exact turn.
        yield {"type": "meta", "student_model": updated_student_model, "route": route,
            "decision": plan.get("decision", "UNKNOWN"), "diagram_svg": diagram_svg,
            "parsed_input": parsed_input, "solution": solution}

        context_bundle = {
            "student_message": message, "parsed_input": parsed_input,
            "student_model": updated_student_model, "plan": plan,
            "solution": solution, "validation": validation, "visualization": _diagram_status(svg_ok),
            "source_documents": source_block,
        }
        user_content = f"{convo}Context bundle:\n{json.dumps(context_bundle, indent=2)}"
        with self.client.messages.stream(
            model=SONNET_MODEL, max_tokens=2700,
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

def _new_session_id() -> str:
    """Generate a timestamped, unique session id."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


# Cap on how many recent turns get formatted into any prompt, to keep the
# current-conversation memory from growing the prompt without bound. Only the
# most recent MAX_HISTORY_MESSAGES messages are ever included.
MAX_HISTORY_MESSAGES = 20


# --- DRAW history gating -------------------------------------------------
# A draw request that carries its own problem statement must be parsed on its
# own, with NO conversation history: input_parser prepends the whole
# conversation, so a fresh "2 kg ball on a 1.5 m string" otherwise gets fused
# with the block-on-an-incline from three turns ago and the wrong problem is
# drawn. A referential request ("draw that one", "same thing but 10 kg") has
# the opposite need — the history is the only place the referent (or the rest
# of the setup being tweaked) lives.
#
# The Router already reads the message as an LLM call and classifies intent;
# it carries the "problem_scope" field ("self_contained" | "referential") in
# its JSON output. A regex used to make this call independently, but it had
# no way to tell "a 10 kg block instead" (referential — depends on the
# previous turn for the rest of the setup) from a genuinely new problem that
# happens to share the same shape of words. The Router reads the conversation
# and can tell the difference; a second regex pass over the message alone
# can't.


def _draw_history(route_decision: dict, conversation_history: list) -> list:
    """The history a DRAW request should be parsed against: [] when the
    Router marked the message self_contained, the real history otherwise —
    including when problem_scope is missing or an unrecognized value, since
    an unparseable/incomplete router response must never strip history.
    """
    scope = (route_decision or {}).get("problem_scope")
    if scope == "self_contained":
        return []
    return conversation_history or []


# Pilot item 8 — a referential DRAW request ("draw that", "same thing") with
# NO prior conversation at all has nothing to refer to; input_parser would
# still be handed empty history and the Visualizer would draw *something*,
# necessarily invented. Asking which problem the student means is safer than
# guessing. Deliberately scoped to the cheap, unambiguous case (no history at
# all, e.g. a fresh session) rather than trying to detect "history exists but
# never actually contained a real problem" — that's a fuzzier judgment call
# this deterministic check doesn't attempt.
DRAW_NEEDS_CLARIFICATION_MESSAGE = (
    "Which problem would you like me to draw? I don't have an earlier one in "
    "this conversation to work from — describe it (or paste it again) and "
    "I'll sketch it."
)


def _draw_needs_clarification(route_decision: dict, conversation_history: list) -> bool:
    scope = (route_decision or {}).get("problem_scope")
    return scope == "referential" and not conversation_history


def _format_history(conversation_history: list,
                    max_messages: int = MAX_HISTORY_MESSAGES) -> str:
    """Central formatter for conversation history. Includes only the most
    recent ``max_messages`` turns (oldest are dropped)."""
    if not conversation_history:
        return "(no prior conversation)"
    recent = conversation_history[-max_messages:] if max_messages else conversation_history
    lines = []
    for msg in recent:
        role = msg.get("role", "user").capitalize()
        content = msg.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _conversation_block(conversation_history: list) -> str:
    """Labeled prior-conversation block for the final response agents, clearly
    separated from the current message. Returns "" when there is no history so
    the current message is never preceded by an empty header. Reuses the single
    central formatter (_format_history) — no duplicated formatting logic."""
    if not conversation_history:
        return ""
    return f"Previous conversation:\n{_format_history(conversation_history)}\n\n"
  
  
  
  
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


# Extracts the first <svg>...</svg> element, tolerating code fences, an
# <?xml ?> prolog, or leading prose around it in the model's raw response.
_SVG_RE = re.compile(r"<svg[\s\S]*?</svg>", re.IGNORECASE)


def _verdict(validation) -> str:
    if not isinstance(validation, dict):
        return "UNCERTAIN"
    return (validation.get("overall_verdict")
            or validation.get("solver_verdict")
            or "UNCERTAIN")


def _svg_is_valid(svg: str) -> bool:
    """True if the string looks like a non-empty, well-formed SVG document.

    The visualizer now returns SVG markup directly (rather than a structured
    FBD spec), so validation is a lightweight shape check — non-empty, and
    delimited by <svg ... </svg> — instead of verifying FBD force structure.
    """
    s = (svg or "").strip()
    return bool(s) and s.startswith("<svg") and s.endswith("</svg>")


def _diagram_status(svg_ok: bool) -> dict:
    """Placeholder passed to the conversationalist instead of raw SVG markup,
    so its reply can't echo the diagram code (and burn its max_tokens budget
    on it). It only needs to know whether a diagram was rendered."""
    return {"diagram_rendered": bool(svg_ok)}


# --- Hint ladder (pilot item 7) ---------------------------------------------
# A deliberately simple, linear 3-level ladder per family, distinct from
# PEDAGOGICAL_PLANNER_PROMPT's own richer stage-aware ladder (FBD L1/L2,
# Equations L1/L2, Solving L3) that the LLM planner draws on for its own
# organic HINT decisions. The Hint button needs a plain level 1/2/3 to
# increment through per tap, so this is its own compact, deterministic copy
# rather than trying to force a single number onto the multi-stage prompt
# ladder. Level 4 ("the answer") isn't a hint at all — it routes through the
# existing SOLVE path instead (see _run_turn / _run_stream_events).
_HINT_LADDER: dict[str, list[str]] = {
    "kinetics": [
        "Have you drawn the free-body diagram? What forces act on the body?",
        "On a surface, don't forget the normal force; on an incline, resolve weight "
        "into components along and perpendicular to the surface. Then write "
        "ΣF = ma along each axis you chose.",
        "Worked step: set up ΣF = ma along your chosen axes, substitute the "
        "givens, and solve the one equation that has only a single unknown.",
    ],
    "kinematics": [
        "Is the acceleration constant here? That decides which equations are valid.",
        "If this is a projectile, treat horizontal and vertical motion separately: "
        "a_x = 0, a_y = -g, and they share only time.",
        "Worked step: pick the constant-acceleration equation that links the "
        "quantities you know to the one you want, and substitute in the givens.",
    ],
    "energy_momentum": [
        "What's conserved here — energy, momentum, both, or neither? Does "
        "friction do work? Is there an external impulse?",
        "Set up the conservation equation for this case (KE_i + PE_i + W_nc = "
        "KE_f + PE_f for energy, or momentum before = momentum after per "
        "direction) and identify each term.",
        "Worked step: substitute the known values into the conservation equation "
        "and isolate the unknown.",
    ],
}
_HINT_STAGES = ["fbd", "equations", "solving"]
_DEFAULT_HINT_FAMILY = "kinetics"  # fallback for "unclear"/unrecognized families


def _hint_for_level(family: str, level: int) -> tuple[str, str]:
    """(hint_text, hint_stage) for a 1-3 hint_level, matching
    PEDAGOGICAL_PLANNER_PROMPT's payload.hint_stage vocabulary."""
    ladder = _HINT_LADDER.get(family, _HINT_LADDER[_DEFAULT_HINT_FAMILY])
    idx = min(max(level, 1), 3) - 1
    return ladder[idx], _HINT_STAGES[idx]


def _pick_worked_step(solution) -> dict | None:
    """The first intermediate value that isn't itself a final answer (e.g.
    the normal force when the question asks for acceleration), plus the
    solver's equation for it when one is written as "<symbol> = ...".
    None when every computed value is a final answer — then there's no
    step to show that wouldn't give the answer away."""
    if not isinstance(solution, dict):
        return None
    finals = {a.get("symbol") for a in solution.get("final_answers") or [] if isinstance(a, dict)}
    for item in solution.get("intermediate_values") or []:
        if not isinstance(item, dict) or item.get("symbol") in finals:
            continue
        symbol = item.get("symbol")
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            continue
        if not isinstance(symbol, str) or not symbol:
            continue
        equation = None
        for eq in solution.get("equations") or []:
            if not isinstance(eq, dict):
                continue
            for form in (eq.get("numeric"), eq.get("symbolic")):
                if isinstance(form, str) and re.match(rf"\s*{re.escape(symbol)}\s*=", form):
                    equation = eq.get("symbolic") or form
                    break
            if equation:
                break
        return {"symbol": symbol, "value": round(value, 4), "unit": item.get("unit") or "",
                "description": item.get("description") or "", "equation": equation}
    return None


def _hint_ladder_plan(hint_level: int, parsed_input: dict) -> dict:
    """The Pedagogical Planner's JSON shape, built deterministically instead
    of by the LLM, for an explicit Hint-button tap. Levels 1-3 use the ladder
    above; level 4 ("the answer") is the one place this pilot's hardening
    pass deliberately overrides CONVERSATIONALIST_PROMPT's "HINT: do NOT
    give the answer" rule — by never producing a HINT decision at level 4 at
    all. It's SOLVE, with its own explicit permission_source, so the answer
    flows through the SAME solve-verify-present path (and the same
    VERIFICATION HONESTY rule) an organically-requested solve already does.
    This is what replaces the old behavior of the tutor simply refusing to
    ever give a value after several stuck turns."""
    if hint_level >= 4:
        return {
            "decision": "SOLVE",
            "rationale": "Student worked through the hint ladder (levels 1-3) and asked for the answer.",
            "payload": {"permission_source": "hint_ladder_exhausted"},
            "target_misconception": None,
        }
    family = (parsed_input or {}).get("family") or _DEFAULT_HINT_FAMILY
    hint_text, hint_stage = _hint_for_level(family, hint_level)
    return {
        "decision": "HINT",
        "rationale": f"Hint ladder level {hint_level} (student-requested via the Hint button).",
        "payload": {"hint_text": hint_text, "hint_level": hint_level, "hint_stage": hint_stage},
        "target_misconception": None,
    }


def _extract_json_object(text: str) -> str | None:
    """Find the first complete, brace-balanced {...} object in ``text``,
    honoring string literals so a '{' or '}' inside a JSON string value
    doesn't miscount the nesting depth. Returns the substring spanning the
    outermost object, or None if no balanced object is found (e.g. the JSON
    was truncated before its closing brace ever arrived)."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None  # never balanced — truncated mid-object


def _parse_json(text: str) -> dict:
    """
    Extract and parse a JSON object from the model's response.

    Strips a leading markdown code fence if present, then extracts the FIRST
    complete, brace-balanced {...} object and parses only that — anything
    before it (leading prose) or after it (a trailing fence, trailing prose,
    a second code block) is ignored rather than tripping json.loads on
    "Extra data". This is the JSON failure boundary: on malformed/empty/
    non-JSON/truncated output it returns a dict carrying a ``parse_error``
    key (and the raw response for debugging) rather than raising, and logs a
    warning so the failure is never silent. Downstream consumers must treat
    a ``parse_error`` result as invalid agent output.

    Note: this is a DIFFERENT failure class from the ThinkingBlock/text
    extraction issue, which is handled upstream by response_utils.extract_text.
    An empty ``text`` here (e.g. a response with no text block) still yields a
    logged parse_error rather than a crash.
    """
    stripped = (text or "").strip()
    # A leading ```json / ``` fence marker is dropped outright — the matching
    # closing fence (and anything after it) doesn't need finding here, since
    # the balanced-object scan below naturally stops at the JSON object's own
    # closing brace and ignores everything past it.
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        stripped = stripped[first_newline + 1:] if first_newline != -1 else ""

    candidate = _extract_json_object(stripped)
    if candidate is not None:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass  # fall through to the shared parse_error path below

    # Never silent: log a truncated snippet (not the full body) so malformed
    # agent output is diagnosable without dumping large/sensitive content.
    snippet = (text or "")[:200].replace("\n", "\\n")
    reason = "no balanced JSON object found" if candidate is None else "invalid JSON"
    logger.warning("Agent returned unparseable JSON (%s). First 200 chars: %r",
                   reason, snippet)
    return {"parse_error": reason, "raw_response": text}
    
    
    
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
