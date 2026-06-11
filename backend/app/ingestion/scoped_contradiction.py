"""Scoped contradiction detection adapter for live ingestion (Phase 5A).

The reconciliation pipeline needs one entry point that, given what a live event introduced,
runs the right scoped detector(s) and returns ``ContradictionRef``s for the response. The actual
detection lives in ``app.contradiction.scoped`` (intra-package with the detector internals it
reuses); this module only adapts it to the ingestion layer's needs:

- a new ``slack_message`` event → its Message vs. all active Decisions, and
- any new Decision the event asserted → that Decision vs. all recent Messages.

Returning ``(refs, cost, candidate_pairs)`` lets the orchestrator fold the cost into the run's
total and report how much adjudication work the event triggered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from app.contradiction.scoped import detect_for_new_decision, detect_for_new_message
from app.ingestion.schemas import ContradictionRef

if TYPE_CHECKING:
    from datetime import datetime

    from neo4j import AsyncDriver

    from app.contradiction.models import WrittenContradiction
    from app.extraction.client import OpenRouterClient
    from app.ingestion.schemas import SourceKind

log = structlog.get_logger(__name__)


def _to_refs(written: list[WrittenContradiction]) -> list[ContradictionRef]:
    return [
        ContradictionRef(
            message_id=w.message_id, decision_id=w.decision_id, confidence=w.confidence
        )
        for w in written
    ]


async def run_scoped_contradiction(
    driver: AsyncDriver,
    *,
    source_kind: SourceKind,
    message_id: str | None,
    decision_ids: list[str],
    client: OpenRouterClient | None,
    as_of: datetime | None,
) -> tuple[list[ContradictionRef], float, int]:
    """Run the scoped detector(s) for what this event introduced.

    Returns ``(contradiction_refs, cost_usd, candidate_pairs)``.
    """
    refs: list[ContradictionRef] = []
    cost = 0.0
    candidates = 0

    if source_kind == "slack_message" and message_id is not None:
        result, written = await detect_for_new_message(
            driver, message_id=message_id, client=client, as_of=as_of
        )
        cost += result.llm_cost_usd
        candidates += result.candidate_pairs
        refs.extend(_to_refs(written))

    for decision_id in decision_ids:
        result, written = await detect_for_new_decision(
            driver, decision_id=decision_id, client=client, as_of=as_of
        )
        cost += result.llm_cost_usd
        candidates += result.candidate_pairs
        refs.extend(_to_refs(written))

    log.info(
        "scoped_contradiction_stage",
        source_kind=source_kind,
        decisions=len(decision_ids),
        candidates=candidates,
        written=len(refs),
    )
    return refs, cost, candidates
