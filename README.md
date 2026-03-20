# Classroom-LM
AI-powered classroom assistant with student grouping, LLM tutoring, and math verification, freeform equations and engineering understanding.

## Architecture
```mermaid
flowchart TD
    A[Student / Professor] --> B[Frontend]
    B --> C[FastAPI Backend]
    C --> D[LLM Orchestrator - main.py]

    D --> E[RAG Pipeline]
    D --> F[Math Engine - SymPy]
    D --> G[Ollama]
    D --> H[Image Pipeline]

    E --> I[Vector Database]
    E --> J[Course Materials]
    E -.->|feeds course context| D

    F -.->|feeds verified answer| D

    G --> K[Qwen 2.5]
    G --> L[DeepSeek-R1]
    K --> M[Response to Student]
    L --> M

    H --> N[OCR / Vision Model]

    N -->|printed equation - extracts text| F
    F -.->|verified answer| G

    N -->|FBD - extracts force data| G
    G -->|sets up physics equations| F
    F -->|solves equations| O[Diagram Renderer - Matplotlib]
    O --> P[SVG / PNG output]
    P --> M