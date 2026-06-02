"""Run one extraction model over the corpus and score it against ground truth.

This is the harness's outer loop. It calls the *extractor's* public surface only
(``OpenRouterClient`` + ``prompts`` + ``parser``) — it never reaches inside the pipeline —
so swapping the model under test is a string change. Per-event raw responses are cached on
disk keyed by ``(model, prompt-fingerprint, event-id)``, so iterating on the eval (or
re-rendering the report) costs nothing after the first run; ``--no-cache`` forces fresh
calls when the prompt changes in a way the fingerprint should already have caught.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from app.eval.failure_modes import FailureBreakdown, classify
from app.eval.ground_truth import GroundTruth, build_ground_truth
from app.eval.matcher import MatchedExtraction, SurfaceIndex, canonicalize_extractions
from app.eval.metrics import Metrics, compute_metrics, compute_metrics_by_type
from app.extraction.models import ExtractionResult
from app.extraction.parser import ExtractionParseError, parse_extraction
from app.extraction.prompts import build_messages, prompt_fingerprint

if TYPE_CHECKING:
    from app.extraction.client import OpenRouterClient
    from app.schemas.postgres import EventDTO

log = structlog.get_logger(__name__)

_JSON_RESPONSE_FORMAT = {"type": "json_object"}
DEFAULT_CACHE_DIR = Path(".eval_cache")


@dataclass(frozen=True)
class _CachedCall:
    content: str
    cost_usd: float


class ExtractionCache:
    """Tiny on-disk cache of raw model responses, keyed by model + prompt + event."""

    def __init__(self, root: Path = DEFAULT_CACHE_DIR) -> None:
        self._root = root
        self._fingerprint = prompt_fingerprint()[:8]

    def _path(self, model: str, event_id: str) -> Path:
        safe_model = model.replace("/", "_")
        return self._root / f"{safe_model}__{self._fingerprint}__{event_id}.json"

    def get(self, model: str, event_id: str) -> _CachedCall | None:
        path = self._path(model, event_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return _CachedCall(content=data["content"], cost_usd=float(data["cost_usd"]))

    def put(self, model: str, event_id: str, call: _CachedCall) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._path(model, event_id)
        path.write_text(
            json.dumps({"content": call.content, "cost_usd": call.cost_usd}),
            encoding="utf-8",
        )


@dataclass(frozen=True)
class EvalResult:
    """Everything the report needs for one model."""

    model: str
    entity_metrics: Metrics
    relationship_metrics: Metrics
    entity_metrics_by_type: dict[str, Metrics]
    relationship_metrics_by_type: dict[str, Metrics]
    failures: FailureBreakdown
    total_cost_usd: float
    fresh_cost_usd: float
    event_count: int
    parse_failures: int
    ground_truth: GroundTruth
    matched: MatchedExtraction


async def run_eval(
    model: str,
    events: list[EventDTO],
    *,
    client: OpenRouterClient,
    cache: ExtractionCache | None = None,
    use_cache: bool = True,
    ground_truth: GroundTruth | None = None,
    index: SurfaceIndex | None = None,
) -> EvalResult:
    """Extract every event with ``model``, canonicalise, and score against ground truth.

    Bounded concurrency is intentionally *not* used here: the eval is run once per model
    and clarity of the per-event cache flow matters more than wall-clock. Parse failures
    are counted and contribute an empty extraction (which correctly costs recall).
    """
    gt = ground_truth or build_ground_truth()
    idx = index or SurfaceIndex()
    cache = cache if cache is not None else ExtractionCache()

    pairs: list[tuple[str, ExtractionResult]] = []
    total_cost = 0.0
    fresh_cost = 0.0
    parse_failures = 0

    for event in events:
        event_id = str(event.id)
        cached = cache.get(model, event_id) if use_cache else None
        if cached is not None:
            content, cost = cached.content, cached.cost_usd
        else:
            completion = await client.complete(
                messages=build_messages(event.content),
                model=model,
                response_format=_JSON_RESPONSE_FORMAT,
            )
            content, cost = completion.content, completion.cost_usd
            fresh_cost += cost
            cache.put(model, event_id, _CachedCall(content=content, cost_usd=cost))
        total_cost += cost

        try:
            result = parse_extraction(content)
        except ExtractionParseError as exc:
            parse_failures += 1
            log.warning("eval_parse_failure", model=model, event_id=event_id, error=str(exc)[:200])
            result = ExtractionResult()
        pairs.append((event_id, result))

    matched = canonicalize_extractions(pairs, index=idx)

    expected_entities = {(e.type, e.canonical_name) for e in gt.entities}
    expected_rels = {
        (r.type, r.source_canonical_name, r.target_canonical_name) for r in gt.relationships
    }
    entity_metrics = compute_metrics(set(matched.entity_keys), expected_entities)
    relationship_metrics = compute_metrics(set(matched.relationship_keys), expected_rels)
    entity_by_type = compute_metrics_by_type(
        matched.entity_keys, expected_entities, key=lambda x: x[0]
    )
    rel_by_type = compute_metrics_by_type(
        matched.relationship_keys, expected_rels, key=lambda x: str(x[0])
    )
    failures = classify(matched, gt)

    log.info(
        "eval_complete",
        model=model,
        entity_f1=round(entity_metrics.f1, 3),
        relationship_f1=round(relationship_metrics.f1, 3),
        total_cost_usd=round(total_cost, 4),
        parse_failures=parse_failures,
    )
    return EvalResult(
        model=model,
        entity_metrics=entity_metrics,
        relationship_metrics=relationship_metrics,
        entity_metrics_by_type=entity_by_type,
        relationship_metrics_by_type=rel_by_type,
        failures=failures,
        total_cost_usd=total_cost,
        fresh_cost_usd=fresh_cost,
        event_count=len(events),
        parse_failures=parse_failures,
        ground_truth=gt,
        matched=matched,
    )
