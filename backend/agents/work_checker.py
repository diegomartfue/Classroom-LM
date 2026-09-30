"""
agents/work_checker.py — deterministic, SymPy-only checker for a student's
line-by-line solution work (pilot item 9). No LLM anywhere in this module;
the checking itself is pure Python + SymPy.

SECURITY — sympy.parse_expr is NOT safe on raw untrusted input by default.
It tokenizes and reconstructs the string, then evaluates the reconstructed
expression via Python's own eval() under the hood. Every string handed to
parse_expr in this module has already passed four independent guards, in
order, each of which can reject on its own:

  1. length limit (_MAX_LINE_LENGTH)
  2. a character whitelist — letters, digits, single underscores (needed for
     ordinary physics subscript notation like mu_k, v_0, f_k — already used
     throughout this codebase's own parsed-problem schema), whitespace, and
     arithmetic/equation punctuation only. No brackets other than
     parentheses, no quotes, no backslash, no colons/semicolons, no @ # $ %,
     and — checked separately, see (3) — no double underscore anywhere.
  3. double underscores are rejected outright, anywhere in the string. This
     is deliberately narrower than banning every underscore (which would
     also reject legitimate symbols like mu_k): "__" is the actual Python
     attack surface (__import__, __class__, __globals__, __subclasses__,
     ...) and is never needed in real physics notation.
  4. every identifier token must be either a known problem symbol or match
     a narrow physics-symbol shape (_is_physics_symbol: a letter plus up to
     two letters/digits, or a Greek letter name, optionally with one short
     subscript — N, f_k, Ax, v0, theta_1, mu_k), and never a Python keyword
     or a parser helper name. Anything else (secret_value, evil_func,
     __import__, getattr) is rejected before parsing is even attempted.
     Every accepted name is mapped to a plain sympy.Symbol in local_dict,
     so no identifier can resolve to a function or object from any other
     namespace.

A '.' is only ever accepted as a decimal point (digit immediately before AND
after) — "3.14" is fine, "x.y" or "().foo"-style attribute access is not.

Even after all of that, parse_expr itself is called with
global_dict={"__builtins__": {}} and a local_dict built ONLY from the
allowlist, so a string that somehow slipped past every check above still has
no path to a real builtin, module, or attribute chain. eval()/exec() are
never called directly anywhere in this module — parse_expr is SymPy's own
guarded parser, not a hand-rolled one.
"""
from __future__ import annotations

import keyword
import math
import re
from typing import NamedTuple

import sympy
from sympy.parsing.sympy_parser import parse_expr

_MAX_LINE_LENGTH = 200

_ALLOWED_CHAR_RE = re.compile(r"^[A-Za-z0-9_.+\-*/^(),=\s]*$")
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Fixed, small set of safe math function/constant names a physics line might
# legitimately use. Never extended from user input — this table is the
# entire universe of "function-shaped" names a line can reference.
_SYMPY_FUNCS = {
    "sin": sympy.sin, "cos": sympy.cos, "tan": sympy.tan,
    "asin": sympy.asin, "acos": sympy.acos, "atan": sympy.atan,
    "atan2": sympy.atan2,
    "sinh": sympy.sinh, "cosh": sympy.cosh, "tanh": sympy.tanh,
    "sqrt": sympy.sqrt, "exp": sympy.exp, "log": sympy.log, "ln": sympy.log,
    "Abs": sympy.Abs, "abs": sympy.Abs, "pi": sympy.pi, "Pow": sympy.Pow,
}
_SAFE_NAMES = set(_SYMPY_FUNCS)


def _build_safe_global_dict() -> dict:
    """parse_expr's transformations (auto_number, auto_symbol, ...) call
    helper names like Integer/Float/Symbol from its eval namespace — so the
    global_dict can't just be {"__builtins__": {}} or those calls raise
    NameError. The standard safe pattern (from SymPy's own sandboxing docs)
    is to populate the namespace with `from sympy import *` and then
    explicitly zero out __builtins__ on top of it, which is what this does.
    SymPy's own names are just math classes/functions — safe to expose —
    and none of them are reachable from real Python builtins afterward."""
    g: dict = {}
    exec("from sympy import *", g)  # noqa: S102 - fixed, non-user-controlled source string
    g["__builtins__"] = {}
    return g


_SAFE_GLOBAL_DICT = _build_safe_global_dict()


