"""
linear_solver.py

Takes a list of SymPy equations and a list of unknowns, solves the linear system,
and handles under-determined and over-determined cases gracefully.

Returns:
    {
        "status": "solved" | "underdetermined" | "overdetermined" | "no_solution" | "error",
        "solutions": {symbol_name: value, ...},   # on success
        "free_symbols": [...],                     # on underdetermined
        "inconsistent_equations": [...],           # on overdetermined / no_solution
        "detail": str,
    }
"""

from sympy import linsolve, linear_eq_to_matrix, symbols as sympy_symbols
from sympy import Eq, Symbol, sympify, N
from sympy.core.containers import Tuple


def solve_linear_system(equations: list, unknowns: list) -> dict:
    """
    Solve a (possibly non-square) linear system.

    Parameters
    ----------
    equations : list of sympy.Eq or sympy.Expr
        If Expr, treated as Expr = 0.
    unknowns : list of sympy.Symbol or str

    Returns
    -------
    dict — see module docstring.
    """
    if not equations:
        return {"status": "error", "detail": "No equations provided.", "solutions": {}}
    if not unknowns:
        return {"status": "error", "detail": "No unknowns provided.", "solutions": {}}

    # Normalise: convert Eq(lhs, rhs) → lhs - rhs
    exprs = []
    for eq in equations:
        if isinstance(eq, Eq):
            exprs.append(eq.lhs - eq.rhs)
        else:
            exprs.append(sympify(eq))

    # Normalise unknowns to Symbol objects
    sym_unknowns = []
    for u in unknowns:
        if isinstance(u, str):
            sym_unknowns.append(Symbol(u))
        else:
            sym_unknowns.append(u)

    try:
        solution_set = linsolve(exprs, sym_unknowns)
    except Exception as exc:
        return {"status": "error", "detail": str(exc), "solutions": {}}

    if solution_set is None or len(solution_set) == 0:
        # No solution — system is inconsistent
        return {
            "status": "no_solution",
            "solutions": {},
            "detail": "System is inconsistent (no solution exists).",
        }

    # linsolve returns a FiniteSet of Tuples (one Tuple per solution)
    solution_tuple = next(iter(solution_set))  # first (and usually only) element

    # Check for free symbols → underdetermined
    free = []
    for val in solution_tuple:
        free.extend([str(s) for s in val.free_symbols if s not in sym_unknowns])

    # Also detect parametric unknowns: if any value still contains one of our unknowns
    parametric = []
    for sym, val in zip(sym_unknowns, solution_tuple):
        remaining = val.free_symbols.intersection(set(sym_unknowns))
        if remaining:
            parametric.extend([str(s) for s in remaining])

    if free or parametric:
        return {
            "status": "underdetermined",
            "solutions": {str(s): val for s, val in zip(sym_unknowns, solution_tuple)},
            "free_symbols": list(set(free + parametric)),
            "detail": "System is underdetermined; some unknowns remain free.",
        }

    # Check over-determination: more equations than unknowns
    # If all are consistent, linsolve still returns a solution — just flag it
    n_eq = len(exprs)
    n_unk = len(sym_unknowns)
    status = "solved"
    detail = f"Unique solution found ({n_eq} equations, {n_unk} unknowns)."
    if n_eq > n_unk:
        detail = (
            f"Over-determined system ({n_eq} equations, {n_unk} unknowns); "
            "solution satisfies all equations (consistent)."
        )
        status = "overdetermined"

    solutions = {}
    for sym, val in zip(sym_unknowns, solution_tuple):
        # Evaluate to float if fully numeric
        try:
            solutions[str(sym)] = float(val)
        except (TypeError, ValueError):
            solutions[str(sym)] = val  # leave as sympy expr if symbolic

    return {"status": status, "solutions": solutions, "detail": detail}


if __name__ == "__main__":
    from sympy import symbols, Eq

    A_x, A_y, B_y = symbols("A_x A_y B_y")

    # Pin at A, roller at B, 500 N load at midspan
    equations = [
        Eq(A_x, 0),
        Eq(A_y + B_y - 500, 0),
        Eq(B_y * 4 - 500 * 2, 0),
    ]
    unknowns = [A_x, A_y, B_y]

    result = solve_linear_system(equations, unknowns)
    print("Status:", result["status"])
    print("Solutions:", result["solutions"])
    print("Detail:", result["detail"])

    # Under-determined example
    print("\n--- Under-determined ---")
    result2 = solve_linear_system([Eq(A_x + A_y, 10)], [A_x, A_y])
    print("Status:", result2["status"])
    print("Free symbols:", result2.get("free_symbols"))

    # Inconsistent example
    print("\n--- Inconsistent ---")
    result3 = solve_linear_system(
        [Eq(A_x, 1), Eq(A_x, 2)], [A_x]
    )
    print("Status:", result3["status"])
    print("Detail:", result3["detail"])
