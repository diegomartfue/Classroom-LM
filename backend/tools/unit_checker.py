"""
unit_checker.py

Uses pint to check dimensional consistency of a list of quantities.

Input: list of dicts:
    [
        {"label": "A_y",  "value": 250,  "unit": "N"},
        {"label": "B_y",  "value": 250,  "unit": "N"},
        {"label": "load", "value": 500,  "unit": "N"},
        {"label": "arm",  "value": 2.0,  "unit": "m"},
    ]

Optional: a list of "groups" — each group must have the same dimensions:
    [
        {"group": "forces",  "labels": ["A_y", "B_y", "load"]},
        {"group": "moments", "labels": []},
    ]

If no groups provided, checks that all quantities parse as valid pint units (no
incompatible implicit mixing is flagged per-group by caller).

Returns:
    {
        "passed": bool,
        "details": [
            {"label": "...", "unit": "...", "dimension": "...", "valid": bool, "error": str|None},
            ...
        ],
        "group_results": [
            {"group": "forces", "consistent": bool, "dimensions": [...], "error": str|None},
            ...
        ],
        "summary": str,
    }
"""

try:
    from pint import UnitRegistry, DimensionalityError, UndefinedUnitError
    _PINT_AVAILABLE = True
except ImportError:
    _PINT_AVAILABLE = False


def check_units(quantities: list[dict], groups: list[dict] | None = None) -> dict:
    """
    Check dimensional consistency of the supplied quantities.

    Parameters
    ----------
    quantities : list of {"label": str, "value": float, "unit": str}
    groups : optional list of {"group": str, "labels": [str, ...]}
        Each group's members must share the same physical dimension.

    Returns
    -------
    dict — see module docstring.
    """
    if not _PINT_AVAILABLE:
        return {
            "passed": False,
            "details": [],
            "group_results": [],
            "summary": "pint library not installed. Run: pip install pint",
        }

    ureg = UnitRegistry()
    label_to_dim: dict[str, str] = {}
    details = []
    all_valid = True

    for q in quantities:
        label = q.get("label", "?")
        value = q.get("value", 0)
        unit_str = q.get("unit", "")
        try:
            qty = ureg.Quantity(value, unit_str)
            dim = str(qty.dimensionality)
            label_to_dim[label] = dim
            details.append({"label": label, "unit": unit_str, "dimension": dim, "valid": True, "error": None})
        except (UndefinedUnitError, Exception) as exc:
            all_valid = False
            label_to_dim[label] = "unknown"
            details.append({"label": label, "unit": unit_str, "dimension": "unknown", "valid": False, "error": str(exc)})

    group_results = []
    if groups:
        for g in groups:
            g_name = g.get("group", "unnamed")
            g_labels = g.get("labels", [])
            dims = [label_to_dim.get(lbl, "unknown") for lbl in g_labels]
            unique_dims = set(dims)
            if "unknown" in unique_dims:
                consistent = False
                error = f"One or more labels have unknown units: {[l for l in g_labels if label_to_dim.get(l) == 'unknown']}"
            elif len(unique_dims) <= 1:
                consistent = True
                error = None
            else:
                consistent = False
                all_valid = False
                error = f"Dimension mismatch in group '{g_name}': {dict(zip(g_labels, dims))}"
            group_results.append({
                "group": g_name,
                "consistent": consistent,
                "dimensions": dims,
                "error": error,
            })

    passed = all_valid and all(r["consistent"] for r in group_results) if group_results else all_valid
    summary = "All unit checks passed." if passed else "One or more unit checks failed."

    return {
        "passed": passed,
        "details": details,
        "group_results": group_results,
        "summary": summary,
    }


if __name__ == "__main__":
    import json

    quantities = [
        {"label": "A_y",  "value": 250,  "unit": "N"},
        {"label": "B_y",  "value": 250,  "unit": "N"},
        {"label": "load", "value": 500,  "unit": "N"},
        {"label": "arm",  "value": 2.0,  "unit": "m"},
        {"label": "M_ext","value": 100,  "unit": "N*m"},
    ]
    groups = [
        {"group": "forces",  "labels": ["A_y", "B_y", "load"]},
        {"group": "moments", "labels": ["M_ext"]},
    ]

    result = check_units(quantities, groups)
    print(json.dumps(result, indent=2))

    print("\n--- Inconsistent group ---")
    bad = [
        {"label": "F", "value": 100, "unit": "N"},
        {"label": "x", "value": 2,   "unit": "m"},
    ]
    bad_groups = [{"group": "mixed", "labels": ["F", "x"]}]
    result2 = check_units(bad, bad_groups)
    print(json.dumps(result2, indent=2))

    print("\n--- Bad unit string ---")
    result3 = check_units([{"label": "Q", "value": 1, "unit": "flurbles"}])
    print(json.dumps(result3, indent=2))
