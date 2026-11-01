"""
Pilot item 9 — the show-your-work line checker. Pure SymPy/Python, no LLM
and no Anthropic client anywhere in this file, so none of these tests mock
anything: work_checker.py is deterministic and directly testable.

The injection tests are the important ones per the task's explicit security
requirement: confirm real attack strings are rejected, not merely that
"normal" input works.
"""
import math

import pytest

from agents.work_checker import (
    UnsafeExpression,
    build_known_values,
    check_line,
    check_work,
    safe_parse,
)


INCLINE_SYMBOLS = {"m", "g", "theta", "N", "mu_k", "f_k", "a"}
_THETA = math.radians(30)
# Givens only — N, f_k, a are the unknowns the student is solving for, not
# yet known.
INCLINE_GIVENS = {"m": 10.0, "g": 9.81, "theta": _THETA, "mu_k": 0.2}
# Givens plus the solver's own verified answers for N, f_k, a — this is what
# a real /check-work call would pass as known_values, since the solver has
# already computed every unknown before the student starts showing work.
_N = INCLINE_GIVENS["m"] * INCLINE_GIVENS["g"] * math.cos(_THETA)
_F_K = INCLINE_GIVENS["mu_k"] * _N
_A = INCLINE_GIVENS["g"] * math.sin(_THETA) - INCLINE_GIVENS["mu_k"] * INCLINE_GIVENS["g"] * math.cos(_THETA)
INCLINE_KNOWNS = dict(INCLINE_GIVENS, N=_N, f_k=_F_K, a=_A)


# --- Injection attempts: every one of these must be rejected ----------------

INJECTION_ATTEMPTS = [
    "__import__('os').system('echo pwned')",
    "().__class__.__bases__[0]",
    "N.__class__",
    "getattr(N, '__class__')",
    "exec('import os')",
    "eval('1+1')",
    "os.system('ls')",
    "__builtins__",
    "N; import os",
    "N or __import__('os')",
    "N.__globals__",
    "(1).__class__.__mro__",
    "open('/etc/passwd').read()",
    "N + os.environ['HOME']",
    "N # comment injection",
    "N + 'a'",
    "N + [1,2,3]",
    "N + {1:2}",
    "lambda: 1",
    "N if True else 0",
    "N \\ 2",
    "N & 1",
    "N | 1",
    "N << 1",
]


@pytest.mark.parametrize("expr", INJECTION_ATTEMPTS)
def test_safe_parse_rejects_injection_attempts(expr):
    with pytest.raises(UnsafeExpression):
        safe_parse(expr, INCLINE_SYMBOLS)


@pytest.mark.parametrize("expr", INJECTION_ATTEMPTS)
def test_check_line_never_raises_on_injection_attempts(expr):
    # check_line must catch everything and report "invalid" — never crash,
    # never leak a raw traceback, never silently succeed.
    line = f"N = {expr}"
    result = check_line(line, INCLINE_KNOWNS, INCLINE_SYMBOLS)
    assert result["status"] == "invalid"


def test_rejects_double_underscore_even_as_a_bare_identifier():
    with pytest.raises(UnsafeExpression):
        safe_parse("__secret", {"__secret"})


def test_rejects_attribute_style_dot():
    with pytest.raises(UnsafeExpression):
        safe_parse("N.real", INCLINE_SYMBOLS)


def test_rejects_leading_dot_decimal():
    with pytest.raises(UnsafeExpression):
        safe_parse(".5 * m", INCLINE_SYMBOLS)


def test_allows_ordinary_decimal():
    expr = safe_parse("9.81 * m", INCLINE_SYMBOLS)
    assert expr is not None


def test_rejects_overlong_line():
    with pytest.raises(UnsafeExpression):
        safe_parse("m + " * 100 + "m", INCLINE_SYMBOLS)


def test_rejects_unknown_identifier_not_in_allowlist():
    with pytest.raises(UnsafeExpression):
        safe_parse("secret_value * 2", INCLINE_SYMBOLS)


def test_rejects_disallowed_character():
    for bad_char_expr in ["N; DROP TABLE", "N`", "N$", "N[0]", "N{0}", "N'", 'N"', "N@x"]:
        with pytest.raises(UnsafeExpression):
            safe_parse(bad_char_expr, INCLINE_SYMBOLS)


def test_allows_single_underscore_physics_symbols():
    # mu_k, f_k, v_0-style subscript notation must keep working — only
    # double underscores are banned, not the character itself.
    expr = safe_parse("mu_k * N", INCLINE_SYMBOLS)
    assert expr is not None


def test_safe_functions_allowed():
    expr = safe_parse("cos(theta) * m * g", INCLINE_SYMBOLS)
    assert expr is not None


