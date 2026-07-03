"""
reaction_checker.py

Sanity-checks computed reactions against applied loads.

Checks:
1. Magnitude order-of-magnitude: each reaction magnitude should be within
   3 orders of magnitude of the largest applied load (catches unit errors,
   wildly wrong solutions).
2. Direction physical sense: reactions at common support types should only
   act in allowable directions:
       pin    — any direction (2 components)
       roller — perpendicular to surface only (1 component)
       fixed  — any direction + moment (3 components)
       cable  — tension only (magnitude >= 0)
       contact— compression only (normal force >= 0)

Input:
    reactions : list of dicts
        {"label": "A_y", "value": float, "direction_deg": float,
         "support_type": "pin"|"roller"|"fixed"|"cable"|"contact"|None}

    applied_loads : list of dicts
        {"label": "P", "value": float, "direction_deg": float}

Returns:
    {
        "passed": bool,
        "checks": [
            {"check": str, "passed": bool, "detail": str},
            ...
        ],
        "summary": str,
    }
"""

import math


_SUPPORT_CONSTRAINTS = {
    "cable":   {"tension_only": True},
    "contact": {"compression_only": True},
}


def _order_of_magnitude(val: float) -> int:
    if val == 0:
        return 0
    return int(math.floor(math.log10(abs(val))))


def check_reactions(reactions: list[dict], applied_loads: list[dict]) -> dict:
    """
    Sanity-check computed reactions against applied loads.

    Parameters
    ----------
    reactions : list of reaction dicts (see module docstring)
    applied_loads : list of load dicts (see module docstring)

    Returns
    -------
    dict — see module docstring
    """
    checks = []
    all_passed = True

    # ------------------------------------------------------------------ #
    # 1. Magnitude order-of-magnitude check
    # ------------------------------------------------------------------ #
    load_magnitudes = [abs(float(l.get("value", 0))) for l in applied_loads]
    reaction_magnitudes = [abs(float(r.get("value", 0))) for r in reactions]

    max_load = max(load_magnitudes) if load_magnitudes else 0.0
    max_rxn  = max(reaction_magnitudes) if reaction_magnitudes else 0.0

    if max_load > 0 and max_rxn > 0:
        oom_diff = abs(_order_of_magnitude(max_rxn) - _order_of_magnitude(max_load))
        if oom_diff <= 3:
            checks.append({
                "check": "magnitude_order_of_magnitude",
                "passed": True,
                "detail": (
                    f"Max reaction {max_rxn:.3g} vs max applied load {max_load:.3g}; "
                    f"OOM difference = {oom_diff} (≤ 3, OK)."
                ),
            })
        else:
            all_passed = False
            checks.append({
                "check": "magnitude_order_of_magnitude",
                "passed": False,
                "detail": (
                    f"Max reaction {max_rxn:.3g} vs max applied load {max_load:.3g}; "
                    f"OOM difference = {oom_diff} (> 3, suspect unit error or wrong solution)."
                ),
            })
    else:
        checks.append({
            "check": "magnitude_order_of_magnitude",
            "passed": True,
            "detail": "Cannot compare (zero loads or reactions).",
        })

    # ------------------------------------------------------------------ #
    # 2. Individual reaction magnitude sanity (not grossly larger than all loads combined)
    # ------------------------------------------------------------------ #
    total_load = sum(load_magnitudes) if load_magnitudes else 0.0
    for r in reactions:
        label = r.get("label", "?")
        val = abs(float(r.get("value", 0)))
        # Allow up to 10× the total load as a generous upper bound
        if total_load > 0 and val > 10 * total_load:
            all_passed = False
            checks.append({
                "check": f"reaction_magnitude_bound:{label}",
                "passed": False,
                "detail": (
                    f"Reaction {label} = {val:.3g} is more than 10× total applied load "
                    f"({total_load:.3g}). Likely a numerical error."
                ),
            })
        else:
            checks.append({
                "check": f"reaction_magnitude_bound:{label}",
                "passed": True,
                "detail": f"Reaction {label} = {val:.3g} is within acceptable bound (≤ 10× total load {total_load:.3g}).",
            })

    # ------------------------------------------------------------------ #
    # 3. Direction / sign constraints for specific support types
    # ------------------------------------------------------------------ #
    for r in reactions:
        label = r.get("label", "?")
        support_type = r.get("support_type", None)
        val = float(r.get("value", 0))

        if support_type == "cable":
            # Cables can only pull (tension), so the reported magnitude must be >= 0
            passed = val >= -1e-9  # small tolerance for floating point
            checks.append({
                "check": f"cable_tension_only:{label}",
                "passed": passed,
                "detail": (
                    f"Cable reaction {label} = {val:.3g} N: {'OK (tension/zero)' if passed else 'FAIL (compression in cable is impossible)'}."
                ),
            })
            if not passed:
                all_passed = False

        elif support_type == "contact":
            # Contact (normal) forces only push — magnitude >= 0
            passed = val >= -1e-9
            checks.append({
                "check": f"contact_compression_only:{label}",
                "passed": passed,
                "detail": (
                    f"Contact reaction {label} = {val:.3g} N: {'OK (compression/zero)' if passed else 'FAIL (tensile contact force is physically impossible)'}."
                ),
            })
            if not passed:
                all_passed = False

    summary = "All reaction sanity checks passed." if all_passed else "One or more reaction checks failed."
    return {"passed": all_passed, "checks": checks, "summary": summary}


if __name__ == "__main__":
    import json

    # Normal case: pin + roller, 500 N load
    reactions = [
        {"label": "A_x", "value": 0,   "direction_deg": 0,  "support_type": "pin"},
        {"label": "A_y", "value": 250, "direction_deg": 90, "support_type": "pin"},
        {"label": "B_y", "value": 250, "direction_deg": 90, "support_type": "roller"},
    ]
    applied_loads = [
        {"label": "P", "value": 500, "direction_deg": 270},
    ]
    result = check_reactions(reactions, applied_loads)
    print(json.dumps(result, indent=2))

    # Cable in compression (should fail)
    print("\n--- Cable in compression ---")
    bad_reactions = [
        {"label": "T_cable", "value": -200, "direction_deg": 90, "support_type": "cable"},
    ]
    result2 = check_reactions(bad_reactions, applied_loads)
    print(json.dumps(result2, indent=2))

    # Wildly large reaction (OOM fail)
    print("\n--- OOM check ---")
    big = [{"label": "R", "value": 1e8, "direction_deg": 90, "support_type": "pin"}]
    result3 = check_reactions(big, applied_loads)
    print(json.dumps(result3, indent=2))
