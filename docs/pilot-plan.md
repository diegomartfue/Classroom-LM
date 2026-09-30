# ClassroomLM Pilot Plan (~10 students)

Backend paths are relative to `backend/`. No real API calls will be made
while building or testing this — every test mocks the Anthropic client, and
the frontend build/dev-server checks point `VITE_API_BASE` at an unreachable
address.

## Two things worth flagging before the item list

**AuthContext isn't actually live.** `src/App.tsx` mounts `<ClassroomLM />`
directly, with no `<AuthProvider>` wrapper, and `ClassroomLM.tsx` never calls
`useAuth()`. The sidebar's "Emu / Undergraduate · UTEP" card is a hardcoded
string, not derived from any session. There is no login screen wired to the
live app and no backend user database — `AuthContext.tsx` is dead scaffolding
from an earlier design. So "the logged in user from AuthContext" doesn't
exist to read from today. For a 10-student pilot with no real auth system,
the pragmatic, deterministic substitute is a **stable per-browser student id**
generated once and kept in `localStorage` (same persistence tier the app
already uses for `sidebarCollapsed`), sent as `student_id` on every request.
This satisfies every item that needs *some* stable student identity (1, 4, 6,
7) without building a login system, which is out of scope for "build on what
exists." Flagged here rather than silently reinterpreted.

**Scale.** This is a large list for one pass. Item 9 is explicitly called out
as biggest; item 10 explicitly says build-don't-run. I'm going through 1→10
in order and will mark any item that turns out bigger than expected rather
than half-finishing it silently.

---

## Item 1 — Save everything on the server

**Exists today:** `agents/memory.py` (`SessionMemory`) already has
`log_turn`, `log_error`, `save_student_model`, all file-based and defensive
(never raise). `run()` (`agents/orchestrator.py:966`) uses all three via a
per-agent `_log()` closure inside `_run_turn()`. `run_stream()`
(`agents/orchestrator.py:1366`) calls `self.memory` **zero times** — confirmed
by grep. It also doesn't currently accept `session_id`/`student_id`
parameters at all, and neither does `TutorRequest` (`main.py:56`) or the
`/tutor/stream` endpoint (`main.py:268`).

**Change:** Add `session_id`/`student_id` to `TutorRequest` and thread them
into `agent.run_stream(...)`. Give `run_stream()` the same two params `run()`
has. Rather than replicating `_run_turn`'s granular per-agent journal (which
would mean touching ~15 yield points across 4 route branches), wrap the
existing generator: a thin outer generator that creates the session, iterates
the inner one forwarding every event, captures the `student_model` from
whichever `meta` event carries it, and on the generator's natural end (or an
exception — ties into item 3) logs **one consolidated turn record** (route,
decision, final response text, student model) via `memory.log_turn` and
calls `memory.save_student_model`. Frontend: generate/persist a per-browser
student id, send it as `student_id` alongside `doc_ids` on `/tutor/stream`.

**Risk:** consolidated-per-turn logging is coarser than `run()`'s per-agent
trace (no intermediate agent outputs for a streamed turn). Calling this out
rather than silently matching `run()`'s granularity, which would require far
more invasive surgery on a 300-line generator for a pilot-scale ask.

## Item 2 — Spending limit

**Exists today:** `utils/cost_tracker.py` is a *theoretical* estimator
(hardcoded average tokens per route) — useful for the `/cost-estimate`
endpoint, not real usage. Nothing logs `response.usage` from an actual call
anywhere in the codebase.

**Change:** New `utils/usage_tracker.py`: a `DailyUsageTracker` that appends
`{ts, model, input_tokens, output_tokens, cost_usd}` to
`backend/state/usage/{date}.json` (atomic write, same pattern as
`memory.py`), and a `limit_reached()` check against `DAILY_COST_LIMIT_USD`
(env var, sensible default). Wrap `OrchestratorAgent.client` at construction
with a small proxy (`UsageTrackingClient`, unit-testable standalone) whose
`.messages.create(**kw)`: checks the limit first and raises a distinct
`DailyLimitReached` exception if hit (never calls the real client); otherwise
calls through and records `response.usage`. `run()`/`run_stream()` catch that
exception specifically and return/yield the "resting for today" message —
this reuses the same top-level try/except item 3 is already touching.