def test_unknown_function_name_rejected():
    with pytest.raises(UnsafeExpression):
        safe_parse("evil_func(N)", INCLINE_SYMBOLS)


# --- check_line: physics correctness -----------------------------------------

def test_check_line_correct_normal_force():
    # N = m*g*cos(theta) for a 10 kg block on a 30 deg incline
    result = check_line("N = m*g*cos(theta)", INCLINE_KNOWNS, INCLINE_SYMBOLS)
    assert result["status"] == "correct"
    assert math.isclose(result["lhs_value"], result["rhs_value"], rel_tol=0.02)


def test_check_line_incorrect_normal_force():
    # forgot the cosine — wrong physics, should be flagged incorrect
    result = check_line("N = m*g", INCLINE_KNOWNS, INCLINE_SYMBOLS)
    assert result["status"] == "incorrect"
    assert "left side" in result["detail"]


def test_check_line_unverifiable_when_target_symbol_unknown():
    # 'a' and 'f_k' aren't known yet in the givens-only dict — the student
    # hasn't derived them, so this line can't be checked numerically.
    result = check_line("a = f_k / m", INCLINE_GIVENS, INCLINE_SYMBOLS)
    assert result["status"] == "unverifiable"
    assert "f_k" in result["detail"]


def test_check_line_invalid_missing_equals():
    result = check_line("m*g*cos(theta)", INCLINE_KNOWNS, INCLINE_SYMBOLS)
    assert result["status"] == "invalid"


def test_check_line_invalid_double_equals():
    result = check_line("N == m*g*cos(theta)", INCLINE_KNOWNS, INCLINE_SYMBOLS)
    assert result["status"] == "invalid"


def test_check_line_invalid_two_equals_signs():
    result = check_line("N = m = g", INCLINE_KNOWNS, INCLINE_SYMBOLS)
    assert result["status"] == "invalid"


def test_check_line_empty_line():
    result = check_line("", INCLINE_KNOWNS, INCLINE_SYMBOLS)
    assert result["status"] == "invalid"


def test_check_line_tolerance_accepts_small_rounding():
    # student rounded g to 9.8 instead of 9.81 — should still pass within tolerance
    result = check_line("N = m*9.8*cos(theta)", INCLINE_KNOWNS, INCLINE_SYMBOLS)
    assert result["status"] == "correct"


def test_check_line_caret_exponent_supported():
    result = check_line("a = m^2", {"m": 3.0, "a": 9.0}, {"m", "a"})
    assert result["status"] == "correct"
    assert math.isclose(result["rhs_value"], 9.0)


# --- check_work: first-wrong-line reporting ----------------------------------

def test_check_work_all_correct():
    lines = ["N = m*g*cos(theta)"]
    result = check_work(lines, INCLINE_KNOWNS, INCLINE_SYMBOLS)
    assert result["all_correct"] is True
    assert result["first_wrong_index"] is None


def test_check_work_flags_first_wrong_line():
    lines = [
        "N = m*g*cos(theta)",   # correct
        "f_k = mu_k * N",        # correct (mu_k*N)
        "f_k = m * g",           # wrong — no cos, no mu_k
    ]
    result = check_work(lines, INCLINE_KNOWNS, INCLINE_SYMBOLS)
    assert result["first_wrong_index"] == 2
    assert result["results"][0]["status"] == "correct"
    assert result["results"][1]["status"] == "correct"
    assert result["results"][2]["status"] == "incorrect"
    assert result["all_correct"] is False


def test_check_work_reports_every_line_not_just_up_to_first_wrong():
    lines = ["N = m*g", "N = m*g*cos(theta)"]
    result = check_work(lines, INCLINE_KNOWNS, INCLINE_SYMBOLS)
    assert len(result["results"]) == 2
    assert result["first_wrong_index"] == 0


def test_check_work_unverifiable_lines_dont_count_as_wrong():
    lines = ["a = f_k / m"]
    result = check_work(lines, INCLINE_GIVENS, INCLINE_SYMBOLS)
    assert result["first_wrong_index"] is None
    assert result["all_correct"] is False
    assert result["results"][0]["status"] == "unverifiable"


def test_check_work_injection_line_reported_invalid_not_raised():
    lines = ["N = __import__('os').system('echo pwned')"]
    result = check_work(lines, INCLINE_KNOWNS, INCLINE_SYMBOLS)
    assert result["results"][0]["status"] == "invalid"
    assert result["first_wrong_index"] is None


# --- Resource exhaustion: must be rejected fast, never evaluated -------------
# Before the shape guard, "m = 9^9^9" hung a worker indefinitely (SymPy
# computes the exact ~370-million-digit integer while parsing).

