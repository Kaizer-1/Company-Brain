"""Shared LLM call + JSON-parse helper for the agent nodes (Phase 4A).

Both the router and the synthesiser follow the same boundary discipline established in
Phase 2B/3A: request ``json_object`` output, strip stray code fences defensively, then
``model_validate`` into a typed Pydantic model. This module centralises that so the two
nodes don't duplicate the fence-stripping and error-typing logic.

It does NOT swallow errors the way the resolution adjudicator does — the agent wants to
distinguish a parse failure (retryable) from a successful classification, so failures
raise a typed ``AgentLLMError`` the caller decides how to handle.
"""

from __future__ import annotations

import json
from typing import Final, TypeVar

import structlog
from pydantic import BaseModel, ValidationError

from app.extraction.client import OpenRouterClient, OpenRouterError

log = structlog.get_logger(__name__)

_JSON_RESPONSE_FORMAT: Final = {"type": "json_object"}
_FENCE_PREFIXES: Final = ("```json", "```JSON", "```")

T = TypeVar("T", bound=BaseModel)


class AgentLLMError(RuntimeError):
    """Raised when an agent LLM call fails to produce a valid model of the expected shape.

    Carries the raw response (when available) so the node can log it. ``stage`` is one of
    ``"call"`` (the API call itself failed), ``"json"`` (response was not valid JSON), or
    ``"schema"`` (valid JSON of the wrong shape) — the same taxonomy as extraction.
    """

    def __init__(self, message: str, *, raw: str = "", stage: str) -> None:
        super().__init__(message)
        self.raw = raw
        self.stage = stage


def _strip_fences(text: str) -> str:
    """Remove a leading/trailing markdown code fence if the model added one."""
    stripped = text.strip()
    for prefix in _FENCE_PREFIXES:
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :]
            break
    if stripped.endswith("```"):
        stripped = stripped[: -len("```")]
    return stripped.strip()


async def complete_to_model[T: BaseModel](
    client: OpenRouterClient,
    *,
    model: str,
    messages: list[dict[str, str]],
    schema: type[T],
    temperature: float,
    max_tokens: int,
) -> tuple[T, float]:
    """Call the LLM, parse the JSON response into ``schema``, return (instance, cost_usd).

    Raises ``AgentLLMError`` on call failure, malformed JSON, or schema mismatch. The cost
    is returned separately so the caller can accumulate it into the per-question total
    (the client already logs ``openrouter_completion`` for the dollar amount).
    """
    try:
        completion = await client.complete(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=_JSON_RESPONSE_FORMAT,
        )
    except OpenRouterError as exc:
        raise AgentLLMError(f"LLM call failed: {exc}", stage="call") from exc
    except Exception as exc:  # noqa: BLE001 - the LLM boundary is untrusted; any call-time
        # failure (network, unexpected client error) must become a typed, handleable error
        # so the load-bearing router can fall back rather than crashing the request.
        raise AgentLLMError(f"unexpected LLM call error: {exc}", stage="call") from exc

    raw = completion.content
    candidate = _strip_fences(raw)
    if not candidate:
        raise AgentLLMError("empty LLM response", raw=raw, stage="json")
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise AgentLLMError(f"response was not valid JSON: {exc}", raw=raw, stage="json") from exc
    try:
        instance = schema.model_validate(data)
    except ValidationError as exc:
        raise AgentLLMError(
            f"response did not match {schema.__name__}: {exc}", raw=raw, stage="schema"
        ) from exc

    return instance, completion.cost_usd
