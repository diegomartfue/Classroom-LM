"""
model_config.py — single source of truth for the Claude model IDs used
across the backend. Import these instead of hardcoding model strings.
"""

SONNET_MODEL = "claude-sonnet-5"
HAIKU_MODEL = "claude-haiku-4-5-20251001"
OPUS_MODEL = "claude-opus-5"

# Visualizer only. Opus 5.5 is cheaper per token than Opus 5 ($4/$20 vs
# $5/$25 per MTok) and, per Anthropic's own testing, tends to finish
# generation tasks using fewer output tokens at a given effort level —
# a good fit for a call that was previously flaky on token budget. Every
# other agent stays on OPUS_MODEL / SONNET_MODEL / HAIKU_MODEL.
VISUALIZER_MODEL = "claude-opus-5-5"