RESOURCE_ATTACKS = [
    "9^9^9",
    "10^10^8",
    "9**9**9",
    "2^(3^20)",
    "9^999999",
    "2^(1/(1/9999))",
    "exp(exp(exp(99)))",
    "cosh(cosh(cosh(99)))",
    "exp(2^9^9)",
]


@pytest.mark.parametrize("expr", RESOURCE_ATTACKS)
def test_safe_parse_rejects_resource_exhaustion_shapes(expr):
    with pytest.raises(UnsafeExpression):
        safe_parse(expr, INCLINE_SYMBOLS)


def test_fractional_and_negative_exponents_still_allowed():
    assert check_line("a = m^(1/2)", {"m": 9.0, "a": 3.0}, {"m", "a"})["status"] == "correct"
    assert check_line("a = m^-1", {"m": 4.0, "a": 0.25}, {"m", "a"})["status"] == "correct"
    assert check_line("a = exp(m)^2", {"m": 1.0, "a": math.e ** 2}, {"m", "a"})["status"] == "correct"


def test_infinite_result_is_invalid_not_incorrect():
    result = check_line("m = exp(9^1000)", {"m": 1.0}, {"m"})
    assert result["status"] == "invalid"


def test_huge_substituted_value_does_not_hang():
    result = check_line("m = exp(m)^m", {"m": 1e300}, {"m"})
    assert result["status"] == "invalid"


# --- Degree-mode trig ---------------------------------------------------------

def test_numeric_degree_angle_accepted():
    # Students type cos(30) meaning degrees far more often than radians.
    result = check_line("N = m*g*cos(30)", INCLINE_KNOWNS, INCLINE_SYMBOLS,
                        angle_symbols={"theta"})
    assert result["status"] == "correct"


def test_radian_angle_symbol_still_accepted():
    result = check_line("N = m*g*cos(theta)", INCLINE_KNOWNS, INCLINE_SYMBOLS,
                        angle_symbols={"theta"})
    assert result["status"] == "correct"


def test_wrong_trig_function_still_incorrect_in_both_modes():
    result = check_line("N = m*g*sin(30)", INCLINE_KNOWNS, INCLINE_SYMBOLS,
                        angle_symbols={"theta"})
    assert result["status"] == "incorrect"


def test_inverse_trig_in_degrees():
    result = check_line("theta = atan(1/sqrt(3))", INCLINE_KNOWNS, INCLINE_SYMBOLS,
                        angle_symbols={"theta"})
    assert result["status"] == "correct"


# --- Hidden solver answers ---------------------------------------------------

def test_wrong_line_never_reveals_hidden_answer():
    result = check_line("N = 50", INCLINE_KNOWNS, INCLINE_SYMBOLS,
                        hidden_symbols={"N", "f_k", "a"})
    assert result["status"] == "incorrect"
    assert result["lhs_value"] is None
    assert f"{_N:.4g}" not in result["detail"]
    # The student's own side is fine to show.
    assert result["rhs_value"] == 50


def test_correct_line_with_hidden_symbol_has_no_hidden_value():
    result = check_line("f_k = mu_k * N", INCLINE_KNOWNS, INCLINE_SYMBOLS,
                        hidden_symbols={"N", "f_k", "a"})
    assert result["status"] == "correct"
    assert result["lhs_value"] is None and result["rhs_value"] is None


def test_check_work_caps_number_of_lines():
    result = check_work(["N = m*g*cos(theta)"] * 100, INCLINE_KNOWNS, INCLINE_SYMBOLS)
    assert len(result["results"]) == 30


# --- build_known_values -------------------------------------------------------

PARSED_INCLINE = {
    "scenario": {"gravity": 9.81},
    "givens": [
        {"symbol": "m", "value": 10, "unit": "kg"},
        {"symbol": "theta", "value": 30, "unit": "deg"},
        {"symbol": "mu_k", "value": 0.2, "unit": ""},
    ],
    "unknowns_requested": [{"symbol": "N"}, {"symbol": "a"}],
}


def test_build_known_values_converts_degrees_and_adds_g():
    ctx = build_known_values(PARSED_INCLINE, None)
    assert math.isclose(ctx.known_values["theta"], _THETA)
    assert ctx.angle_symbols == {"theta"}
    assert ctx.known_values["g"] == 9.81
    assert {"N", "a"} <= ctx.allowed_symbols
    assert "N" not in ctx.known_values
    assert ctx.hidden_symbols == set()


def test_build_known_values_marks_solver_answers_hidden():
    solution = {"final_answers": [{"symbol": "N", "value": _N, "unit": "N"}]}
    ctx = build_known_values(PARSED_INCLINE, solution)
    assert ctx.known_values["N"] == _N
    assert ctx.hidden_symbols == {"N"}


