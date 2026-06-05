"""Agent configuration (Phase 4A).

Centralises every tunable for the agent layer: model names, retry limits, tool
parameters, prompt paths. The eval swaps models by overriding ``AgentConfig`` rather
than touching node code. Model strings use the OpenRouter-prefixed form already in use
across the codebase (``anthropic/claude-3.5-haiku`` — see resolution/adjudicator.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Prompt templates live next to this module so they ship inside the Docker image
# (backend/app/ is COPYed wholesale) and are editable without a rebuild via volume mount.
_PROMPT_DIR = Path(__file__).parent / "prompts"

# The agent uses a single LLM family in two roles (CLAUDE.md locked decision). Routing is
# a cheap classification; synthesis is a constrained generation. Same model keeps the cost
# model simple and the voice consistent; the split exists so the eval can diverge them.
ROUTER_MODEL = "anthropic/claude-3.5-haiku"
SYNTHESIS_MODEL = "anthropic/claude-3.5-haiku"


@dataclass(frozen=True)
class AgentConfig:
    """Immutable agent settings. One instance is built per ``run_agent`` call.

    Defaults match the CLAUDE.md locked decisions. The eval constructs a variant with a
    different model to compare without editing node code.
    """

    router_model: str = ROUTER_MODEL
    synthesis_model: str = SYNTHESIS_MODEL

    # Routing is a classification: temperature 0 for determinism. Synthesis is prose, but
    # we still keep it low — grounded answers, not creative writing (mirrors extraction).
    router_temperature: float = 0.0
    synthesis_temperature: float = 0.1

    router_max_tokens: int = 400
    synthesis_max_tokens: int = 1200

    # Provenance verification loop: synthesise → verify → (retry with stricter prompt).
    # Two retries is the CLAUDE.md cap; beyond it we return a best-effort answer with a flag.
    max_synthesis_retries: int = 2

    # general_search fanout: the agent needs fewer hits than the search page (k=10) because
    # it only synthesises a short answer — eight gives the model enough context without bloat.
    search_k: int = 8

    # Prompt template paths.
    router_prompt_path: Path = _PROMPT_DIR / "router.txt"
    synthesis_prompt_path: Path = _PROMPT_DIR / "synthesis.txt"
    synthesis_strict_prompt_path: Path = _PROMPT_DIR / "synthesis_strict.txt"

    def load_prompt(self, path: Path) -> str:
        """Read a prompt template from disk. Kept tiny + uncached: prompts are small and
        reading them per request lets a volume-mounted edit take effect without a restart."""
        return path.read_text(encoding="utf-8")
