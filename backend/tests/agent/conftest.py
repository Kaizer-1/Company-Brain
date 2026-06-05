"""Shared fixtures for the agent tests (Phase 4A).

A ``FakeClient`` stands in for ``OpenRouterClient`` so node tests run with no network and
no API key. It records calls and returns scripted ``CompletionResult`` payloads (or a
sequence of them, to exercise the verification retry loop).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.agent.config import AgentConfig
from app.agent.deps import AgentDeps
from app.extraction.client import CompletionResult


class FakeClient:
    """Scripted stand-in for OpenRouterClient.complete.

    Pass a single ``content`` string, or a sequence of strings to return successively on
    each call (useful for router-then-synthesis or synthesis-retry tests). When the script
    is exhausted the last item repeats.
    """

    def __init__(
        self,
        *,
        content: str | Sequence[str] | None = None,
        raise_exc: Exception | None = None,
        cost_usd: float = 0.001,
    ) -> None:
        if isinstance(content, str):
            self._script: list[str] = [content]
        elif content is None:
            self._script = []
        else:
            self._script = list(content)
        self._raise = raise_exc
        self._cost = cost_usd
        self.calls: list[dict[str, Any]] = []

    async def complete(  # type: ignore[no-untyped-def]
        self, *, messages, model, temperature=None, max_tokens=None, response_format=None
    ) -> CompletionResult:
        self.calls.append({"messages": messages, "model": model, "response_format": response_format})
        if self._raise is not None:
            raise self._raise
        idx = min(len(self.calls) - 1, len(self._script) - 1)
        content = self._script[idx]
        return CompletionResult(
            content=content, model=model, cost_usd=self._cost,
            prompt_tokens=10, completion_tokens=5,
        )

    async def aclose(self) -> None:
        """No-op; present so run_agent's ``finally: aclose()`` works on an injected fake."""
        return None


def make_deps(client: Any, *, neo4j_driver: Any = None, session_factory: Any = None) -> AgentDeps:
    """Build AgentDeps for a node test, with defaults for handles a node may not use."""
    return AgentDeps(
        client=client,
        config=AgentConfig(),
        neo4j_driver=neo4j_driver,
        session_factory=session_factory,
    )
