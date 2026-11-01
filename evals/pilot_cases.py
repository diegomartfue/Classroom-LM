"""
evals/pilot_cases.py — the pilot eval suite (pilot item 10).

Eight single-turn cases, each run through OrchestratorAgent.run_stream()
exactly as /tutor/stream does. Each case has:

  message / history / hint_level   what the student sends
  expect                           what a correct tutor turn looks like
  mock                             canned agent outputs for --mode mocked

`expect` keys (all optional except route/decisions):
  route        the Router's route
  decisions    acceptable planner decisions. More than one where the
               Planner may legitimately ask OR hint — pedagogy is a
               judgment call; revealing the answer when the student
               didn't ask is not.
  answers      {symbol: (value, unit)}. When the turn SOLVEs, the solver's
               final answer must match within ANSWER_REL_TOL. When it does
               NOT solve, the response text must not contain the answer
               (the "no leak" check).
  response_contains_any   at least one of these substrings, case-insensitive
  language     "es": the reply must be in Spanish (stopword heuristic)
  agents_not_called       mocked mode only: these agents must not have run

Reference answers are computed here rather than typed in, so a typo can't
silently change what "correct" means.

Separate from evals/problems/ + evals/ground_truth/ (30 statics JSON
problems that predate this harness and aren't wired into it).
"""
from __future__ import annotations

import math

G = 9.81
ANSWER_REL_TOL = 0.02

_CRATE_A = G * (math.sin(math.radians(30)) - 0.25 * math.cos(math.radians(30)))
_BEAM_AY, _BEAM_BY = 12 * 4 / 6, 12 * 2 / 6
_PENDULUM_V = math.sqrt(2 * G * 1.5 * (1 - math.cos(math.radians(40))))
_LADDER_VY = 3 * 0.8 / math.sqrt(5 ** 2 - 3 ** 2)
_BOX_A = (80 - 0.3 * 15 * G) / 15
_SPANISH_A = G * math.sin(math.radians(25))


def _router(route, scope="self_contained"):
    return {"route": route, "rationale": "eval mock", "confidence": 0.95,
            "problem_scope": scope}


def _parsed(family, givens, unknowns, summary):
    return {
        "problem_type": "dynamics",
        "family": family,
        "body_description": summary,
        "scenario": {"gravity": G},
        "givens": [{"symbol": s, "value": v, "unit": u} for s, v, u in givens],
        "unknowns_requested": [{"symbol": s} for s in unknowns],
        "confidence": 0.95,
        "raw_summary": summary,
    }


def _solution(answers):
    return {"in_scope": True, "final_answers": [
        {"symbol": s, "value": round(v, 4), "unit": u} for s, (v, u) in answers.items()]}


_CRATE_MESSAGE = ("A 12 kg crate slides down a 30 degree incline. The coefficient of "
                  "kinetic friction is 0.25. Please show me the full solution for its "
                  "acceleration.")
_CRATE_PARSED = _parsed("kinetics",
                        [("m", 12, "kg"), ("theta", 30, "deg"), ("mu_k", 0.25, "")],
                        ["a"], "12 kg crate on a 30 degree incline, mu_k = 0.25")
_CRATE_ANSWERS = {"a": (_CRATE_A, "m/s^2")}


