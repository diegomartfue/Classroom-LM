# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Classroom-LM is an AI-powered classroom assistant. Students and professors interact via a React frontend; a FastAPI backend orchestrates AI tutoring through Claude, math verification via SymPy, and RAG over uploaded course materials stored in ChromaDB.

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

- **`main.py`** — FastAPI app. Four routes:
  - `POST /chat` — main tutoring endpoint: runs SymPy first, injects verified result into prompt, then calls Claude
  - `POST /interpret` — uploads an image/PDF/DOCX, uses Claude vision to extract equations/diagrams
  - `POST /upload` — ingests a PDF into ChromaDB via `rag_pipeline.ingest_document`
  - `POST /query` — RAG query over ingested course materials

- **`claude_client.py`** — thin wrapper around `anthropic.Anthropic`. Uses `claude-sonnet-4-6` for chat (4096 tokens), `claude-sonnet-4-5` for file interpretation. Strips non-ASCII before sending. The system prompt enforces plain-text math (no LaTeX) and defers to SymPy verified answers.

- **`sympy_solver.py`** — keyword-based math detector (solve/derivative/integral/simplify). When triggered, extracts the expression via regex and returns a `{type, input, solution, verified}` dict that gets injected into the Claude prompt. SymPy result always wins over Claude's own answer.

- **`rag_pipeline.py`** — PDF ingestion: splits text into 500-char chunks (50 overlap), embeds with ChromaDB's default embedding function, persists to `chroma_db/`. Query retrieves top-3 chunks and passes them as context to `claude_client.chat`.

### Frontend (`frontend/src/`)

- **Routing** — no React Router. `App.tsx` holds a `currentView` string; `MainLayout` maps it to components. Pass `onViewChange` down to navigate between views.

- **Auth** — `AuthContext.tsx` provides `isProfessor`, `isStudent`, `isAuthenticated`. Login is handled by `sections/auth/LoginScreen`. Role determines which views are available in the sidebar.

- **Contexts** — `AuthProvider` + `AppProvider` wrap the whole app. Import from `@/contexts` (barrel export in `contexts/index.ts`).

- **Sections** — organized by role:
  - `sections/professor/` — `ProfessorDashboard`, `AIContentGenerator`, `AIQuizGenerator`, `UploadMaterials`
  - `sections/student/` — `StudentDashboard`, `AITutor`
  - `sections/auth/` — `LoginScreen`
  - `sections/shared/` — `Sidebar`

- **UI** — shadcn/ui components (Radix primitives + Tailwind). Components live in `components/ui/`. Markdown responses are rendered with `react-markdown`.

### Adding a New View
1. Create the component in the appropriate `sections/` subdirectory.
2. Import it in `App.tsx` and add it to the `views` object inside `MainLayout`.
3. Add the corresponding nav item in `sections/shared/Sidebar.tsx`.

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
Twelve agents: Router, Input Parser, Direct Tutor, Creator, Student Modeler, Pedagogical Planner, Solver, Validator, Visualizer, Schematic Layout, Diagram Renderer, Conversationalist
See docs/architecture.md for details.

## Repo layout
- /backend/agents/ - orchestrator, inline agent prompts, and the deterministic FBD/schematic renderer
- /backend/tools/ - SymPy/pint helpers (equilibrium builder/verifier, linear solver, reaction/unit checkers) — not yet wired into the pipeline
- /evals/ - problem sets (problems/) and ground truth (ground_truth/)
- /docs/ - architecture.md and misconceptions.md

## Running evals
`python -m evals.run --suite projectile_v1`

## Conventions
- All prompts live in /agents/{name}/prompt.md (version controlled)
- All agent calls log to /traces/{session_id}/{turn}.json
- Temperature and model are set in /agents/{name}/config.yaml

## Known misconceptions to track
See /docs/misconceptions.md
