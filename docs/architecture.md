# ClassroomLM — Architecture

## System Overview

ClassroomLM is an AI-powered classroom assistant for **2D rigid body statics and
dynamics** (particles and rigid bodies). A React/TypeScript frontend talks to a
FastAPI backend. The backend exposes a legacy single-shot `/chat` path and the
primary **`/tutor`** path, which drives a routed, multi-agent tutoring pipeline
implemented in `backend/agents/orchestrator.py`.

The design goal is *learning, not answer delivery*: a Pedagogical Planner decides
whether to hint, ask, wait, clarify, or fully solve, and a student-facing
Conversationalist phrases the result. Solutions that are produced are
independently checked by a Validator before any diagram is drawn.

```
Student → Frontend (ClassroomLM.tsx) → POST /tutor → OrchestratorAgent.run()
        → Router → [route-specific path] → Conversationalist → response (+ optional FBD image)
```

High-level component map:

- **`backend/main.py`** — FastAPI app and endpoints.
- **`backend/agents/orchestrator.py`** — the 12-agent orchestrator (`run`, `run_stream`).
- **`backend/agents/fbd_renderer.py`** — deterministic matplotlib renderer (`render_fbd`, `render_schematic`, `stack_images_vertical`).
- **`backend/tools/`** — SymPy/pint verification helpers (not yet wired into the pipeline; see below).
- **`backend/claude_client.py`, `sympy_solver.py`, `rag_pipeline.py`** — support the legacy `/chat`, `/query`, and `/upload` paths.
- **`frontend/src/components/ClassroomLM.tsx`** — the live chat UI.

## The 12-Agent Pipeline

Every `/tutor` turn begins with a single cheap **Router** call. The Router
classifies the student's latest message into exactly one route, and the route
determines which downstream agents run:

| Route | Path taken | Agents involved |
|-------|-----------|-----------------|
| `PROBLEM` | Full tutoring pipeline | Input Parser → Student Modeler → Pedagogical Planner → (Solver → Validator → Visualizer → renderer, only if the Planner decides `SOLVE`) → Conversationalist |
| `DRAW` | Sketch-only | Input Parser → Visualizer (draws SVG directly) → Conversationalist |
| `CREATE` | Problem generation | Creator |
| `CONCEPT` | Direct answer | Direct Tutor |
| `SMALLTALK` | Direct answer | Direct Tutor |
| `OUT_OF_SCOPE` | Direct answer | Direct Tutor |

This routing keeps cost and latency low: conceptual questions and small talk skip
the parser/solver/diagram machinery entirely, and the expensive Solve → Validate →
Visualize sequence only runs when the Planner explicitly decides to solve.

### Two pipeline paths

1. **Full PROBLEM path (the "7-agent" pipeline).** For genuine problems, the
   orchestrator runs Input Parser → Student Modeler → Pedagogical Planner, then —
   only when the Planner returns `decision == "SOLVE"` — Solver → Validator →
   Visualizer followed by the deterministic renderer, and finally the
   Conversationalist. If the Planner returns `HINT`/`ASK`/`WAIT`/`CLARIFY`, the
   solve/validate/visualize stage is skipped and the Conversationalist responds
   directly. This is the pedagogically-governed path.

2. **Direct Tutor shortcut.** For `CONCEPT`, `SMALLTALK`, and `OUT_OF_SCOPE`
   routes, a single Direct Tutor call produces the reply. The parser, student
   modeler, planner, solver, validator, visualizer, and Conversationalist are all
   bypassed, and the student model is returned unchanged.

### Agent reference

Models and temperatures are set inline in each method in `orchestrator.py`.
Input Parser and Router use Haiku for speed/cost; the three highest-judgment
agents (Pedagogical Planner, Visualizer, Creator) use Opus; the rest use Sonnet.