**Risk:** none major. This is the one item that's almost entirely new
infrastructure, but it's small and isolated (one wrapper class).

## Item 3 — No dead ends

**Exists today:** `/tutor` (`main.py:236`) already catches exceptions and
returns a graceful `TutorResponse`. `/tutor/stream`'s `event_gen()`
(`main.py:280`) already catches exceptions and yields a `{"type": "error"}`
event with a request id — but `run_stream()` itself has no internal
try/except, so a mid-generator exception unwinds the whole generator (any
`yield`s already sent stay sent; nothing after the exception runs, including
the item-1 logging). Frontend `sendMessage()`
(`ClassroomLM.tsx:401`) catches network errors, but: no Retry button
anywhere, and both the SSE `error` event text and the catch-block network
error message get written into `conversationHistoryRef` as if they were a
real assistant reply — meaning a transient failure poisons every future
turn's context.

**Change:** Backend: wrap `run_stream()`'s body in try/except (needed for
item 2 either way) so a mid-stream failure still logs and yields the
friendly error event instead of a bare unwind. Frontend: track the last user
message text; on error, show a "Something went wrong — Retry" affordance
next to the failed message instead of inline error text, and do **not**
append the error text to `conversationHistoryRef`/persisted history.

**Risk:** low. Mostly wiring existing pieces together.

## Item 4 — Tutor remembers you

**Exists today:** `memory.get_student_model(student_id)` already exists and
is defensive (`agents/memory.py`), but nothing calls it — `run()` and
`run_stream()` both take `student_model` as a plain request parameter with no
load step; the frontend always starts `studentModel` at `{}`.

**Change:** On `/tutor` and `/tutor/stream`, if the incoming `student_model`
is empty and a `student_id` is present, load
`memory.get_student_model(student_id)` and use that as the starting model
(load failure → `{}`, already guaranteed by `get_student_model`'s own
try/except). Frontend: once a `student_id` exists, nothing else changes —
the backend does the loading.

**Risk:** low, small addition on top of item 1's plumbing.

## Item 5 — Classic mistake detector

**Exists today:** `docs/misconceptions.md` (133 lines, 22 entries,
ID + description + symptoms + remediation) — confirmed unused anywhere in
`backend/` by grep. Separately, `STUDENT_MODELER_PROMPT`
(`agents/orchestrator.py:152`) already has its own **smaller**, hand-written
19-item inline list (different id scheme, no remediation text) and already
outputs `observed_misconceptions`. `PEDAGOGICAL_PLANNER_PROMPT`
(`:219`) already has a rule ("If student_model shows an observed
misconception, ASK a question that surfaces it before hinting") and already
outputs `target_misconception`. `conversationalist()` (`:930`) already
receives the full `plan` dict (including `target_misconception`) in its
context bundle. So detection-and-targeting is already wired end to end — the
actual gap is narrower than it looks: **no remediation text ever reaches the
conversationalist**, so it has to improvise an explanation from a bare id
string.

**Change:** Small parser (`agents/misconceptions.py`) that loads
`docs/misconceptions.md` into `{id: {description, address}}` at import time
(deterministic, unit-tested against the real file). When
`plan.target_misconception` is set, look up the closest match (small manual
alias map from the 19 existing snake_case ids to the doc's ID scheme where
they overlap) and add *only that one entry's* address text as a new
`misconception_guidance` key in the conversationalist's context bundle —
one sentence, not the whole catalog.

**Risk:** the id-scheme mismatch means the alias map will be partial/manual,
not a full crosswalk. Documented rather than silently claiming full coverage.

## Item 6 — Thumbs up/down

**Exists today:** Copy button lives in `MessageView`'s author row,
`ClassroomLM.tsx` (`clm-copy-btn`, ~line 878). No feedback storage anywhere.

**Change:** New `POST /feedback` endpoint + `FeedbackStore` (file-based,
append-only JSONL, same shape as `memory.log_error`) recording
`{session_id, turn_number, student_id, rating, timestamp}`. Two small icon
buttons next to Copy, same visual treatment. No LLM call.

**Risk:** low.

## Item 7 — Hint button

**Exists today:** `PEDAGOGICAL_PLANNER_PROMPT`'s `HINT` decision already has
a 3-level hint ladder per family (FBD/Equations/Solving), but
`CONVERSATIONALIST_PROMPT`'s hard rule is unconditional: "HINT: do NOT give
the answer" — there is no level-4 path that ever reveals a value through the
normal HINT decision.

**Change:** Track a hint level **per problem** (client-side, keyed by a
stable hash of the parsed problem's `raw_summary`, since there's no problem
id) that increments on each Hint-button tap. Level 1–3 route through the
existing planner HINT payload/ladder unchanged. Level 4 is a distinct,
explicit "reveal" path — sent as its own signal to the planner (not a
disguised HINT) so `CONVERSATIONALIST_PROMPT`'s "do NOT give the answer" rule
is never silently violated; instead the SOLVE path's existing (verified,
validated) answer-revealing behavior is reused for level 4, with the planner
prompt updated to accept "student explicitly requested the answer via the
hint ladder" as a fourth `permission_source` alongside its existing three.

