"""
Dev-only mock for /tutor/stream: a canned tutor reply sent in irregular
bursts, with inline and display math, so the frontend's stream smoothing can
be tried in a browser with zero API calls.

Off by default. Turn it on with MOCK_TUTOR_STREAM=1 in backend/.env (or the
environment). When it's on, /tutor/stream never builds the orchestrator, so no
agent runs, nothing is logged, and no usage is counted.
"""
import os
import random
import re
import time

MOCK_REPLY = r"""Good start. Let's set up equilibrium for the beam.

**Step 1: Free body diagram.** The pin at $A$ gives two reactions, $A_x$ and $A_y$. The roller at $B$ gives one vertical reaction, $B_y$.

**Step 2: Sum the moments about A.** Taking counterclockwise as positive:

$$
\sum M_A = B_y (4\,\text{m}) - (500\,\text{N})(2\,\text{m}) = 0
$$

so $B_y = \frac{1000\,\text{N·m}}{4\,\text{m}} = 250\,\text{N}$.

**Step 3: Sum the forces.**

- Horizontal: $\sum F_x = A_x = 0$
- Vertical: $\sum F_y = A_y + B_y - 500\,\text{N} = 0$, so $A_y = 250\,\text{N}$

Both supports carry half the load, which makes sense because the force sits at the midpoint. What would change if the load moved to $x = 1\,\text{m}$?"""


def enabled() -> bool:
    return os.environ.get("MOCK_TUTOR_STREAM", "").strip().lower() in {"1", "true", "yes", "on"}


def _tokens(text: str) -> list[str]:
    """Split text into pieces about the size of model tokens."""
    return re.findall(r"\s*\S{1,4}|\s+", text)


def mock_events(student_model: dict, rng: random.Random | None = None, sleep=time.sleep):
    """Yield the same event shapes run_stream() does: status lines, one meta
    event, then the reply as token events. Tokens come in clumps (several
    with no pause between them, so they share a network read) separated by
    uneven gaps, with an occasional long stall, like a real stream."""
    rng = rng or random.Random()
    yield {"type": "status", "text": "Reading the problem…"}
    sleep(0.4)
    yield {"type": "status", "text": "Solving…"}
    sleep(0.5)
    yield {"type": "meta", "student_model": student_model, "route": "PROBLEM",
           "decision": "LLM", "diagram_svg": ""}

    tokens = _tokens(MOCK_REPLY)
    i = 0
    while i < len(tokens):
        clump = rng.randint(1, 12)
        for tok in tokens[i:i + clump]:
            yield {"type": "token", "text": tok}
        i += clump
        sleep(rng.uniform(0.4, 0.9) if rng.random() < 0.1 else rng.uniform(0.02, 0.15))
    yield {"type": "done"}
