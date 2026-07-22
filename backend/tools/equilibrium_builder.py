"""
equilibrium_builder.py

Takes a list of forces (applied + reactions, possibly with symbolic magnitudes)
and builds the three 2D rigid-body equilibrium equations using SymPy:

    ΣFx = 0
    ΣFy = 0
    ΣM_ref = 0  (about a caller-specified reference point)

Each force dict:
    {
        "magnitude": float | sympy.Expr | str,   # numeric or symbolic
        "direction_deg": float,                   # CCW from +x axis
        "location_x": float,                      # point of application
        "location_y": float,
    }

Pure moments (couples) can be included via:
    {
        "moment": float | sympy.Expr | str,       # CCW positive
    }

Returns:
    {
        "sum_Fx": sympy.Expr,   (= 0 means equilibrium)
        "sum_Fy": sympy.Expr,
        "sum_M":  sympy.Expr,
        "equations": [Eq(sum_Fx, 0), Eq(sum_Fy, 0), Eq(sum_M, 0)],
    }
"""

import math
from sympy import cos, sin, pi, sympify, Eq, Add, nsimplify, Rational


def _to_sympy(val):
    """Convert a value (float, int, str, or sympy expr) to a sympy expression."""
    if isinstance(val, (int, float)):
        return nsimplify(val, rational=False)
    if isinstance(val, str):
        return sympify(val)
    return val  # already sympy


def build_equilibrium_equations(
    forces: list[dict],
    ref_x: float = 0.0,
    ref_y: float = 0.0,
) -> dict:
    """
    Build SymPy equilibrium equations for a planar rigid body.

    Parameters
    ----------
    forces : list of dicts
        Each entry is either a force:
            {"magnitude": ..., "direction_deg": ..., "location_x": ..., "location_y": ...}
        or a pure moment / couple:
            {"moment": ...}   (CCW positive)

    ref_x, ref_y : float
        Coordinates of the moment reference point.

    Returns
    -------
    dict with keys "sum_Fx", "sum_Fy", "sum_M", "equations"
    """
    sum_Fx = sympify(0)
    sum_Fy = sympify(0)
    sum_M = sympify(0)

    for entry in forces:
        if "moment" in entry:
            # Pure couple — contributes only to ΣM, independent of ref point
            m = _to_sympy(entry["moment"])
            sum_M = sum_M + m
            continue

        mag = _to_sympy(entry["magnitude"])
        angle_deg = float(entry["direction_deg"])
        lx = float(entry["location_x"])
        ly = float(entry["location_y"])

        angle_rad = math.radians(angle_deg)
        # Use exact trig where possible via sympy
        angle_sym = nsimplify(angle_deg) * pi / 180

        fx = mag * cos(angle_sym)
        fy = mag * sin(angle_sym)

        sum_Fx = sum_Fx + fx
        sum_Fy = sum_Fy + fy

        # Moment arm from reference point to point of application
        rx = lx - ref_x
        ry = ly - ref_y

        # Moment = r × F = rx*Fy - ry*Fx  (CCW positive)
        sum_M = sum_M + (rx * fy - ry * fx)

    equations = [
        Eq(sum_Fx, 0),
        Eq(sum_Fy, 0),
        Eq(sum_M, 0),
    ]

    return {
        "sum_Fx": sum_Fx,
        "sum_Fy": sum_Fy,
        "sum_M": sum_M,
        "equations": equations,
    }


if __name__ == "__main__":
    from sympy import symbols, pprint

    # Example: horizontal beam AB, length 4 m
    #   Pin at A (0,0):  A_x (→), A_y (↑)
    #   Roller at B (4,0): B_y (↑)
    #   Point load 500 N downward at C (2,0)
    A_x, A_y, B_y = symbols("A_x A_y B_y")

    forces = [
        {"magnitude": A_x, "direction_deg": 0,   "location_x": 0, "location_y": 0},
        {"magnitude": A_y, "direction_deg": 90,  "location_x": 0, "location_y": 0},
        {"magnitude": B_y, "direction_deg": 90,  "location_x": 4, "location_y": 0},
        {"magnitude": 500, "direction_deg": 270, "location_x": 2, "location_y": 0},
    ]

    result = build_equilibrium_equations(forces, ref_x=0, ref_y=0)
    print("ΣFx = 0:")
    pprint(result["equations"][0])
    print("ΣFy = 0:")
    pprint(result["equations"][1])
    print("ΣM_A = 0:")
    pprint(result["equations"][2])