class UnsafeExpression(ValueError):
    """A line failed a security or syntax guard. Always caught and turned
    into a user-facing "invalid" result — never lets the raw exception
    text (which could echo pieces of the rejected input) leak unfiltered,
    and never raised past check_line/check_work."""


def _check_length(s: str) -> None:
    if len(s) > _MAX_LINE_LENGTH:
        raise UnsafeExpression(f"line is too long (max {_MAX_LINE_LENGTH} characters)")


def _check_no_double_underscore(s: str) -> None:
    if "__" in s:
        raise UnsafeExpression("double underscores are not allowed")


def _check_charset(s: str) -> None:
    if not _ALLOWED_CHAR_RE.match(s):
        raise UnsafeExpression("contains a character that isn't allowed in a math expression")


def _check_dots_are_only_decimal_points(s: str) -> None:
    for i, ch in enumerate(s):
        if ch != ".":
            continue
        before = s[i - 1] if i > 0 else ""
        after = s[i + 1] if i + 1 < len(s) else ""
        if not (before.isdigit() and after.isdigit()):
            raise UnsafeExpression("'.' is only allowed inside a decimal number, e.g. 9.81")


_GREEK = {"alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
          "iota", "kappa", "mu", "nu", "xi", "rho", "sigma", "tau", "phi", "chi",
          "psi", "omega", "Delta", "Omega", "Sigma", "Phi"}
# A letter plus up to two letters/digits (N, f, Ax, v0, F12), or a Greek
# name — then optionally one short subscript (f_k, v_0, mu_k, theta_1, v_top).
_PHYSICS_SYMBOL_RE = re.compile(
    r"^(?:[A-Za-z][A-Za-z0-9]{0,2}|" + "|".join(sorted(_GREEK)) + r")(?:_[A-Za-z0-9]{1,4})?$")
# Names parse_expr's own transformations emit (auto_number -> Integer(2),
# auto_symbol -> Symbol('x'), ...). Shadowing one breaks every line.
_RESERVED_NAMES = {"Integer", "Float", "Rational", "Symbol", "Function",
                   "Lambda", "Add", "Mul", "Pow", "Tuple", "Number"}


def _is_physics_symbol(name: str) -> bool:
    """Shape check only: whether a student may use this as a variable name.
    Keywords are excluded (`if`, `or`, `in` would change what the line
    means), as are parser helpers and the math function names."""
    return (bool(_PHYSICS_SYMBOL_RE.match(name)) and not keyword.iskeyword(name)
            and name not in _RESERVED_NAMES and name not in _SAFE_NAMES)


def _check_identifiers_allowed(s: str, allowed_symbols) -> set:
    """Returns the identifier tokens found. Raises if any of them is not a
    known problem symbol, a physics-shaped variable name, or a safe
    function name."""
    found = set(_IDENTIFIER_RE.findall(s))
    unknown = {n for n in found - set(allowed_symbols) - _SAFE_NAMES
               if not _is_physics_symbol(n)}
    if unknown:
        raise UnsafeExpression(f"unrecognized name(s): {', '.join(sorted(unknown))}")
    return found


_MAX_EXPONENT = 1000


_GROWTH_FUNCS = (sympy.exp, sympy.sinh, sympy.cosh)


def _is_growth_node(node) -> bool:
    """Pow (other than x^-1, which is how an unevaluated parse spells
    division) and the exponential-type functions."""
    if isinstance(node, sympy.Pow):
        return node.exp != -1
    return isinstance(node, _GROWTH_FUNCS)


def _check_expression_shape(expr: sympy.Expr) -> None:
    """Reject shapes whose evaluation would be enormous: towers such as
    9^9^9 (exact integer with ~370 million digits) or exp(exp(exp(99)))
    (hangs mpmath). An exponent, or the argument of exp/sinh/cosh, may not
    contain another power or exponential — m^(1/2) is fine since 1/2 is a
    division — and a purely numeric exponent must stay within
    +/-_MAX_EXPONENT. An exponent that references a symbol is fine: known
    values are substituted as Floats, which evaluate in constant time
    however large the result."""
    for node in sympy.preorder_traversal(expr):
        if isinstance(node, sympy.Pow):
            inner = node.exp
        elif isinstance(node, _GROWTH_FUNCS):
            inner = node.args[0]
        else:
            continue
        if any(_is_growth_node(sub) for sub in sympy.preorder_traversal(inner)):
            raise UnsafeExpression("nested exponents (like 2^3^4 or exp(exp(x))) aren't supported")
        if isinstance(node, sympy.Pow) and not inner.free_symbols:
            try:
                value = abs(complex(inner.evalf()))
            except (TypeError, ValueError):
                raise UnsafeExpression("exponent must be a number")
            if value > _MAX_EXPONENT:
                raise UnsafeExpression(f"exponent is too large (max {_MAX_EXPONENT})")