@pytest.mark.parametrize("bad", ["__import__", "a.b", "os system", "Integer", "Symbol",
                                 "sin", "x" * 40, "", None, 5, "1abc"])
def test_build_known_values_drops_unsafe_symbol_names(bad):
    parsed = {"givens": [{"symbol": bad, "value": 1, "unit": ""}],
              "unknowns_requested": [{"symbol": bad}]}
    ctx = build_known_values(parsed, None)
    assert ctx.allowed_symbols == {"g"}


def test_build_known_values_ignores_non_numeric_and_non_finite_values():
    parsed = {"givens": [{"symbol": "m", "value": "ten", "unit": "kg"},
                         {"symbol": "k", "value": float("inf"), "unit": ""}]}
    ctx = build_known_values(parsed, None)
    assert "m" not in ctx.known_values and "k" not in ctx.known_values


def test_build_known_values_tolerates_garbage_input():
    ctx = build_known_values("not a dict", ["nor", "this"])
    assert ctx.known_values == {"g": 9.81}


# --- Physics symbols, aliases, and line-to-line definitions -----------------

@pytest.mark.parametrize("name", ["N", "f", "f_k", "W", "T", "F", "a", "v", "x", "y",
                                  "theta", "mu", "omega", "alpha", "v_0", "F_x", "T_1",
                                  "theta_1", "mu_s", "Ax", "By", "v0", "omega_z", "E", "I"])
def test_common_physics_symbols_parse(name):
    expr = safe_parse(f"{name} * 2", set())
    assert {str(s) for s in expr.free_symbols} == {name}


@pytest.mark.parametrize("bad", ["if", "or", "in", "is", "not", "and",
                                 "Integer", "Symbol", "secret_value", "lambda",
                                 "abcd", "x_toolong"])
def test_non_physics_names_still_rejected(bad):
    with pytest.raises(UnsafeExpression):
        safe_parse(f"{bad} + 1", set())


def test_physics_symbol_cannot_reach_a_sympy_function():
    # "N" is SymPy's numeric-evaluation function and "E"/"I" are constants
    # in the parser's namespace; as student variables they must be plain
    # symbols, never the SymPy objects.
    expr = safe_parse("N + E + I + S", set())
    assert all(isinstance(s, __import__("sympy").Symbol) for s in expr.args)


def test_alias_student_f_uses_solver_f_k():
    knowns = dict(INCLINE_KNOWNS)
    result = check_line("f = mu*N", knowns, set(), hidden_symbols={"N", "f_k"})
    assert result["status"] == "correct"


def test_weight_is_derived_from_m_and_g():
    result = check_line("W = m*g", INCLINE_GIVENS, set())
    assert result["status"] == "correct"
    assert check_line("W = 50", INCLINE_GIVENS, set())["status"] == "incorrect"


def test_definition_carries_to_later_lines():
    result = check_work(["x = 3*m", "y = x + 1", "y = 31", "y = 5"], INCLINE_GIVENS, set())
    assert [r["status"] for r in result["results"]] == ["defined", "defined", "correct", "incorrect"]
    assert "x = 30" in result["results"][0]["detail"]


def test_definition_with_degree_literal_uses_degrees():
    result = check_work(["P = m*g*cos(30)", f"P = {_N}"], INCLINE_GIVENS, set())
    assert [r["status"] for r in result["results"]] == ["defined", "correct"]


def test_known_value_beats_a_wrong_earlier_definition():
    # N is known from the solver: "N = m*g" is simply wrong, and doesn't
    # redefine N for later lines.
    result = check_work(["N = m*g", "N = m*g*cos(theta)"], INCLINE_KNOWNS, set())
    assert [r["status"] for r in result["results"]] == ["incorrect", "correct"]


def test_definition_from_hidden_value_does_not_reveal_it():
    result = check_work(["P = N", "P = 1"], INCLINE_KNOWNS, set(), hidden_symbols={"N"})
    assert result["results"][0]["detail"] == "saved P for later lines"
    assert f"{_N:.4g}" not in str(result)


def test_two_unknowns_stay_unverifiable():
    result = check_line("T = a*m + x", INCLINE_GIVENS, set())
    assert result["status"] == "unverifiable"


def test_build_known_values_includes_intermediate_values_as_hidden():
    solution = {"final_answers": [{"symbol": "a", "value": 1.0, "unit": "m/s^2"}],
                "intermediate_values": [{"symbol": "F_N", "value": _N, "unit": "N"}]}
    ctx = build_known_values(PARSED_INCLINE, solution)
    assert ctx.known_values["F_N"] == _N
    assert {"a", "F_N"} <= ctx.hidden_symbols
