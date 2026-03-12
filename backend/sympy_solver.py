"""
SymPy Solver - Math Verification Layer
Verifies AI answers against SymPy's computed results.
SymPy always wins if there's a disagreement.
"""

import sympy as sp
from sympy.parsing.sympy_parser import parse_expr
import re

def extract_and_solve(message: str) -> dict | None:
    """
    Try to detect and solve a math problem from a message.
    Returns result dict if solvable, None if not a math problem.
    """
    message_lower = message.lower()

    # Detect equation solving
    if "solve" in message_lower and "=" in message:
        return solve_equation(message)

    # Detect derivatives
    if any(word in message_lower for word in ["derivative", "differentiate", "d/dx"]):
        return compute_derivative(message)

    # Detect integrals
    if any(word in message_lower for word in ["integrate", "integral"]):
        return compute_integral(message)

    # Detect simplification
    if "simplify" in message_lower:
        return simplify_expression(message)

    return None


def solve_equation(message: str) -> dict | None:
    """Solve an equation using SymPy."""
    try:
        # Extract equation pattern like "x^2 + 3x = 10"
        match = re.search(r'([a-zA-Z0-9\^\+\-\*\/\s\.]+)=([a-zA-Z0-9\^\+\-\*\/\s\.]+)', message)
        if not match:
            return None

        left = match.group(1).strip().replace("^", "**")
        right = match.group(2).strip().replace("^", "**")

        x = sp.Symbol('x')
        equation = sp.Eq(parse_expr(left), parse_expr(right))
        solution = sp.solve(equation, x)

        return {
            "type": "equation",
            "input": f"{match.group(1).strip()} = {match.group(2).strip()}",
            "solution": [str(s) for s in solution],
            "verified": True
        }
    except Exception:
        return None


def compute_derivative(message: str) -> dict | None:
    """Compute derivative using SymPy."""
    try:
        # Extract expression after "derivative of" or "d/dx"
        match = re.search(r'(?:derivative of|differentiate|d/dx\s+of?)\s+([^\?\.]+)', message, re.IGNORECASE)
        if not match:
            return None

        expr_str = match.group(1).strip().replace("^", "**")
        x = sp.Symbol('x')
        expr = parse_expr(expr_str)
        derivative = sp.diff(expr, x)

        return {
            "type": "derivative",
            "input": match.group(1).strip(),
            "solution": str(derivative),
            "verified": True
        }
    except Exception:
        return None


def compute_integral(message: str) -> dict | None:
    """Compute integral using SymPy."""
    try:
        match = re.search(r'(?:integrate|integral of)\s+([^\?\.]+)', message, re.IGNORECASE)
        if not match:
            return None

        expr_str = match.group(1).strip().replace("^", "**")
        # Remove "dx" if present
        expr_str = re.sub(r'\s*dx\s*$', '', expr_str).strip()

        x = sp.Symbol('x')
        expr = parse_expr(expr_str)
        integral = sp.integrate(expr, x)

        return {
            "type": "integral",
            "input": match.group(1).strip(),
            "solution": str(integral) + " + C",
            "verified": True
        }
    except Exception:
        return None


def simplify_expression(message: str) -> dict | None:
    """Simplify an expression using SymPy."""
    try:
        match = re.search(r'simplify\s+([^\?\.]+)', message, re.IGNORECASE)
        if not match:
            return None

        expr_str = match.group(1).strip().replace("^", "**")
        expr = parse_expr(expr_str)
        simplified = sp.simplify(expr)

        return {
            "type": "simplify",
            "input": match.group(1).strip(),
            "solution": str(simplified),
            "verified": True
        }
    except Exception:
        return None