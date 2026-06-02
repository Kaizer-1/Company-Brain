"""Tier 2 LLM adjudication for ambiguous candidate pairs (Phase 3A).

When no exact Tier 1 rule decides a pair but the embeddings are close (or a rule fired but
similarity contradicted it), ``anthropic/claude-3.5-haiku`` decides. It is given both nodes'
stored properties and 2–3 short source-event snippets each, so it can reason about *meaning*
(a request API vs a delivery worker) rather than surface similarity alone. The model's output
is validated against ``LLMVerdict``; on any parse/validation failure the adjudicator falls
back to a safe **no-merge** (ADR 0014). Reuses the existing OpenRouter client.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError

from app.resolution.models import CandidatePair, LLMVerdict

if TYPE_CHECKING:
    from app.extraction.client import OpenRouterClient

log = structlog.get_logger(__name__)

ADJUDICATOR_MODEL = "anthropic/claude-3.5-haiku"
_JSON_RESPONSE_FORMAT = {"type": "json_object"}
_MAX_SNIPPETS = 3
_SNIPPET_CHARS = 280

_SYSTEM_PROMPT = (
    "You are an entity-resolution adjudicator for a company knowledge graph. You decide "
    "whether two graph nodes refer to the same real-world entity. Be conservative: a wrong "
    "merge corrupts downstream graph queries and is hard to undo, so only answer 'same' when "
    "the evidence genuinely supports it. Respond with JSON only."
)


_FALLBACK_VERDICT = LLMVerdict(
    same=False, confidence=0.0, reasoning="adjudication failed; defaulting to no-merge"
)


def _props_block(properties: dict[str, object]) -> str:
    """Render a node's properties as a compact, deterministic key=value list."""
    skip = {"source_event_ids", "created_at"}
    items = sorted((k, v) for k, v in properties.items() if k not in skip)
    if not items:
        return "(none)"
    return ", ".join(f"{k}={v!r}" for k, v in items)


def _snippets_block(snippets: list[str]) -> str:
    if not snippets:
        return "(no source events available)"
    trimmed = [s.strip().replace("\n", " ")[:_SNIPPET_CHARS] for s in snippets[:_MAX_SNIPPETS]]
    return "\n".join(f"  - {s}" for s in trimmed)


def build_adjudication_messages(
    pair: CandidatePair,
    *,
    snippets_a: list[str],
    snippets_b: list[str],
) -> list[dict[str, str]]:
    """Assemble the chat messages for one adjudication. Pure — easy to assert in tests."""
    node_type = pair.node_a.node_type.value
    user = (
        f"You are deciding whether two graph nodes refer to the same real-world {node_type}.\n\n"
        f"Node A:\n"
        f"- Properties: {_props_block(pair.node_a.properties)}\n"
        f"- Mentioned in these events:\n{_snippets_block(snippets_a)}\n\n"
        f"Node B:\n"
        f"- Properties: {_props_block(pair.node_b.properties)}\n"
        f"- Mentioned in these events:\n{_snippets_block(snippets_b)}\n\n"
        f"Embedding similarity: {pair.similarity:.3f}\n\n"
        f"Are A and B the same {node_type}? Respond with JSON:\n"
        '{\n'
        '  "same": true | false,\n'
        '  "confidence": 0.0-1.0,\n'
        '  "reasoning": "brief explanation grounded in evidence from the snippets"\n'
        '}'
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def parse_verdict(content: str) -> LLMVerdict:
    """Parse the model's JSON into an ``LLMVerdict``, or fall back to no-merge.

    Tolerates a ```json fenced block. Any JSON error or schema-validation error yields the
    safe no-merge default — never raises.
    """
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
        return LLMVerdict.model_validate(data)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        log.warning("adjudicator_parse_failure", error=str(exc)[:200], raw=content[:200])
        return _FALLBACK_VERDICT


class Adjudicator:
    """Tier 2 LLM adjudicator. One instance reused across many pairs."""

    def __init__(self, client: OpenRouterClient, *, model: str = ADJUDICATOR_MODEL) -> None:
        self._client = client
        self._model = model
        self.cost_usd = 0.0

    @property
    def model(self) -> str:
        return self._model

    async def adjudicate(
        self,
        pair: CandidatePair,
        *,
        snippets_a: list[str],
        snippets_b: list[str],
    ) -> LLMVerdict:
        """Ask the LLM whether the pair is the same entity. Never raises — failures no-merge."""
        messages = build_adjudication_messages(
            pair, snippets_a=snippets_a, snippets_b=snippets_b
        )
        try:
            completion = await self._client.complete(
                messages=messages,
                model=self._model,
                response_format=_JSON_RESPONSE_FORMAT,
            )
        except Exception as exc:  # noqa: BLE001 - a failed call must not abort the run
            log.warning("adjudicator_call_failed", error=str(exc)[:200])
            return _FALLBACK_VERDICT
        self.cost_usd += completion.cost_usd
        return parse_verdict(completion.content)
