"""
equilibrium_verifier.py

The killer check: given all forces (applied loads + computed reactions),
verifies static equilibrium by computing:

    ΣFx  = 0
    ΣFy  = 0
    ΣM_P1 = 0   (about a first reference point)
    ΣM_P2 = 0   (about a second, different reference point)

All four sums must be within `tolerance` (default 1e-6) of zero.

Input:
    forces : list of dicts
        {"label": str, "value": float, "direction_deg": float,
         "location_x": float, "location_y": float}
    moments : list of dicts  (pure couples)
        {"label": str, "value": float}   (CCW positive)
    ref_point_1 : (float, float)   default (0, 0)
    ref_point_2 : (float, float)   default (1, 0)  — must differ from ref_point_1
    tolerance   : float            default 1e-6

Returns:
    {
        "passed": bool,
        "sum_Fx":     float,
        "sum_Fy":     float,
        "sum_M_ref1": float,
        "sum_M_ref2": float,
        "ref_point_1": [float, float],
        "ref_point_2": [float, float],
        "tolerance":  float,
        "checks": [
            {"check": "sum_Fx",     "value": float, "passed": bool},
            {"check": "sum_Fy",     "value": float, "passed": bool},
            {"check": "sum_M_ref1", "value": float, "passed": bool},
            {"check": "sum_M_ref2", "value": float, "passed": bool},
        ],
        "summary": str,
    }
"""

import math


def _sum_forces_and_moment(forces: list[dict], moments: list[dict], ref_x: float, ref_y: float):
    """Return (ΣFx, ΣFy, ΣM_ref) for the given force/moment set."""
    sum_fx = 0.0
    sum_fy = 0.0
    sum_m  = 0.0

    for f in forces:
        val   = float(f.get("value", 0))
        angle = math.radians(float(f.get("direction_deg", 0)))
        lx    = float(f.get("location_x", 0))
        ly    = float(f.get("location_y", 0))

        fx = val * math.cos(angle)
        fy = val * math.sin(angle)
        sum_fx += fx
        sum_fy += fy

        rx = lx - ref_x
        ry = ly - ref_y
        sum_m += rx * fy - ry * fx

    for m in moments:
        sum_m += float(m.get("value", 0))

    return sum_fx, sum_fy, sum_m


def verify_equilibrium(
    forces: list[dict],
    moments: list[dict] | None = None,
    ref_point_1: tuple[float, float] = (0.0, 0.0),
    ref_point_2: tuple[float, float] = (1.0, 0.0),
    tolerance: float = 1e-6,
) -> dict:
    """
    Verify static equilibrium by computing ΣFx, ΣFy, and ΣM about two
    independent reference points.

    Parameters
    ----------
    forces : list of force dicts (see module docstring)
    moments : list of couple dicts (see module docstring), or None
    ref_point_1, ref_point_2 : moment reference coordinates
    tolerance : absolute tolerance for zero check

    Returns
    -------
    dict — see module docstring
    """
    if moments is None:
        moments = []

    if ref_point_1 == ref_point_2:
        return {
            "passed": False,
            "summary": "ref_point_1 and ref_point_2 must be different.",
            "checks": [],
        }

    r1x, r1y = ref_point_1
    r2x, r2y = ref_point_2

    fx, fy, m1 = _sum_forces_and_moment(forces, moments, r1x, r1y)
    _,  _,  m2 = _sum_forces_and_moment(forces, moments, r2x, r2y)

    def _check(name, val):
        return {"check": name, "value": val, "passed": abs(val) <= tolerance}

    checks = [
        _check("sum_Fx",     fx),
        _check("sum_Fy",     fy),
        _check("sum_M_ref1", m1),
        _check("sum_M_ref2", m2),
    ]

    passed = all(c["passed"] for c in checks)

    failed_names = [c["check"] for c in checks if not c["passed"]]
    if passed:
        summary = f"Equilibrium verified (all sums within tolerance {tolerance:.0e})."
    else:
        summary = (
            f"Equilibrium NOT satisfied. Failed checks: {failed_names}. "
            f"Tolerance = {tolerance:.0e}."
        )

    return {
        "passed": passed,
        "sum_Fx":     fx,
        "sum_Fy":     fy,
        "sum_M_ref1": m1,
        "sum_M_ref2": m2,
        "ref_point_1": list(ref_point_1),
        "ref_point_2": list(ref_point_2),
        "tolerance":  tolerance,
        "checks":     checks,
        "summary":    summary,
    }


if __name__ == "__main__":
    import json

    # Example: pin at A (0,0), roller at B (4,0), 500 N load at C (2,0)
    # Reactions: A_x=0, A_y=250 N↑, B_y=250 N↑
    forces = [
        # Applied load
        {"label": "P",   "value": 500, "direction_deg": 270, "location_x": 2, "location_y": 0},
        # Reactions
        {"label": "A_x", "value": 0,   "direction_deg": 0,   "location_x": 0, "location_y": 0},
        {"label": "A_y", "value": 250, "direction_deg": 90,  "location_x": 0, "location_y": 0},
        {"label": "B_y", "value": 250, "direction_deg": 90,  "location_x": 4, "location_y": 0},
    ]

    result = verify_equilibrium(forces, ref_point_1=(0, 0), ref_point_2=(4, 0))
    print(json.dumps(result, indent=2))

    # Intentionally wrong reaction to trigger failure
    print("\n--- Wrong reaction (should fail) ---")
    bad_forces = [
        {"label": "P",   "value": 500, "direction_deg": 270, "location_x": 2, "location_y": 0},
        {"label": "A_y", "value": 300, "direction_deg": 90,  "location_x": 0, "location_y": 0},  # wrong
        {"label": "B_y", "value": 250, "direction_deg": 90,  "location_x": 4, "location_y": 0},
    ]
    result2 = verify_equilibrium(bad_forces, ref_point_1=(0, 0), ref_point_2=(2, 0))
    print(json.dumps(result2, indent=2))

    # With a pure couple moment
    print("\n--- With applied couple ---")
    forces_with_couple = [
        {"label": "P",   "value": 500, "direction_deg": 270, "location_x": 2, "location_y": 0},
        {"label": "A_x", "value": 0,   "direction_deg": 0,   "location_x": 0, "location_y": 0},
        {"label": "A_y", "value": 375, "direction_deg": 90,  "location_x": 0, "location_y": 0},
        {"label": "B_y", "value": 125, "direction_deg": 90,  "location_x": 4, "location_y": 0},
    ]
    couples = [{"label": "M_ext", "value": 500}]  # 500 N·m CCW
    result3 = verify_equilibrium(forces_with_couple, moments=couples, ref_point_1=(0, 0), ref_point_2=(4, 0))
    print(json.dumps(result3, indent=2))