**Risk:** medium. Reworking "student stuck for several turns" behavior
touches pedagogical judgment call sites; keeping levels 1–3 on the existing
ladder and only special-casing level 4 minimizes the blast radius.

## Item 8 — Ask instead of guessing

**Exists today:** Router already outputs `problem_scope`
(`self_contained`/`referential`, `:552`), and `_draw_history()` (`:1707`)
already uses it to decide whether history is kept. What's missing: when
`referential` and there is genuinely **no prior problem in history** (fresh
session, or history contains no problem-shaped content), the pipeline still
calls `input_parser`/`visualizer` and gets *something* — likely a guess.

**Change:** Deterministic check (no extra LLM call — reuses the router
result already computed): if `problem_scope == "referential"` and
`conversation_history` is empty or contains no prior user message that looks
like a problem statement, short-circuit before `input_parser` and respond
with a clarifying question ("Which problem are you referring to?").

**Risk:** the "no problem-shaped content in history" check is itself a
heuristic (not perfect); scoping it to the clear, cheap case (empty/no-prior
history) rather than attempting full semantic detection of "was there ever a
real problem in this conversation."

## Item 9 — Show-your-work checker (biggest item)

**Exists today:** `sympy_solver.py` calls `parse_expr` directly on
regex-extracted raw text with **zero sanitization** — this is the legacy
`/chat` path's pattern and is exactly what the task warns against; it will
not be reused.

**Change:** New `agents/work_checker.py`:
- `safe_parse(expr_str, allowed_symbols)`: length cap, character whitelist
  (`^[A-Za-z0-9_.+\-*/^()=. ]+$` minus the disallowed set below), reject any
  `_` (blocks dunder/attribute-style tricks) or `.` used outside a decimal
  number (blocks attribute access), tokenize identifiers and reject any not
  in an explicit allowlist (problem symbols + a fixed safe math-function set:
  `sin cos tan sqrt Abs pi` etc.), then `parse_expr` with
  `global_dict={"__builtins__": {}}` and a `local_dict` built only from the
  allowlist, `evaluate=False` first pass to inspect the tree before
  evaluating. Never `eval`/`exec` directly — SymPy's own guarded parse is the
  only interpreter used, with the allowlist as the actual security boundary.
- `check_line(line, givens, known_values)`: split on `=`, evaluate both
  sides substituting givens/solver values, compare within tolerance.
- `check_work(lines, ...)`: evaluate in order, stop at (and report) the first
  wrong line.
- New `POST /check-work` endpoint. Small frontend addition: a line-by-line
  input under the composer, one row per submitted line, ✓/✗ per row.

**Tests:** explicit injection attempts (`__import__`, `os.system`, attribute
chains, `exec(...)`, overlong input, disallowed names) asserted rejected,
plus correct/incorrect physics lines.

**Risk:** highest-effort item, exactly as flagged in the prompt. If the
allowlist/parsing core eats the whole budget, the frontend UI may be trimmed
to "one line at a time, no fancy diffing" rather than dropped — the security
core is non-negotiable, the UI polish is not.

## Item 10 — Eval harness (build only)

**Exists today:** `evals/` doesn't exist yet (only referenced in
`CLAUDE.md` as `python -m evals.run --suite projectile_v1`, which doesn't
match anything on disk — aspirational doc, not code).

