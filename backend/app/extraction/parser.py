"""Parse and strictly validate an LLM response into an ``ExtractionResult``.

The LLM boundary is untrusted: a model may return malformed JSON, a JSON object with
the wrong shape, or text wrapped in stray prose/code fences despite instructions. This
module fails loudly on all three (Phase 1B lesson: a silent no-op is an invisible bug),
raising a typed ``ExtractionParseError`` that carries the raw response for debugging.
"""

import json
from typing import Final

from pydantic import ValidationError

from app.extraction.models import ExtractionResult

# Some models still wrap JSON in ```json fences despite JSON-mode; strip them defensively.
_FENCE_PREFIXES: Final = ("```json", "```JSON", "```")


class ExtractionParseError(ValueError):
    """Raised when an LLM response cannot be validated into an ``ExtractionResult``.

    Carries the raw response text (``raw``) so the pipeline can log it as the
    ``extraction_runs.error_message`` and a developer can see exactly what the model
    returned. ``stage`` distinguishes a JSON-decode failure from a schema-validation
    failure — the two map to different failure modes in the eval taxonomy.
    """

    def __init__(self, message: str, *, raw: str, stage: str) -> None:
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


def parse_extraction(json_str: str) -> ExtractionResult:
    """Parse a raw LLM response string into a validated ``ExtractionResult``.

    Raises:
        ExtractionParseError: if the response is not valid JSON (``stage="json"``) or
            is valid JSON of the wrong shape (``stage="schema"``). The raw response is
            attached to the exception in both cases.
    """
    candidate = _strip_fences(json_str)
    if not candidate:
        raise ExtractionParseError(
            "empty response from model", raw=json_str, stage="json"
        )

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ExtractionParseError(
            f"response is not valid JSON: {exc}", raw=json_str, stage="json"
        ) from exc

    if not isinstance(payload, dict):
        raise ExtractionParseError(
            f"top-level JSON must be an object, got {type(payload).__name__}",
            raw=json_str,
            stage="schema",
        )

    # Require both keys explicitly. The Pydantic model defaults them to empty lists for
    # ergonomic programmatic construction, but a *model response* missing a key is a
    # truncated/garbled extraction we want to fail loudly rather than silently treat as
    # "extracted nothing of that kind".
    missing = {"entities", "relationships"} - payload.keys()
    if missing:
        raise ExtractionParseError(
            f"response JSON is missing required key(s): {sorted(missing)}",
            raw=json_str,
            stage="schema",
        )

    try:
        # strict=True: reject coerced types (e.g. confidence as a string) — an
        # extraction that needs coercion is a sloppy extraction we want to see fail.
        return ExtractionResult.model_validate(payload, strict=True)
    except ValidationError as exc:
        raise ExtractionParseError(
            f"response JSON does not match the extraction schema: {exc}",
            raw=json_str,
            stage="schema",
        ) from exc