| Agent | Model | Temp | Input | Output |
|-------|-------|------|-------|--------|
| **Router** | claude-haiku-4-5-20251001 | 0 | Student message + history | JSON `{route}` — one of PROBLEM/DRAW/CREATE/CONCEPT/SMALLTALK/OUT_OF_SCOPE |
| **Input Parser** | claude-haiku-4-5-20251001 | 0 | Raw student text + history | Structured problem JSON (geometry, supports, applied loads, dynamics, unknowns, confidence) |
| **Direct Tutor** | claude-sonnet-4-6 | 0.5 | Message + route label | Natural-language reply for non-problem messages |
| **Creator** | claude-opus-4-7 | 0.4 | Message + history | JSON of generated practice problem(s) / variants |
| **Student Modeler** | claude-sonnet-4-6 | 0.2 | Parsed problem + current model + history | Updated student model JSON (concept mastery, misconceptions, state) |
| **Pedagogical Planner** | claude-opus-4-7 | 0.1 | Parsed problem + student model + history + raw message | Decision JSON `{decision, rationale, payload, target_misconception}` where decision ∈ SOLVE/HINT/ASK/WAIT/CLARIFY |
| **Solver** | claude-sonnet-4-6 | 0 | Parsed problem JSON | Full solution JSON (assumptions, coordinate system, FBD structure, equations, final answers) |
| **Validator** | claude-sonnet-4-6 | 0 | Parsed problem + solver solution | Verdict JSON (independent re-derivation, equilibrium checks, PASS/FAIL/UNCERTAIN) |
| **Visualizer** | claude-opus-4-7 | 0 | Parsed problem + solution | Structured FBD spec JSON (body, supports, reactions, applied loads) |
| **Schematic Layout** | claude-sonnet-4-6 | 0.2 | Parsed problem + solution | JSON drawing primitives for multi-body schematics (FBD-renderer fallback) |
| **Diagram Renderer** | claude-sonnet-4-6 | 0 | Visualizer output + solution | Executable matplotlib code → base64 PNG (used on the streaming path) |
| **Conversationalist** | claude-sonnet-4-6 | 0.5 | Full context bundle (message, parsed input, student model, plan, solution, validation, visualization) | Student-facing prose reply |

### Diagram rendering

