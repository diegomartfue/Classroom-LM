# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Classroom-LM is an AI-powered classroom assistant. Students and professors interact via a React frontend; a FastAPI backend orchestrates AI tutoring through Claude, math verification via SymPy, and uploaded course documents (`document_store.py`) that students can attach to a question.

## Dev Commands

### Backend
```bash
cd backend
source venv/bin/activate       # activate virtualenv
pip install -r requirements.txt
uvicorn main:app --reload      # starts on http://localhost:8000
```

Requires `ANTHROPIC_API_KEY` in a `.env` file inside `backend/`.

### Frontend
```bash
cd frontend
npm install
npm run dev     # starts on http://localhost:5173
npm run build
npm run lint
```

## Architecture

### Backend (`backend/`)

- **`main.py`** — FastAPI app. Main routes:
  - `POST /tutor/stream` — the live chat endpoint (the agent orchestrator, streamed); `POST /tutor` is the non-streaming version
  - `/documents` (plus `/documents/{doc_id}`, `/documents/summarize`, `/documents/quiz`) — course-file uploads via `document_store.py`
  - `POST /chat` — legacy tutoring endpoint: runs SymPy first, injects verified result into prompt, then calls Claude
  - `POST /interpret` — uploads an image/PDF/DOCX, uses Claude vision to extract equations/diagrams
  - Also `/feedback`, `/check-work`, `/participant/verify`, `/health`, `/cost-estimate`

- **`claude_client.py`** — thin wrapper around `anthropic.Anthropic`. Uses `claude-sonnet-4-6` for chat (4096 tokens), `claude-sonnet-4-5` for file interpretation. Strips non-ASCII before sending. The system prompt enforces plain-text math (no LaTeX) and defers to SymPy verified answers.

- **`sympy_solver.py`** — keyword-based math detector (solve/derivative/integral/simplify). When triggered, extracts the expression via regex and returns a `{type, input, solution, verified}` dict that gets injected into the Claude prompt. SymPy result always wins over Claude's own answer.

### Frontend (`frontend/src/`)

- **App** — no router. `App.tsx` mounts `components/ClassroomLM.tsx` (the whole chat UI: sidebar, conversations, uploads, hints, show-your-work) plus the toast `Toaster`.

- **Sign-in** — `components/ParticipantCodeScreen.tsx` asks for the pilot participant (or professor) code; every API call sends it in the `X-Participant-Code` header (`lib/pilot.ts`).

- **UI** — shadcn/ui components (Radix primitives + Tailwind) in `components/ui/`. Markdown and KaTeX math are rendered with `react-markdown`, `remark-math` and `rehype-katex`.

# Dynamics Tutor Project

## Scope (MVP)
2D rigid body statics and dynamics (particles and rigid bodies). Specifically:
- Single rigid body in planar equilibrium (statics: ΣF=0, ΣM=0)
- 2D dynamics of particles and rigid bodies (Newton's second law: ΣF=ma, ΣM=Iα, general plane motion)
- Standard supports: pin, roller, fixed, cable, contact
- Applied loads: point forces, point moments, distributed loads (uniform and linear)
- Unknowns: reaction forces, reaction moments, accelerations, geometric parameters
- OUT OF SCOPE for MVP: trusses, frames, machines, friction problems, 3D problems, deformable bodies.
- Input: structured text description only for v1. Image input in v2.

## Architecture
Eleven agents: Router, Input Parser, Direct Tutor, Creator, Student Modeler, Pedagogical Planner, Solver, Validator, Visualizer, Schematic Layout, Conversationalist
See docs/architecture.md for details.

## Repo layout
- /backend/agents/ - orchestrator, inline agent prompts, and the deterministic FBD/schematic renderer
- /backend/tools/ - SymPy/pint helpers (equilibrium builder/verifier, linear solver, reaction/unit checkers) — not yet wired into the pipeline
- /evals/ - problem sets (problems/) and ground truth (ground_truth/)
- /docs/ - architecture.md and misconceptions.md

## Running evals
`python -m evals.run` (mocked, zero API calls). `--mode live` prints a cost estimate and needs `--yes` to make real calls. Cases live in `evals/pilot_cases.py`.

## Conventions
- All prompts live in /agents/{name}/prompt.md (version controlled)
- All agent calls log to /traces/{session_id}/{turn}.json
- Temperature and model are set in /agents/{name}/config.yaml

## Known misconceptions to track
See /docs/misconceptions.md
