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
| `DRAW` | Sketch-only | `draw_only` / `_draw_created_problem` → deterministic renderer |
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

## Notes on current gaps

- The `backend/tools/` verification helpers are not yet called by the pipeline;
  Solver/Validator verification is currently prompt-driven.
- `/traces` and `/state` (per-CLAUDE.md conventions) are not yet implemented; the
  student model is passed through the request/response rather than persisted.
- The eval sets under `/evals/problems/` and `/evals/ground_truth/` (30 problems
  each) do not yet have a `run.py` grading harness.