**Change:** `evals/problems.py` (8 problems: crate on incline, beam
reactions, pendulum, ladder kinematics, pushed box, follow-up "same thing but
20 kg", missing-context "draw that", one Spanish-language problem) each with
an expected route/decision/key-value shape. `evals/run.py`: one command,
`--mode mocked` (default, canned responses, runs under pytest, zero API
calls) and `--mode live` (real calls — **not invoked this session**). Cost
estimate for one live run computed from `utils/cost_tracker.py`'s existing
route estimates, printed, never executed.

**Risk:** low — this is scaffolding, not the risky part.

---

## Progress

**Item 1 — done.** `run_stream()` is now a thin wrapper (`agents/orchestrator.py`)
around the renamed `_run_stream_events()`: creates the session, watches
"meta"/"token"/"error" events as they're forwarded, logs one consolidated
turn record and saves the student model in a `finally` (runs on normal
completion, a caught mid-stream exception, or early generator close). Added
`session_id`/`student_id` to `TutorRequest` and threaded them through both
`/tutor` and `/tutor/stream` in `main.py`. Frontend: `loadStudentId()`
(localStorage, generated once) sent as `student_id`; the existing
conversation `activeId` doubles as `session_id` (one frontend conversation =
one backend session — no new id needed). Updated
`test_upstream_agent_failure_propagates_out_of_run_stream` (the old
contract — raw propagation — is superseded by item 3's requirement) and the
`FailingAgent` stub in `test_stream_error_path.py` (was missing the new
kwargs, which was accidentally masking its intended RuntimeError scenario
behind a TypeError). Added `tests/test_run_stream_memory.py` (5 tests).
`pytest`: 99 passed.

**Item 2 — done.** New `utils/usage_tracker.py`: `DailyUsageTracker`
(appends one JSON line per call to `state/usage/{date}.jsonl`, sums it for
`today_total()`/`limit_reached()`, limit from `DAILY_COST_LIMIT_USD` env var,
default $20/day) and `UsageTrackingClient` (wraps a real client; checks the
limit *before* every `create`/`stream` call and raises `DailyLimitReached`
without ever reaching the API once hit; records `response.usage` — via
`get_final_message()` for the streamed case — after a successful call).
Wired into `OrchestratorAgent.__init__` as the one place `self.client` is
built, so every one of the ~15 agent methods gets usage logging + the limit
for free. `run()`/`run_stream()` each catch `DailyLimitReached` specifically
(before the generic handler) and return/yield `DAILY_LIMIT_MESSAGE` — in
`run_stream()` as a normal `meta`/`token`/`done` sequence, not an `error`
event, so the frontend needs no special case. `state/usage/` already covered
by the existing root `.gitignore` `state/` rule. 17 new tests (13
`utils/usage_tracker.py` standalone + 4 for the resting-message wiring), 0
real API calls. `pytest`: 116 passed.

**Item 3 — done.** Backend was already mostly covered (`/tutor` and
`/tutor/stream` both already caught exceptions gracefully); item 1's
try/except/finally on `run_stream()` closed the remaining gap (a mid-stream
exception now still logs + saves before yielding the friendly error).
Frontend (`ClassroomLM.tsx`): `Message` gained `failed`/`retryText`; both the
SSE `error` event and the fetch/network catch-block now set
`failed: true` + `retryText: text` and show a friendly message (backend's
own safe SSE error text, or a generic connection message for network
failures — the raw `err.message` that used to be shown directly is now only
`console.error`'d) instead of appending `[error: ...]` to the streamed
content. Neither path appends to `conversationHistoryRef`/persisted
history — a failure no longer poisons future turns' context. `MessageView`
shows a Retry button (reusing `.clm-copy-btn` styling + the established
`#b4341f` error color from `.clm-upload-error`) instead of Copy on a failed
message; clicking it resends the original text as a new turn via the
existing `sendMessage(overrideText)` path. `npx tsc -b`: clean. `npm run
lint`: 18 errors, same as baseline, 0 in `ClassroomLM.tsx`. Backend
`pytest`: 116 passed (no backend changes this item).

**Item 4 — done.** New `OrchestratorAgent._load_student_model_if_empty()`:
if the incoming `student_model` is empty, loads
`self.memory.get_student_model(student_id)` (already defensive — returns
`{}` on any read failure); a non-empty incoming model is trusted as-is and
never overwritten mid-conversation. Called from both `run()` and
`run_stream()` right after `student_id` is resolved. No frontend change
needed — `studentModel` already starts at `{}` on mount and student_id/
session_id already flow through from item 1, so a fresh page load already
triggers the load path automatically. 6 new tests. `pytest`: 122 passed.

**Item 5 — done, and the gap was different than expected.** Confirmed
`docs/misconceptions.md` was genuinely unused (0 references anywhere in
`backend/`). But detection-and-targeting was *already* fully wired —
`STUDENT_MODELER_PROMPT` outputs `observed_misconceptions`,
`PEDAGOGICAL_PLANNER_PROMPT` already had a rule to `ASK` when one's observed
and outputs `target_misconception`, and `conversationalist()` already
receives the whole `plan` dict. The doc's real value: its 22 entries are all
**statics** (FBD construction, equilibrium equations, reference point
choice, distributed loads) — a category the modeler's hand-written inline
list (19 dynamics-focused ids) had zero coverage of, even though statics is
explicitly in the MVP scope per `CLAUDE.md`. New `agents/misconceptions.py`
parses the doc once at import (regex on the `**ID** / - **Description:** /
- **What it looks like:** / - **How to address:**` structure, grouped by
`## Category` heading) into `MISCONCEPTIONS`; `known_misconceptions_block()`
is appended to `STUDENT_MODELER_PROMPT` (additive — the original 19-item
list is untouched) and `remediation_for(id)` gives the conversationalist
exactly one "how to address" sentence, added to its context bundle as
`misconception_guidance` only when `plan.target_misconception` matches a
known id (omitted entirely otherwise — no per-turn bloat on a normal turn).
Both parser and prompt/conversationalist wiring are covered without any real
API calls (a fake client captures the conversationalist's outgoing context
bundle to confirm the guidance key). Parser is defensive — a
missing/malformed doc file yields `{}` and both functions degrade to their
pre-this-item behavior rather than breaking detection. 14 new tests.
`pytest`: 136 passed.

**Item 6 — done.** New `feedback_store.py` (backend root, same pattern as
`document_store.py`): `record_feedback(session_id, turn_number, student_id,
rating)` appends one JSON line to `state/feedback.jsonl`
(`FeedbackError` — a real 400, not swallowed — for a rating outside
{"up","down"}); `read_feedback()` for later analysis. New `POST /feedback`
endpoint + `FeedbackRequest` model in `main.py`. Frontend: `Message` gained
`turnNumber`, stamped when the AI placeholder message is created as
`historySnapshot.filter(m => m.role === 'user').length` — this is exactly
what `OrchestratorAgent` computes as `turn_number` server-side, since
`historySnapshot` **is** the `conversation_history` sent for that turn.
Thumbs buttons live in a new `.clm-msg-actions` wrapper next to Copy/Retry
(moved `margin-left: auto` from `.clm-copy-btn` onto the wrapper so multiple
buttons don't each fight for the flex space); optimistic local highlight,
POSTs `{session_id: activeId, turn_number, student_id, rating}` to
`/feedback`, tap-again-to-undo visually (still sends the new rating server-
side — feedback_store is append-only, so a change of mind is a new entry,
not an edit). 7 new backend tests (5 for `feedback_store.py` + 2 for the
endpoint, `main.feedback_endpoint()` called directly). `npx tsc -b`: clean. `npm run lint`: 18 errors, same baseline, 0 in `ClassroomLM.tsx`.
`pytest`: 143 passed.

**Item 7 — done.** Fully deterministic, as flagged in the plan as the way to
de-risk this: `hint_level` (1-4) is a new explicit `TutorRequest`/
`run()`/`run_stream()` parameter, not a message the Router/Planner has to
interpret. When set, `_run_turn()`/`_run_stream_events()` skip the Router
call entirely (route is forced to `"PROBLEM"` — no misclassification risk,
one fewer API call) and skip the Pedagogical Planner call, building `plan`
in Python instead via new `_hint_ladder_plan()`: levels 1-3 use a new
`_HINT_LADDER` dict (a deliberately simple, linear 3-rung ladder per family
— kinetics/kinematics/energy_momentum — distinct from
`PEDAGOGICAL_PLANNER_PROMPT`'s own richer multi-stage ladder used for the
LLM's organic HINT decisions elsewhere; collapsing that multi-stage ladder
onto a strict 1/2/3 button felt like fighting the prompt's own structure, so
the button gets its own compact copy instead — noted as a small, deliberate
duplication). Level 4 is **not** a HINT at all — `_hint_ladder_plan(4, ...)`
returns `decision: "SOLVE"` with a new `permission_source:
"hint_ladder_exhausted"` (added to `PEDAGOGICAL_PLANNER_PROMPT`'s documented
enum for consistency), which flows through the exact same solve → validate →
visualize path (and the same VERIFICATION HONESTY conversationalist rule) an
organically-requested solve already uses — this is what replaces the old
behavior of the tutor being inconsistent about ever revealing a value after
several stuck turns; the student now has explicit, guaranteed control via 4
taps instead of relying on the Planner's own judgment call.

Frontend: `hintLevel` tracked per conversation (sessionStorage, same tier as
conversation history — there's no separate "problem id" surfaced to the
frontend, so one conversation is treated as one problem-in-progress, the
same scoping choice item 6 already made for turn tracking) via
`loadHintLevel`/`saveHintLevel`, reloaded on conversation switch. New Hint
button in the composer next to Send; each tap increments the level (capped
at 4), sends one of four friendly literal messages
(`HINT_LEVEL_PROMPTS`) plus the numeric `hint_level` through the now-extended
`sendMessage(overrideText?, hintLevel?)`. Deliberately does **not**
auto-reset on an intervening regular message (a "let me think" aside
shouldn't erase hint progress) — only a genuinely new conversation resets it,
since that's a fresh sessionStorage key. 12 new backend tests (pure-function
ladder lookup + `_hint_ladder_plan` shape + end-to-end via both `run()` and
`run_stream()` with a fake client asserting the Router/Planner prompts were
never invoked). `npx tsc -b` + `npm run build`: clean. `npm run lint`: 18
errors, same baseline, 0 in `ClassroomLM.tsx`. `pytest`: 155 passed.

**Item 8 — done.** New `_draw_needs_clarification(route_decision,
conversation_history)`: true exactly when the Router already marked the
message `"referential"` (the same `problem_scope` field `_draw_history`
already reads — no new Router call, no new cost) and `conversation_history`
is empty. Deliberately scoped to that one cheap, unambiguous case, not the
fuzzier "history exists but never actually contained a real problem" —
noted in the plan as a real limitation, not silently over-claimed. Wired
into both DRAW branches (`run()`/`_run_turn()` and `_run_stream_events()`)
right before `input_parser` would otherwise run: on a hit, both return/yield
a `CLARIFY` decision with a fixed, friendly `DRAW_NEEDS_CLARIFICATION_MESSAGE`
— `input_parser` and `visualizer` are never called, so nothing gets
invented. An unparseable/missing `problem_scope` defaults to NOT blocking
(same permissive-default philosophy `_draw_history` already uses) — a
broken Router response should never make the tutor needlessly interrogate
the student. 9 new tests (4 pure-function + 5 end-to-end via `run()` and
`run_stream()`, confirming `input_parser`/`visualizer` are never invoked on
the clarification path and the turn is still logged). No frontend changes —
the message flows through the existing chat/streaming display untouched.
`pytest`: 164 passed.

**Item 9 — done.** The checker core (`agents/work_checker.py`) and its
injection tests were already on disk from the previous pass. Finishing it
turned up three real problems in that core, all fixed:
- **Denial of service.** `parse_expr` evaluates as it parses, so `m = 9^9^9`
  (a ~370-million-digit integer) or `exp(exp(exp(99)))` hung a worker
  indefinitely. Parsing now uses `evaluate=False`, and
  `_check_expression_shape` inspects the tree before anything is computed.
  It rejects towers (a power or exp/sinh/cosh inside an exponent or exp
  argument, except `x^-1`, which is how division is represented, so
  `m^(1/2)` still works) and numeric exponents above 1000. An infinite
  result is `invalid`, not `incorrect`. 9 resource-attack strings are
  asserted rejected, and each returns in well under a second with `1e300`
  substituted.
- **Degrees.** Trig was radians-only, so `N = m*g*cos(30)` (the checker's
  own example in its error message) was marked wrong. A line that fails in
  radians is now re-checked as a degree-mode calculator would read it
  (degree givens back in degrees, `sin/cos/tan` take degrees, inverse trig
  returns degrees). It passes if either reading matches.
- **Answer leak.** An incorrect line reported `left side = <value>`, and
  when that side was `N`, the value was the solver's answer. The solver's
  answers are now `hidden_symbols`: a side that uses one never has its
  value shown (`lhs_value`/`rhs_value` None, not in `detail`). The
  student's own side is still shown. Guess-and-check (`N = 85` → correct)
  is inherent to any checker and not addressed.

`build_known_values` now returns a `CheckContext` (known values, allowed /
angle / hidden symbols). It always knows `g` (the problem's gravity,
default 9.81), and it drops any symbol name from `parsed_input` that isn't
a short plain identifier or would shadow a parser helper (`Integer`,
`Symbol`, ...) or math function. Browser-supplied `parsed_input` is
untrusted. Max 30 lines per check.

**Where the reference answers come from — a deviation to flag.** The
solver only runs on SOLVE turns. The turns where a student shows work are
usually HINT/ASK, so there'd be nothing to check unknowns against. Sending
the solution to the browser on those turns would put the answer in
devtools. Instead, new `agents/solution_cache.py` (in-process, bounded
LRU, keyed by a hash of the canonical `parsed_input` JSON) holds solutions
server-side:
- Every SOLVE turn that passes validation fills it (in both `run()` and
  `run_stream()`), at no extra cost.
- `POST /check-work {lines, parsed_input}` first checks with givens only,
  with no LLM call. Only if a line uses an unknown does it call
  `OrchestratorAgent.solution_for_work_check()`. That reuses the cache, or
  else spends **one solver + one validator call once per problem**. A
  solution that fails validation is not used (those lines stay
  "can't check"), since a wrong reference would mark correct work wrong.
- These calls go through `UsageTrackingClient`, so the daily limit applies
  and hitting it returns a 429 with the resting message. A solver crash
  degrades to "can't check", not an error.
- The cache is process-local: a restart costs one re-solve per problem, and
  with multiple uvicorn workers each worker would keep its own cache.

Frontend: the PROBLEM turn's `meta` already carried `parsed_input`. It is
now stored per conversation (sessionStorage `classroomlm:problem:{id}`, the
same tier as hint level). A "Check work" button appears next to Hint once
a problem exists. It opens a panel above the composer: a monospace
textarea, one equation per line, with Cmd/Ctrl+Enter or Check to submit.
Each row shows ✓ / ✗ / ? (can't check yet) / ! (couldn't read). The first
wrong line is highlighted with "First mistake: …". Editing the text clears
stale results. Kept to one panel with no inline diffing, as the plan
allowed. `npx tsc -b` and `npm run build`: clean. `npm run lint`: 18
errors, same as baseline. The 3 in `ClassroomLM.tsx` are the pre-existing
`any`s, also present at HEAD (the earlier "0 in ClassroomLM.tsx" notes
meant 0 new). **Not checked in a real browser this session.**

Tests: +34 in `test_work_checker.py` (resource attacks, degree mode,
hidden answers, symbol sanitizing) and a new `test_check_work_endpoint.py`
(15: endpoint with a fake agent, cache behavior, a streamed SOLVE turn
filling the cache only when validated). `pytest`: 285 passed.

**Item 10 — done (built, not run live).** `evals/` already existed (30
statics problems + ground truth in `evals/problems/`,
`evals/ground_truth/`). The plan was wrong that it didn't. Those files
aren't wired into this harness. The new case file is
`evals/pilot_cases.py`, not `problems.py`, so it doesn't collide with the
`problems/` directory. It has 8 cases: crate on incline, beam reactions,
pendulum, ladder kinematics, pushed box (student checks a correct answer),
"same thing but 20 kg" follow-up (mass cancels, so `a` must be unchanged),
"draw that" with no context, and a Spanish problem. Each case has an
expected route, a list of acceptable decisions, and reference answers
computed in Python, not typed in.

`evals/run.py` runs every case through `run_stream()`, the same path as
`/tutor/stream`, and grades the event stream:
- route and decision
- no error event, non-empty reply
- on SOLVE, the solver's final answer within 2% (matched by symbol, or by
  value if a live solver names it differently; magnitudes only, so sign
  conventions don't fail it)
- on non-SOLVE turns, **no leak**: the answer must not appear in the reply,
  unless the student typed that number themselves
- optional phrase checks
- a Spanish stopword heuristic
- in mocked mode, which agents must not have run

Usage:
- `python -m evals.run`: mocked (default). Canned per-case outputs, a null
  memory so nothing lands in `backend/state/`, zero API calls.
  **8/8 pass.** This tests pipeline wiring and the grader, not model
  quality.
- `--mode live`: always prints the estimate first and **exits 2 without
  `--yes`**. With `--yes`, it journals to gitignored
  `evals/results/<timestamp>/` instead of pilot state.

Estimated cost of one live run (using `utils/cost_tracker` averages):
**$0.81**. That's 5 × PROBLEM_SOLVE at $0.140, 2 × PROBLEM_HINT at $0.055,
and 1 router-only clarify at $0.001. The tracker leaves out validator
retries and extended thinking, so a real run can cost more. Live mode was
not invoked.

`CLAUDE.md`'s old `--suite projectile_v1` command is replaced with the
real one. New `backend/tests/test_eval_harness.py` (16 tests) runs the
mocked suite and checks that live mode never starts without `--yes`. It
also feeds the grader bad turns (wrong answer, leaked answer, wrong route,
English reply to a Spanish problem, "draw that" guessing, a broken mock
solver) to prove it actually fails them.

`pytest tests/ -q`: **301 passed**, 0 real API calls.


**Browser-test fixes (round 1).**
1. *Check work rejected N and f.* Three causes stacked. (a) The only
   names allowed were the givens, the requested unknowns, and the solver's
   final answers, so for "find a" the normal force and friction were
   rejected as unrecognized. (b) The endpoint only asked the solver when a
   line was "can't check", never when a line was rejected, so the solver
   wasn't consulted even after the full solution was shown. (c) The solver
   only reported final answers, not N or friction.
   - Names are now checked by shape (`_is_physics_symbol`: a letter plus up
     to 2 letters/digits, or a Greek letter name, optionally with a short
     subscript; no Python keywords or parser names). Every accepted name
     becomes a plain `sympy.Symbol`. All injection and resource tests still
     pass.
   - Symbol families map the student's names to the solver's (f ↔ f_k,
     F_f; N ↔ F_N; W ↔ F_g; mu ↔ mu_k; T; theta), and W = m*g is derived
     when not given.
   - A line like `f = 0.25*N` whose only unknown is a bare symbol is
     "defined". Its value carries to later lines, but a known value always
     wins over a student's definition.
   - The solver prompt now asks for `intermediate_values`, which are hidden
     like final answers.
   - Result for `N = m*g*cos(30)` / `f = 0.25*N` / `N = m*g`: ✓ ✓ ✗.
2. The close button rendered a literal `×` (JSX text doesn't process
   escapes), which also overflowed the button. It's now `{'×'}`,
   absolutely positioned in the panel's top-right corner.
3. The panel's height is capped at `min(45vh, 420px)` and scrolls; the
   message list has `min-height: 180px`; the composer area no longer shrinks.
4. Hint level 3 now runs the solver + validator (or reuses the cache) and
   passes one intermediate value (e.g. N = 84.96 N, never a final answer) as
   `payload.worked_step`. A new reply-prompt rule has it carry that step out
   with numbers. The solution itself never reaches the reply prompt or the
   browser. If validation fails, it falls back to the old text hint.
   **Cost:** a level-3 tap now costs one solver + one validator call unless
   that problem was already solved.
5. `fix_label_collisions` does run on this path (inside `visualizer()`). It
   detected both labels but found no clear spot, and logged that only at
   DEBUG. θ was blocked because arcs were treated as a box padded by the
   radius around both endpoints, covering the whole corner where θ goes.
   W was blocked because candidate moves were only up/down/left/right.
   - Curves and arcs are now sampled into real segments.
   - Candidate moves are nearest-first, include the touched edge's normal
     and 12 directions, and keep the 40px cap.
   - `translate()` on groups and inherited/style `font-size` are now read.
     Before, a label in a translated group was shoved 88px based on the
     wrong coordinates.
   - Anything under rotate/scale is left alone, and "left in place" is now
     a WARNING.
   - The visualizer prompt got a rule against transforms on text and
     labels inside filled shapes.