On the `SOLVE` branch, the orchestrator first tries the **deterministic**
renderer: `render_fbd(visualizer_spec)`. If that returns empty (e.g., a
multi-body mechanism the single-body FBD renderer can't draw), it falls back to
`schematic_layout` → `render_schematic(layout)`. The LLM-based **Diagram
Renderer** agent (which generates and `exec`s matplotlib code) is retained for
the streaming path (`run_stream`) but is not on the primary `run()` SOLVE branch.

## Tools (`backend/tools/`) — intended role, not yet wired in

These modules are complete and independently tested (each has a `__main__`
demo), but **no agent or endpoint imports them today**. They are intended to
replace the current prompt-only "use SymPy" instructions with real, tool-backed
verification in the Solver/Validator stage:

- **`equilibrium_builder.py`** — builds the ΣFx / ΣFy / ΣM equilibrium equations
  from a list of forces (and pure couples) using SymPy, about a chosen reference
  point.
- **`equilibrium_verifier.py`** — the "killer check": given all forces plus
  computed reactions, confirms ΣFx = ΣFy = 0 and ΣM = 0 about **two independent**
  reference points, within tolerance.
- **`linear_solver.py`** — solves a (possibly non-square) linear system with
  SymPy `linsolve`, gracefully reporting under-/over-determined and inconsistent
  cases.
- **`reaction_checker.py`** — sanity checks: reaction magnitudes within a few
  orders of magnitude of applied loads, and support-type sign constraints
  (cable = tension-only, contact = compression-only).
- **`unit_checker.py`** — pint-based dimensional consistency check across
  quantity groups (forces, moments, etc.).

Wiring these into the Validator (independent numerical re-solve + unit check)
is the natural next step to make verification deterministic rather than
prompt-dependent.

## FastAPI Endpoints (`backend/main.py`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Liveness string. |
| GET | `/health` | Reports whether `ANTHROPIC_API_KEY` is configured. |
| POST | `/chat` | Legacy path: `sympy_solver.extract_and_solve` runs first, its verified result is injected into the prompt, then `claude_client.chat` replies. |
| POST | `/interpret` | Upload an image / PDF / DOCX; Claude vision/text extraction returns equations and diagrams as plain text. |
| POST | `/upload` | Ingest a PDF into ChromaDB via `rag_pipeline.ingest_document`. |
| POST | `/query` | RAG query over ingested course materials (top-3 chunks → Claude). |
| POST | `/tutor` | Primary endpoint: runs `OrchestratorAgent.run()` and returns the reply, the routing decision, the updated student model, an optional base64 FBD image, and full pipeline metadata. |

## Frontend Architecture (`frontend/src/`)

- **Entry / routing.** `App.tsx` mounts `ClassroomLM` directly. (The role-based
  `MainLayout` + `sections/` structure and `AuthContext` roles exist in the
  codebase but are not currently mounted by `App.tsx`.)
- **Live component.** `components/ClassroomLM.tsx` is the UTEP-themed chat UI. It
  posts to `${API_BASE}/tutor` (`API_BASE` defaults to `http://localhost:8000`)
  and uploads course files to `/upload`. Markdown replies are rendered with
  `react-markdown`; returned FBD images are shown inline.
- **Legacy context.** `contexts/AppContext.tsx` still contains
  `simulateAITutorResponse`, which targets `/chat`; the live UI does not use it.
- **UI kit.** shadcn/ui components (Radix + Tailwind) live in `components/ui/`.

## DRAW pipeline: history gating and label-collision fixing

Two small deterministic mechanisms sit around the Visualizer to fix problems
found in earlier manual testing: a DRAW request drawing the *previous* turn's
problem instead of the one just described, and labels rendering on top of
each other or on top of arrows.

### 1. History gating via the Router's `problem_scope` field

`input_parser()` prepends the *entire* conversation history to its prompt.
That's correct for a referential request ("draw that one again") but wrong
for a self-contained one: a fresh "a 2 kg ball on a 1.5 m string" describing
its own complete setup would otherwise get parsed alongside an unrelated
block-on-an-incline problem from three turns earlier, and the model can fuse
the two into the wrong diagram.

The Router (`ROUTER_PROMPT`, `router()` in `orchestrator.py`) already reads
the message as an LLM call and classifies routing intent; the fix adds one
more field to its existing JSON output — `problem_scope`: `"self_contained"`
or `"referential"` — rather than running a second, independent classifier.
`_draw_history(route_decision, conversation_history)` reads that field: `[]`
when `self_contained`, the real history otherwise, including when the field
is missing/unrecognized (never strip history on an incomplete or
unparseable router response). Both live DRAW callsites (`run()` and
`run_stream()`) use it.

This replaced an earlier standalone regex (`_is_self_contained_problem`,
deleted) that checked the message alone for a quantity + a body noun. The
regex could not tell "a 10 kg block instead" (referential — it still depends
on the previous turn for the incline angle, friction, etc.) from a genuinely
new problem using similar words; the Router sees the whole conversation and
can.

**Known limits:**
- This is one more judgment call added to an existing LLM classification
  call, not a deterministic rule — a router misclassification (rare, but
  possible, especially on ambiguously-worded messages) now determines
  history inclusion the way it already determines route. The `run_stream()`
  streaming path also doesn't currently surface `route_decision` (and so
  `problem_scope`) in its `"meta"` event, so a caller/tester who wants to
  observe what the router decided has to instrument `router()` directly
  rather than read it off the stream.
- The three-turn gating check this change was meant to be verified against
  (a self-contained problem, then a self-contained follow-up problem, then a
  referential tweak on it) has not yet been run against the live API — see
  "Outstanding verification" below.

### 2. Deterministic label-collision fixing (`backend/agents/svg_layout.py`)

`VISUALIZER_PROMPT`'s LAYOUT PROCESS asks Opus to plan label placement so
nothing overlaps, but the model is producing a *text* SVG spec with no way to
actually measure what it drew — it cannot self-check bounding boxes, so
collisions still happen (a support's point label overlapping its own
reaction-force label was one observed case). `fix_label_collisions(svg)` is
the deterministic backstop, wired into `visualizer()` right before it
returns on the success path (wrapped in try/except — this pass must never
break a diagram it was only supposed to improve):