def safe_parse(expr_str: str, allowed_symbols) -> sympy.Expr:
    """Parse ``expr_str`` into a SymPy expression, or raise
    UnsafeExpression. See the module docstring for the full guard chain."""
    if not isinstance(expr_str, str):
        raise UnsafeExpression("expression must be text")
    s = expr_str.strip()
    if not s:
        raise UnsafeExpression("empty expression")

    _check_length(s)
    _check_no_double_underscore(s)
    _check_charset(s)
    _check_dots_are_only_decimal_points(s)
    used_names = _check_identifiers_allowed(s, allowed_symbols)

    symbol_names = used_names - _SAFE_NAMES
    local_dict = {name: sympy.Symbol(name) for name in symbol_names}
    local_dict.update({name: _SYMPY_FUNCS[name] for name in used_names if name in _SYMPY_FUNCS})

    # evaluate=False first: SymPy would otherwise compute exact integer
    # results while parsing, and "9^9^9" (or "10^10^8") is a ~370-million-digit
    # integer that pins a worker indefinitely. The unevaluated tree is
    # inspected by _check_expression_shape before anything is computed.
    try:
        expr = parse_expr(
            s.replace("^", "**"),
            local_dict=local_dict,
            global_dict=_SAFE_GLOBAL_DICT,
            evaluate=False,
        )
    except UnsafeExpression:
        raise
    except Exception as exc:
        raise UnsafeExpression(f"could not parse: {type(exc).__name__}") from exc

    if not isinstance(expr, sympy.Expr):
        raise UnsafeExpression("not a math expression")
    _check_expression_shape(expr)

    # Defense in depth: the parsed expression's free symbols must be a
    # subset of what was explicitly allowed. If parse_expr somehow produced
    # a symbol our identifier scan above didn't catch, reject rather than
    # silently proceed with something unexpected.
    extra = {str(sym) for sym in expr.free_symbols} - symbol_names
    if extra:
        raise UnsafeExpression(f"unexpected symbol(s): {', '.join(sorted(extra))}")

    return expr


_TRIG = (sympy.sin, sympy.cos, sympy.tan)
_INVERSE_TRIG = (sympy.asin, sympy.acos, sympy.atan, sympy.atan2)
_DEG = sympy.pi / 180


def _to_degree_mode(expr: sympy.Expr) -> sympy.Expr:
    """Reinterpret trig as a calculator in degree mode would: sin/cos/tan
    take degrees, asin/acos/atan/atan2 return degrees."""
    expr = expr.replace(lambda e: isinstance(e, _TRIG),
                        lambda e: e.func(e.args[0] * _DEG))
    return expr.replace(lambda e: isinstance(e, _INVERSE_TRIG),
                        lambda e: sympy.Mul(e, 1 / _DEG, evaluate=False))


def _numeric_sides(lhs_expr, rhs_expr, values: dict, degree_mode: bool):
    subs = {sympy.Symbol(k): sympy.Float(v) for k, v in values.items()}
    lhs, rhs = lhs_expr.subs(subs), rhs_expr.subs(subs)
    if degree_mode:
        lhs, rhs = _to_degree_mode(lhs), _to_degree_mode(rhs)
    return float(lhs.evalf()), float(rhs.evalf())


def _invalid(line, detail: str) -> dict:
    return {"line": line, "status": "invalid", "detail": detail,
            "lhs_value": None, "rhs_value": None}


# Students and the solver name the same quantity differently: the student
# writes f and N, the solver reports f_k and F_N. A symbol with no value of
# its own takes the first valued member of its family. Kept to quantities
# where the short name is unambiguous in 2D statics/dynamics.
_ALIAS_FAMILIES = [
    ("N", "n", "F_N", "F_n"),                              # normal force
    ("f_k", "f", "F_f", "F_k", "f_f", "F_fr", "f_r"),      # kinetic friction
    ("W", "w", "F_g", "F_W", "W_g"),                       # weight
    ("T", "F_T"),                                          # tension
    ("mu_k", "mu", "u_k"),                                 # kinetic friction coefficient
    ("theta", "th"),                                       # incline angle
]
_FAMILY_OF = {name: fam for fam in _ALIAS_FAMILIES for name in fam}
_WEIGHT_FAMILY = _FAMILY_OF["W"]