CASES: list[dict] = [
    {
        "id": "crate_incline",
        "description": "Explicit request for a full solution on a rough incline.",
        "message": _CRATE_MESSAGE,
        "history": [],
        "expect": {
            "route": "PROBLEM",
            "decisions": ["SOLVE"],
            "answers": _CRATE_ANSWERS,
        },
        "mock": {
            "router": _router("PROBLEM"),
            "input_parser": _CRATE_PARSED,
            "planner": {"decision": "SOLVE", "payload": {"permission_source": "student_requested"}},
            "solver": _solution(_CRATE_ANSWERS),
            "response": f"Along the incline, m*a = m*g*sin(30) - mu_k*m*g*cos(30), so a = {_CRATE_A:.2f} m/s^2.",
        },
    },
    {
        "id": "beam_reactions",
        "description": "Statics: student is stuck, wants a start, not the answer.",
        "message": ("A 6 m beam is pinned at A and on a roller at B. A 12 kN downward load "
                    "sits 2 m from A. I need the support reactions but I don't know where "
                    "to start."),
        "history": [],
        "expect": {
            "route": "PROBLEM",
            "decisions": ["HINT", "ASK"],
            "answers": {"Ay": (_BEAM_AY, "kN"), "By": (_BEAM_BY, "kN")},
        },
        "mock": {
            "router": _router("PROBLEM"),
            "input_parser": _parsed("kinetics", [("L", 6, "m"), ("P", 12, "kN"), ("d", 2, "m")],
                                    ["Ay", "By"], "pinned-roller beam, 12 kN at 2 m"),
            "planner": {"decision": "HINT", "payload": {"hint_level": 1}},
            "response": "Start with a free body diagram. Which point could you take moments about to leave only one unknown?",
        },
    },
    {
        "id": "pendulum",
        "description": "Energy method, explicit request for a solution.",
        "message": ("A 2 kg pendulum bob on a 1.5 m string is released from rest at 40 "
                    "degrees from vertical. How fast is it moving at the bottom? Please "
                    "work it out fully."),
        "history": [],
        "expect": {
            "route": "PROBLEM",
            "decisions": ["SOLVE"],
            "answers": {"v": (_PENDULUM_V, "m/s")},
        },
        "mock": {
            "router": _router("PROBLEM"),
            "input_parser": _parsed("energy_momentum",
                                    [("m", 2, "kg"), ("L", 1.5, "m"), ("theta", 40, "deg")],
                                    ["v"], "pendulum released from 40 degrees"),
            "planner": {"decision": "SOLVE", "payload": {"permission_source": "student_requested"}},
            "solver": _solution({"v": (_PENDULUM_V, "m/s")}),
            "response": f"Energy: m*g*L*(1 - cos 40) = (1/2)*m*v^2, so v = {_PENDULUM_V:.2f} m/s.",
        },
    },
    {
        "id": "ladder_kinematics",
        "description": "Related rates on a sliding ladder, student stuck.",
        "message": ("A 5 m ladder leans against a wall. Its bottom slides away from the "
                    "wall at 0.8 m/s. How fast is the top sliding down when the bottom is "
                    "3 m from the wall? I'm stuck."),
        "history": [],
        "expect": {
            "route": "PROBLEM",
            "decisions": ["HINT", "ASK"],
            "answers": {"v_top": (_LADDER_VY, "m/s")},
        },
        "mock": {
            "router": _router("PROBLEM"),
            "input_parser": _parsed("kinematics",
                                    [("L", 5, "m"), ("v_B", 0.8, "m/s"), ("x", 3, "m")],
                                    ["v_top"], "sliding ladder related rates"),
            "planner": {"decision": "ASK", "payload": {}},
            "response": "What relation between x and y holds for the whole motion, since the ladder length never changes?",
        },
    },
    {
        "id": "pushed_box",
        "description": "Student checks their own (correct) answer.",
        "message": ("I push a 15 kg box across the floor with a horizontal 80 N force. "
                    "mu_k = 0.3. I got an acceleration of 2.39 m/s^2. Is that right?"),
        "history": [],
        "expect": {
            "route": "PROBLEM",
            "decisions": ["SOLVE", "ASK", "HINT"],
            "answers": {"a": (_BOX_A, "m/s^2")},
            "response_contains_any": ["correct", "right", "yes", "exactly", "nice"],
        },
        "mock": {
            "router": _router("PROBLEM"),
            "input_parser": _parsed("kinetics",
                                    [("m", 15, "kg"), ("F", 80, "N"), ("mu_k", 0.3, "")],
                                    ["a"], "box pushed across rough floor"),
            "planner": {"decision": "SOLVE", "payload": {"permission_source": "student_requested"}},
            "solver": _solution({"a": (_BOX_A, "m/s^2")}),
            "response": f"Yes, that's correct: a = (80 - 0.3*15*9.81)/15 = {_BOX_A:.2f} m/s^2.",
        },
    },
    {
        "id": "followup_20kg",
        "description": "Referential follow-up; mass cancels, so a is unchanged.",
        "message": "Same thing but with a 20 kg crate. Show me the solution again.",
        "history": [
            {"role": "user", "content": _CRATE_MESSAGE},
            {"role": "assistant", "content": f"The crate accelerates at {_CRATE_A:.2f} m/s^2 down the incline."},
        ],
        "expect": {
            "route": "PROBLEM",
            "decisions": ["SOLVE"],
            "answers": _CRATE_ANSWERS,
        },
        "mock": {
            "router": _router("PROBLEM", scope="referential"),
            "input_parser": _parsed("kinetics",
                                    [("m", 20, "kg"), ("theta", 30, "deg"), ("mu_k", 0.25, "")],
                                    ["a"], "20 kg crate on a 30 degree incline, mu_k = 0.25"),
            "planner": {"decision": "SOLVE", "payload": {"permission_source": "student_requested"}},
            "solver": _solution(_CRATE_ANSWERS),
            "response": f"The mass cancels, so a is still {_CRATE_A:.2f} m/s^2.",
        },
    },
    {
        "id": "draw_that_no_context",
        "description": "'Draw that' with nothing to refer to must ask, not guess.",
        "message": "draw that",
        "history": [],
        "expect": {
            "route": "DRAW",
            "decisions": ["CLARIFY"],
            "response_contains_any": ["which problem"],
            "agents_not_called": ["input_parser", "visualizer"],
        },
        "mock": {
            "router": _router("DRAW", scope="referential"),
        },
    },
    {
        "id": "spanish_incline",
        "description": "Spanish-language problem; reply should stay in Spanish.",
        "message": ("Un bloque de 5 kg se desliza por un plano inclinado sin friccion de 25 "
                    "grados. Cual es su aceleracion? Muestrame la solucion completa, por favor."),
        "history": [],
        "expect": {
            "route": "PROBLEM",
            "decisions": ["SOLVE"],
            "answers": {"a": (_SPANISH_A, "m/s^2")},
            "language": "es",
        },
        "mock": {
            "router": _router("PROBLEM"),
            "input_parser": _parsed("kinetics", [("m", 5, "kg"), ("theta", 25, "deg")],
                                    ["a"], "5 kg block on a frictionless 25 degree incline"),
            "planner": {"decision": "SOLVE", "payload": {"permission_source": "student_requested"}},
            "solver": _solution({"a": (_SPANISH_A, "m/s^2")}),
            "response": (f"Sobre el plano, la unica fuerza que acelera el bloque es m*g*sen(25), "
                         f"asi que la aceleracion es {_SPANISH_A:.2f} m/s^2 y no depende de la masa."),
        },
    },
]
