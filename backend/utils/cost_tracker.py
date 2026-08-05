"""
cost_tracker.py — rough API-cost estimator for the tutoring pipeline.

This module turns the agent pipelines defined in ``agents/orchestrator.py`` into
back-of-the-envelope dollar figures so we can reason about per-interaction and
per-semester spend without instrumenting live traffic.

The numbers here are *estimates*: each route is modelled as a fixed list of
agent calls, and each agent call is assigned an average input/output token
count plus the model it actually runs on in the orchestrator. Real usage will
vary with problem length and retries, but the mix of models and the order of
magnitude are representative.

Run it directly for a formatted report:

    python -m utils.cost_tracker      # from the backend/ directory
    python utils/cost_tracker.py
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# 1. Per-model token costs (USD per 1,000,000 tokens)
# ---------------------------------------------------------------------------
# Model ids match the ones used in agents/orchestrator.py.
MODEL_COSTS: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-opus-4-7": {"input": 15.00, "output": 75.00},
}

# Short aliases so the pipeline tables below read cleanly.
_HAIKU = "claude-haiku-4-5-20251001"
_SONNET = "claude-sonnet-4-6"
_OPUS = "claude-opus-4-7"

_MILLION = 1_000_000


def _agent_cost(model: str, tokens_input: int, tokens_output: int) -> float:
    """USD cost of a single agent call at the given token counts."""
    rates = MODEL_COSTS[model]
    return (
        tokens_input / _MILLION * rates["input"]
        + tokens_output / _MILLION * rates["output"]
    )


# ---------------------------------------------------------------------------
# 2. Average token estimates per route
# ---------------------------------------------------------------------------
# Each route is a list of agent calls: (label, model, avg_input, avg_output).
# The models mirror what each agent actually uses in the orchestrator, and the
# agent-call counts match the pipeline sizes:
#   SMALLTALK / CONCEPT ... 1 call   (Direct Tutor)
#   PROBLEM  (HINT) ....... 5 calls
#   PROBLEM  (SOLVE) ...... 7 calls
#   CREATE ................ 6 calls
#   DRAW .................. 4 calls
ROUTE_PIPELINES: dict[str, list[tuple[str, str, int, int]]] = {
    # Single Direct Tutor call on Sonnet (~500 in / ~300 out).
    "SMALLTALK": [
        ("direct_tutor", _SONNET, 500, 300),
    ],
    "CONCEPT": [
        ("direct_tutor", _SONNET, 500, 300),
    ],
    # PROBLEM that ends in a HINT (no solve): 5 agent calls.
    "PROBLEM_HINT": [
        ("router", _HAIKU, 600, 80),
        ("input_parser", _HAIKU, 500, 400),
        ("student_modeler", _SONNET, 800, 400),
        ("pedagogical_planner", _OPUS, 900, 300),
        ("conversationalist", _SONNET, 1500, 800),
    ],
    # PROBLEM that ends in a full SOLVE: 7 agent calls.
    "PROBLEM_SOLVE": [
        ("input_parser", _HAIKU, 500, 400),
        ("student_modeler", _SONNET, 800, 400),
        ("pedagogical_planner", _OPUS, 900, 300),
        ("solver", _SONNET, 600, 1200),
        ("validator", _SONNET, 1200, 500),
        ("visualizer", _OPUS, 800, 700),
        ("conversationalist", _SONNET, 1500, 800),
    ],
    # CREATE (generate practice problems): 6 agent calls.
    "CREATE": [
        ("student_modeler", _SONNET, 800, 400),
        ("pedagogical_planner", _OPUS, 900, 300),
        ("creator", _OPUS, 800, 1500),
        ("validator", _SONNET, 1200, 500),
        ("visualizer", _OPUS, 800, 700),
        ("conversationalist", _SONNET, 1500, 800),
    ],
    # DRAW (render a diagram, no solve): 4 agent calls.
    "DRAW": [
        ("input_parser", _HAIKU, 500, 400),
        ("visualizer", _OPUS, 800, 700),
        ("schematic_layout", _SONNET, 700, 1000),
        ("conversationalist", _SONNET, 1500, 800),
    ],
}

# Routes surfaced in the /cost-estimate endpoint and the printed report.
REPORT_ROUTES: list[str] = [
    "SMALLTALK",
    "CONCEPT",
    "PROBLEM_HINT",
    "PROBLEM_SOLVE",
    "CREATE",
    "DRAW",
]

# A generic "PROBLEM" interaction is a blend of hint-only and full-solve turns.
# Weights (hint, solve) — tweak if real usage skews one way.
_PROBLEM_HINT_SOLVE_SPLIT: tuple[float, float] = (0.5, 0.5)


def _blend(estimates: list[tuple[dict, float]]) -> dict:
    """Weighted-average a list of (route_estimate, weight) into one estimate."""
    total_weight = sum(w for _, w in estimates) or 1.0
    tokens_input = sum(e["tokens_input"] * w for e, w in estimates) / total_weight
    tokens_output = sum(e["tokens_output"] * w for e, w in estimates) / total_weight
    cost = sum(e["cost_usd"] * w for e, w in estimates) / total_weight
    agent_calls = sum(e["agent_calls"] * w for e, w in estimates) / total_weight
    return {
        "tokens_input": round(tokens_input),
        "tokens_output": round(tokens_output),
        "cost_usd": round(cost, 6),
        "agent_calls": round(agent_calls, 1),
    }


# ---------------------------------------------------------------------------
# 3. Estimation functions
# ---------------------------------------------------------------------------
def estimate_route_cost(route: str) -> dict:
    """
    Estimate the cost of a single interaction on ``route``.

    Returns a dict with at least ``tokens_input``, ``tokens_output`` and
    ``cost_usd`` (plus ``route``, ``agent_calls`` and a per-agent ``breakdown``).

    Accepts the concrete routes in ``ROUTE_PIPELINES`` as well as the generic
    ``"PROBLEM"``, which is a weighted blend of PROBLEM_HINT and PROBLEM_SOLVE.
    """
    key = (route or "").strip().upper()

    if key == "PROBLEM":
        hint_w, solve_w = _PROBLEM_HINT_SOLVE_SPLIT
        blended = _blend([
            (estimate_route_cost("PROBLEM_HINT"), hint_w),
            (estimate_route_cost("PROBLEM_SOLVE"), solve_w),
        ])
        blended["route"] = "PROBLEM"
        blended["breakdown"] = []
        return blended

    if key not in ROUTE_PIPELINES:
        raise ValueError(
            f"Unknown route {route!r}. Known routes: "
            f"{', '.join(sorted(ROUTE_PIPELINES) + ['PROBLEM'])}"
        )

    pipeline = ROUTE_PIPELINES[key]
    tokens_input = 0
    tokens_output = 0
    cost = 0.0
    breakdown = []
    for label, model, t_in, t_out in pipeline:
        agent_cost = _agent_cost(model, t_in, t_out)
        tokens_input += t_in
        tokens_output += t_out
        cost += agent_cost
        breakdown.append({
            "agent": label,
            "model": model,
            "tokens_input": t_in,
            "tokens_output": t_out,
            "cost_usd": round(agent_cost, 6),
        })

    return {
        "route": key,
        "agent_calls": len(pipeline),
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "cost_usd": round(cost, 6),
        "breakdown": breakdown,
    }


def estimate_student_semester_cost(
    problems_per_week: int,
    weeks: int,
    route_distribution: dict,
) -> dict:
    """
    Estimate a single student's API cost over a semester.

    ``route_distribution`` maps a route name (any accepted by
    ``estimate_route_cost``, e.g. ``PROBLEM``, ``CONCEPT``, ``CREATE``,
    ``SMALLTALK``) to the fraction of interactions on that route. Fractions are
    used as given (they need not sum to exactly 1.0).
    """
    total_interactions = problems_per_week * weeks

    per_route: dict[str, dict] = {}
    total_tokens_input = 0.0
    total_tokens_output = 0.0
    total_cost = 0.0

    for route, fraction in route_distribution.items():
        est = estimate_route_cost(route)
        interactions = total_interactions * fraction
        route_tokens_input = est["tokens_input"] * interactions
        route_tokens_output = est["tokens_output"] * interactions
        route_cost = est["cost_usd"] * interactions

        per_route[route] = {
            "fraction": fraction,
            "interactions": round(interactions, 2),
            "cost_per_interaction_usd": est["cost_usd"],
            "tokens_input": round(route_tokens_input),
            "tokens_output": round(route_tokens_output),
            "cost_usd": round(route_cost, 4),
        }
        total_tokens_input += route_tokens_input
        total_tokens_output += route_tokens_output
        total_cost += route_cost

    return {
        "problems_per_week": problems_per_week,
        "weeks": weeks,
        "total_interactions": total_interactions,
        "route_distribution": route_distribution,
        "per_route": per_route,
        "total_tokens_input": round(total_tokens_input),
        "total_tokens_output": round(total_tokens_output),
        "total_cost_usd": round(total_cost, 4),
        "cost_per_interaction_usd": round(
            total_cost / total_interactions, 6
        ) if total_interactions else 0.0,
    }


# ---------------------------------------------------------------------------
# 4. Reporting
# ---------------------------------------------------------------------------
def print_cost_report() -> None:
    """Print a formatted per-route cost breakdown (cost of one interaction)."""
    print("=" * 72)
    print("ClassroomLM — estimated cost per interaction, by route")
    print("=" * 72)
    print(
        f"{'Route':<16}{'Calls':>6}{'In tok':>10}{'Out tok':>10}"
        f"{'Cost/interaction':>20}"
    )
    print("-" * 72)
    for route in REPORT_ROUTES:
        est = estimate_route_cost(route)
        print(
            f"{est['route']:<16}"
            f"{est['agent_calls']:>6}"
            f"{est['tokens_input']:>10,}"
            f"{est['tokens_output']:>10,}"
            f"{'$' + format(est['cost_usd'], '.4f'):>20}"
        )
    print("=" * 72)


def print_semester_report(
    problems_per_week: int,
    weeks: int,
    route_distribution: dict,
) -> None:
    """Print a formatted semester cost report for a single student."""
    report = estimate_student_semester_cost(
        problems_per_week, weeks, route_distribution
    )
    print()
    print("=" * 72)
    print("ClassroomLM — estimated semester cost, single student")
    print("=" * 72)
    print(
        f"Assumptions: {problems_per_week} interactions/week x {weeks} weeks "
        f"= {report['total_interactions']} interactions"
    )
    print("Route distribution: " + ", ".join(
        f"{route} {fraction:.0%}"
        for route, fraction in route_distribution.items()
    ))
    print("-" * 72)
    print(
        f"{'Route':<12}{'Share':>7}{'Interactions':>14}"
        f"{'$/interaction':>16}{'Subtotal':>14}"
    )
    print("-" * 72)
    for route, row in report["per_route"].items():
        print(
            f"{route:<12}"
            f"{row['fraction']:>7.0%}"
            f"{row['interactions']:>14.1f}"
            f"{'$' + format(row['cost_per_interaction_usd'], '.4f'):>16}"
            f"{'$' + format(row['cost_usd'], '.2f'):>14}"
        )
    print("-" * 72)
    print(
        f"Total tokens: {report['total_tokens_input']:,} in / "
        f"{report['total_tokens_output']:,} out"
    )
    print(
        f"Average cost per interaction: "
        f"${report['cost_per_interaction_usd']:.4f}"
    )
    print(f"TOTAL SEMESTER COST PER STUDENT: ${report['total_cost_usd']:.2f}")
    print("=" * 72)


# ---------------------------------------------------------------------------
# 5. Script entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Typical student: 2 problems/week for 16 weeks, mostly PROBLEM work.
    TYPICAL_DISTRIBUTION = {
        "PROBLEM": 0.60,
        "CONCEPT": 0.20,
        "CREATE": 0.10,
        "SMALLTALK": 0.10,
    }

    print_cost_report()
    print_semester_report(
        problems_per_week=2,
        weeks=16,
        route_distribution=TYPICAL_DISTRIBUTION,
    )