def _resolve(symbol: str, known_values: dict, hidden: set, angle_symbols,
             defined: dict, defined_hidden: set):
    """(value, is_hidden, is_angle) for one symbol, or None if nothing
    gives it a value. Order: its own known value, a family alias, weight
    derived as m*g, then a value the student defined on an earlier line.
    A known value always beats a student definition, so a wrong earlier
    line never makes a later line look right."""
    candidates = [symbol] + [a for a in _FAMILY_OF.get(symbol, ()) if a != symbol]
    for name in candidates:
        if name in known_values:
            return known_values[name], name in hidden, name in angle_symbols
    if symbol in _WEIGHT_FAMILY and "m" in known_values and "g" in known_values:
        return known_values["m"] * known_values["g"], False, False
    if symbol in defined:
        return defined[symbol], symbol in defined_hidden, False
    return None


def _numeric_trig_args_look_like_degrees(expr: sympy.Expr) -> bool:
    """cos(30) means degrees; cos(pi/6) means radians. Only used to pick
    the reading for a line that DEFINES a value (a checked line tries
    both readings instead)."""
    for node in sympy.preorder_traversal(expr):
        if isinstance(node, _TRIG) and not node.args[0].free_symbols:
            try:
                if abs(float(node.args[0].evalf())) > 2 * math.pi:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def check_line(line: str, known_values: dict, allowed_symbols,
               rel_tol: float = 0.02, abs_tol: float = 1e-6, *,
               angle_symbols=(), hidden_symbols=(),
               defined: dict | None = None, defined_hidden=()) -> dict:
    """Evaluate one submitted line ("lhs = rhs") against known_values —
    the problem's givens plus the solver's own verified numeric answers.

    Returns:
        {"line": str, "status": "correct" | "incorrect" | "unverifiable" | "invalid",
         "lhs_value": float | None, "rhs_value": float | None, "detail": str}

    "invalid" = failed a security/syntax guard (safe_parse raised, or the
    line isn't a single equation) — reported as a short, safe message, never
    the raw exception text and never a crash.
    "unverifiable" = parsed fine, but at least one side references a symbol
    with no known numeric value (e.g. the unknown actually being solved
    for) — correctly NOT the same as "incorrect".

    angle_symbols: symbols whose known_values are radians converted from a
    degree given. Students write cos(30) as often as cos(theta), so a line
    that fails in radians is re-checked as a degree-mode calculator would
    read it (angle symbols back in degrees, trig taking degrees); it passes
    if either reading matches.

    hidden_symbols: symbols whose values are the solver's answers. A side
    that references one never has its value reported (lhs_value/rhs_value
    None, not in detail) — otherwise "N = 50" coming back as "left side =
    84.96" would hand the student the answer they're meant to work out.

    Symbols resolve through _resolve (aliases like f -> f_k, W = m*g, and
    `defined`: values from the student's own earlier lines). A line whose
    only unknown is a bare symbol on one side ("f = 0.25*N") is status
    "defined": nothing to check it against, but its value is returned in
    "defines" so check_work can make it available to later lines.
    """
    s = (line or "").strip()
    if not s:
        return _invalid(line, "empty line")

    for bad in ("==", "<=", ">=", "!="):
        if bad in s:
            return _invalid(line, "use a single '=' for one equation, e.g. N = m*g*cos(30)")

    if s.count("=") != 1:
        return _invalid(line, "each line needs exactly one '=' (e.g. N = m*g*cos(30))")

    lhs_str, rhs_str = s.split("=", 1)

    try:
        lhs_expr = safe_parse(lhs_str, allowed_symbols)
        rhs_expr = safe_parse(rhs_str, allowed_symbols)
    except UnsafeExpression as exc:
        return _invalid(line, str(exc))

    defined = defined or {}
    hidden = set(hidden_symbols)
    values, hidden_used, angles = {}, set(), set()
    missing = set()
    for sym in lhs_expr.free_symbols | rhs_expr.free_symbols:
        name = str(sym)
        resolved = _resolve(name, known_values, hidden, angle_symbols,
                            defined, set(defined_hidden))
        if resolved is None:
            missing.add(name)
            continue
        values[name], is_hidden, is_angle = resolved
        if is_hidden:
            hidden_used.add(name)
        if is_angle:
            angles.add(name)

    if missing:
        return _define_or_unverifiable(line, lhs_expr, rhs_expr, missing, values,
                                       hidden_used, angles)

    try:
        lhs_val, rhs_val = _numeric_sides(lhs_expr, rhs_expr, values, degree_mode=False)
        ok = math.isclose(lhs_val, rhs_val, rel_tol=rel_tol, abs_tol=abs_tol)
        has_trig = lhs_expr.has(*_TRIG, *_INVERSE_TRIG) or rhs_expr.has(*_TRIG, *_INVERSE_TRIG)
        if not ok and has_trig:
            degree_values = {k: math.degrees(v) if k in angles else v
                             for k, v in values.items()}
            d_lhs, d_rhs = _numeric_sides(lhs_expr, rhs_expr, degree_values, degree_mode=True)
            if math.isclose(d_lhs, d_rhs, rel_tol=rel_tol, abs_tol=abs_tol):
                ok, lhs_val, rhs_val = True, d_lhs, d_rhs
    except (TypeError, ValueError, OverflowError) as exc:
        return _invalid(line, f"could not evaluate numerically: {type(exc).__name__}")

    if not all(math.isfinite(v) for v in (lhs_val, rhs_val)):
        return _invalid(line, "a side works out to infinity or is undefined")

    lhs_shown = None if {str(x) for x in lhs_expr.free_symbols} & hidden_used else lhs_val
    rhs_shown = None if {str(x) for x in rhs_expr.free_symbols} & hidden_used else rhs_val

    if ok:
        detail = ""
    elif lhs_shown is not None and rhs_shown is not None:
        detail = f"left side = {lhs_val:.4g}, right side = {rhs_val:.4g}"
    elif rhs_shown is not None:
        detail = f"right side works out to {rhs_val:.4g}, which doesn't match"
    elif lhs_shown is not None:
        detail = f"left side works out to {lhs_val:.4g}, which doesn't match"
    else:
        detail = "these two sides don't match"

    return {
        "line": line,
        "status": "correct" if ok else "incorrect",
        "lhs_value": lhs_shown,
        "rhs_value": rhs_shown,
        "detail": detail,
    }