1. Parse with `xml.etree.ElementTree` (stdlib) — not `lxml`. Both are
   importable in the dev venv, but `lxml` is not declared in
   `backend/requirements.txt`; it's a transitive dependency of another
   package, not something this codebase can rely on staying installed.
2. Estimate every `<text>` element's bounding box from a fixed heuristic —
   `0.55 * font_size * len(text)` wide, `1.2 * font_size` tall, adjusted for
   `text-anchor` and `dominant-baseline` — rather than measuring real glyphs
   with PIL. Pillow is also only present transitively (via matplotlib), not
   a declared backend dependency, so it isn't used here either.
3. Estimate bounding boxes for every `<line>`, `<path>`, and `<polygon>`
   (not `<rect>`/`<circle>` — a body outline or background rect would
   otherwise collide with almost every nearby label). Path curves/arcs are
   over-approximated from their control/end points, which can only widen an
   estimated bbox, never hide a real overlap.
4. For each text that overlaps another text or crosses geometry (4px
   padding), try candidate offsets in order: 14px further from the diagram
   center along the label's existing direction, then the four cardinal
   directions at 14px, then the same four at 28px. The first candidate with
   no collision *and* that stays inside the 30px viewBox margin wins. A
   label that finds nothing safe within 40px total displacement is left
   exactly where it was (logged at debug level) — never an exception.
5. Only `<text>` elements move; geometry, `<defs>`, markers, and the
   background are never touched. If nothing needed to move, the original
   SVG string is returned byte-for-byte unchanged rather than round-tripped
   through the XML serializer.

**Known limits:**
- **Single greedy pass, document order.** Each label is evaluated once,
  against the *current* state of everything else (including labels already
  moved earlier in the same pass). This resolves most pairwise collisions,
  but a label can be logged as "no clear spot" and left in place even though
  a *later* label's move would have cleared the collision for it too — the
  final result is still correct in that case (the pair no longer overlaps),
  but the log line looks like a failure when it wasn't one.
- **Coarse text metrics.** The fixed-ratio width estimate is not real glyph
  measurement; it can over- or under-estimate a label's true width, which
  can occasionally cause an unnecessary nudge or, less often, miss a real
  but narrow overlap.
- **Approximate path bounding boxes.** Bezier/arc control-point
  over-approximation means a path's estimated bbox can be noticeably larger
  than its visual footprint, which can cause a label to be nudged away from
  a curve it wasn't actually touching.
- **Doesn't fix everything a bad diagram can have.** It only fixes label vs.
  label and label vs. geometry collisions. It does not fix wrong physics,
  wrong force placement, or (per the verification run below) a diagram that
  never got generated at all because the model's response was truncated.

### Outstanding verification (not yet completed)

Both mechanisms are unit- and pytest-tested against fakes (`pytest tests/ -q`
in `backend/`: 62 passed as of this writing), and a four-case manual run
against the live API confirmed `fix_label_collisions` visibly cleans up real
diagrams (5, 4, and 2 labels moved respectively on the crate/beam/pendulum
cases, with no visible remaining collisions). Two pieces of the requested
verification could not be completed in that session because the Anthropic
API account ran out of credits partway through:

- The 5-force, two-dimension ladder stress case failed outright — the
  Visualizer's response hit `max_tokens=16000` and was discarded
  (`stop_reason=max_tokens`), producing no diagram at all. Whether this is a
  one-off (a verbose generation) or a systematic problem for
  higher-force-count bodies needs re-running with credits restored, and
  possibly raising `max_tokens` or trimming `VISUALIZER_PROMPT` if it
  recurs.
- The three-turn gating check (self-contained crate → self-contained
  pendulum → referential "same thing but 3 m string") has not been run
  end-to-end against the live router, so `problem_scope`'s real-world
  accuracy on that specific sequence is unconfirmed beyond the unit tests.

## Notes on current gaps

- The `backend/tools/` verification helpers are not yet called by the pipeline;
  Solver/Validator verification is currently prompt-driven.
- `/traces` and `/state` (per-CLAUDE.md conventions) are not yet implemented; the
  student model is passed through the request/response rather than persisted.
- The eval sets under `/evals/problems/` and `/evals/ground_truth/` (30 problems
  each) do not yet have a `run.py` grading harness.
