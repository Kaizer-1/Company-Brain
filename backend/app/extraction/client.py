"""Async OpenRouter client.

One small wrapper over OpenRouter's OpenAI-compatible ``/chat/completions`` endpoint.
OpenRouter is chosen (ADR 0012) so the same code talks to gpt-4o-mini, claude-3.5-haiku,
and gemini-2.0-flash by changing one ``model`` string — which is what makes the
three-model eval cheap to run.

Responsibilities kept here and nowhere else:

- Read the API key from ``settings`` (never ``os.environ`` — project rule).
- Request JSON-mode output and per-call cost accounting.
- Log the real dollar cost of every call (OpenRouter returns ``usage.cost`` when asked).
- Retry transient failures (429 rate-limit, 503 overload) with bounded exponential
  backoff. Retries are implemented inline rather than via ``tenacity`` to avoid adding a
  dependency for ~15 lines of well-understood logic.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx
import structlog

from app.config import settings

log = structlog.get_logger(__name__)

# Transport + retry tuning. Extraction calls are short; 30s is generous. Three retries
# with 1s/2s/4s backoff rides out brief rate-limit/overload blips without hanging a
# 111-event run.
_TIMEOUT_SECONDS = 30.0
_MAX_RETRIES = 3
_RETRY_STATUS = frozenset({429, 503})
_BACKOFF_BASE_SECONDS = 1.0


class OpenRouterError(RuntimeError):
    """Raised when OpenRouter returns a non-retryable error or retries are exhausted."""


@dataclass(frozen=True)
class CompletionResult:
    """The outcome of one chat completion.

    ``content`` is the assistant message text (the JSON the parser consumes).
    ``cost_usd`` is the real dollar cost OpenRouter charged for the call (0.0 if the
    provider did not report it). Token counts are kept for the eval report's telemetry.
    """

    content: str
    model: str
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int


class OpenRouterClient:
    """Thin async client over OpenRouter's chat-completions API.

    A single instance is reused across many events (and many models — ``model`` is a
    per-call argument, not construction state). Construct one, call ``complete`` N times,
    ``aclose`` once. Usable as an async context manager.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.openrouter_api_key
        self._base_url = (base_url or settings.openrouter_base_url).rstrip("/")
        # An injected client makes the transport mockable in tests.
        self._client = client or httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)
        self._owns_client = client is None

    async def __aenter__(self) -> OpenRouterClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying transport if this client created it."""
        if self._owns_client:
            await self._client.aclose()

    @property
    def has_api_key(self) -> bool:
        """True if an API key is configured (used to skip the real-API smoke test)."""
        return bool(self._api_key)

    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, str] | None = None,
    ) -> CompletionResult:
        """Run one chat completion and return its content, cost, and token usage.

        Retries 429/503 with exponential backoff up to ``_MAX_RETRIES``. Any other
        non-2xx response, or exhausted retries, raises ``OpenRouterError``.
        """
        if not self._api_key:
            raise OpenRouterError(
                "OPENROUTER_API_KEY is not set; cannot call the API. "
                "Set it in .env (see .env.example)."
            )

        body: dict[str, object] = {
            "model": model,
            "messages": messages,
            "temperature": (
                temperature if temperature is not None else settings.extraction_temperature
            ),
            "max_tokens": (
                max_tokens if max_tokens is not None else settings.extraction_max_tokens
            ),
            # Ask OpenRouter to echo the real cost of the call back in the usage block.
            "usage": {"include": True},
        }
        if response_format is not None:
            body["response_format"] = response_format

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            # Optional attribution headers OpenRouter recommends; harmless if ignored.
            "HTTP-Referer": "https://github.com/company-brain",
            "X-Title": "Company Brain extraction",
        }
        url = f"{self._base_url}/chat/completions"

        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await self._client.post(url, json=body, headers=headers)
            except httpx.HTTPError as exc:  # network-level failure — treat as retryable
                last_error = exc
                if attempt < _MAX_RETRIES:
                    await self._backoff(attempt, model=model, reason=str(exc))
                    continue
                raise OpenRouterError(f"network error calling OpenRouter: {exc}") from exc

            if response.status_code in _RETRY_STATUS and attempt < _MAX_RETRIES:
                await self._backoff(
                    attempt, model=model, reason=f"http {response.status_code}"
                )
                continue
            if response.status_code >= 400:
                raise OpenRouterError(
                    f"OpenRouter returned {response.status_code}: {response.text[:500]}"
                )

            return self._parse_response(response.json(), model=model)

        # Only reached if every attempt was a retryable status without success.
        raise OpenRouterError(
            f"OpenRouter retries exhausted for model {model}: {last_error}"
        )

    async def _backoff(self, attempt: int, *, model: str, reason: str) -> None:
        delay = _BACKOFF_BASE_SECONDS * (2**attempt)
        log.warning(
            "openrouter_retry",
            model=model,
            attempt=attempt + 1,
            max_retries=_MAX_RETRIES,
            reason=reason,
            sleep_seconds=delay,
        )
        await asyncio.sleep(delay)

    @staticmethod
    def _parse_response(payload: dict[str, object], *, model: str) -> CompletionResult:
        """Extract content, cost, and token usage from an OpenRouter JSON response."""
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise OpenRouterError(f"OpenRouter response had no choices: {payload}")
        first = choices[0]
        message = first.get("message", {}) if isinstance(first, dict) else {}
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise OpenRouterError(f"OpenRouter response had no message content: {payload}")

        usage = payload.get("usage")
        usage_dict = usage if isinstance(usage, dict) else {}
        cost = float(usage_dict.get("cost", 0.0) or 0.0)
        prompt_tokens = int(usage_dict.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage_dict.get("completion_tokens", 0) or 0)

        log.info(
            "openrouter_completion",
            model=model,
            cost_usd=cost,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        return CompletionResult(
            content=content,
            model=model,
            cost_usd=cost,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