def _define_or_unverifiable(line, lhs_expr, rhs_expr, missing: set, values: dict,
                            hidden_used: set, angles: set) -> dict:
    """A line with unknowns: either it defines one new variable from
    things already known ("f = 0.25*N"), or it can't be checked yet."""
    unverifiable = {"line": line, "status": "unverifiable",
                    "detail": f"no known value yet for: {', '.join(sorted(missing))}",
                    "lhs_value": None, "rhs_value": None}
    if len(missing) != 1:
        return unverifiable
    [name] = missing
    target = sympy.Symbol(name)
    if lhs_expr == target and target not in rhs_expr.free_symbols:
        source = rhs_expr
    elif rhs_expr == target and target not in lhs_expr.free_symbols:
        source = lhs_expr
    else:
        return unverifiable

    degree_mode = _numeric_trig_args_look_like_degrees(source)
    vals = ({k: math.degrees(v) if k in angles else v for k, v in values.items()}
            if degree_mode else values)
    try:
        subs = {sympy.Symbol(k): sympy.Float(v) for k, v in vals.items()}
        expr = source.subs(subs)
        if degree_mode:
            expr = _to_degree_mode(expr)
        value = float(expr.evalf())
    except (TypeError, ValueError, OverflowError):
        return unverifiable
    if not math.isfinite(value):
        return _invalid(line, "a side works out to infinity or is undefined")

    is_hidden = bool({str(x) for x in source.free_symbols} & hidden_used)
    return {
        "line": line,
        "status": "defined",
        "detail": (f"saved {name} for later lines" if is_hidden
                   else f"saved {name} = {value:.4g} for later lines"),
        "lhs_value": None,
        "rhs_value": None,
        "defines": {"symbol": name, "value": value, "hidden": is_hidden},
    }


class CheckContext(NamedTuple):
    known_values: dict
    allowed_symbols: set
    angle_symbols: set
    hidden_symbols: set


_SYMBOL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,23}$")


def _is_safe_symbol_name(name) -> bool:
    return (isinstance(name, str) and bool(_SYMBOL_NAME_RE.match(name))
            and "__" not in name and name not in _RESERVED_NAMES
            and name not in _SAFE_NAMES)


def build_known_values(parsed_input: dict | None, solution: dict | None) -> CheckContext:
    """Turn the pipeline's own already-computed parsed_input (input_parser's
    output) and solution (solver's output) into what check_work needs. Pure
    data reshaping — no LLM call.

    parsed_input comes back from the browser, so symbol names from it are
    untrusted: anything that isn't a short plain identifier (or would shadow
    a parser helper or math function) is dropped rather than allowed.

    Angles given in degrees are converted to radians, since the checker's
    trig functions (sympy.sin/cos/tan/...) are radian-based, matching the
    convention the solver itself uses internally; they're also recorded in
    angle_symbols so check_line can try the degree-mode reading.

    g is always known (the problem's own gravity, default 9.81) since
    students write it in nearly every kinetics line whether or not the
    parser listed it as a given. The solver's final answers and
    intermediate values go into hidden_symbols so their values are never
    echoed back.
    """
    ctx = CheckContext({}, set(), set(), set())

    def _add(symbol, value, unit, hidden=False):
        if not _is_safe_symbol_name(symbol):
            return
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        if not math.isfinite(v):
            return
        if isinstance(unit, str) and unit.strip().lower() in ("deg", "degree", "degrees"):
            v = math.radians(v)
            ctx.angle_symbols.add(symbol)
        ctx.known_values[symbol] = v
        ctx.allowed_symbols.add(symbol)
        if hidden:
            ctx.hidden_symbols.add(symbol)

    parsed_input = parsed_input if isinstance(parsed_input, dict) else {}
    solution = solution if isinstance(solution, dict) else {}

    scenario = parsed_input.get("scenario")
    gravity = scenario.get("gravity") if isinstance(scenario, dict) else None
    _add("g", gravity if gravity is not None else 9.81, "m/s^2")

    for given in parsed_input.get("givens") or []:
        if isinstance(given, dict):
            _add(given.get("symbol"), given.get("value"), given.get("unit"))

    for unknown in parsed_input.get("unknowns_requested") or []:
        if isinstance(unknown, dict) and _is_safe_symbol_name(unknown.get("symbol")):
            ctx.allowed_symbols.add(unknown["symbol"])

    # intermediate_values: forces and other quantities the solver computed
    # on the way (N, f_k, W components...) — what students actually write
    # lines about. Hidden like final answers: a step is still a step.
    for key in ("intermediate_values", "final_answers"):
        for answer in solution.get(key) or []:
            if isinstance(answer, dict):
                _add(answer.get("symbol"), answer.get("value"), answer.get("unit"), hidden=True)

    return ctx


_MAX_LINES = 30


def check_work(lines: list, known_values: dict, allowed_symbols,
               rel_tol: float = 0.02, abs_tol: float = 1e-6, *,
               angle_symbols=(), hidden_symbols=()) -> dict:
    """Check the submitted lines in order and report the first
    confirmed-wrong one. Each line is checked against known_values (so one
    wrong line doesn't make later lines wrong), and a line that defines a
    new variable ("f = 0.25*N") makes it available to the lines after it.

    Returns {"results": [per-line dicts, see check_line], "first_wrong_index":
    int | None, "all_correct": bool}. all_correct is True only when there is
    at least one "correct" line and zero "incorrect" ones (unverifiable/
    invalid/defined lines don't count against it, but don't count as a
    finished correct solution either). Lines past _MAX_LINES are not checked."""
    defined: dict = {}
    defined_hidden: set = set()
    results = []
    for line in list(lines)[:_MAX_LINES]:
        result = check_line(line, known_values, allowed_symbols, rel_tol, abs_tol,
                            angle_symbols=angle_symbols, hidden_symbols=hidden_symbols,
                            defined=defined, defined_hidden=defined_hidden)
        definition = result.pop("defines", None)
        if definition:
            defined[definition["symbol"]] = definition["value"]
            if definition["hidden"]:
                defined_hidden.add(definition["symbol"])
        results.append(result)
    first_wrong_index = next(
        (i for i, r in enumerate(results) if r["status"] == "incorrect"), None
    )
    return {
        "results": results,
        "first_wrong_index": first_wrong_index,
        "all_correct": first_wrong_index is None and any(r["status"] == "correct" for r in results),
    }
