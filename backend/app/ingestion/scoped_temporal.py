"""Scoped temporal enrichment for live ingestion (Phase 5A).

A deliberately thin pass-through over Phase 3B's ``enrich_temporal``. The 5A pre-implementation
check established that temporal enrichment (a) makes **zero** LLM calls, (b) is fully idempotent
(it recomputes the same ``valid_from``/``valid_to``/``status`` and ``MERGE``s the same
``SUPERSEDES`` edges), and (c) runs in milliseconds over the ≤ ~10 Decision nodes at this scale.

Refactoring it for per-decision scope would add complexity and a divergence-risk for no cost or
latency benefit, so ingestion runs the full pass — but only when the event actually introduced
or changed a Decision (the orchestrator gates the call). This wrapper exists to (1) make that
decision explicit and documented at the call site, and (2) give the orchestrator a stable seam
to swap in true per-decision scope later if Decision volume ever grows (ADR 0031).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.temporal.enricher import enrich_temporal

if TYPE_CHECKING:
    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.temporal.models import TemporalEnrichmentResult


async def run_scoped_temporal(
    driver: AsyncDriver, session: AsyncSession
) -> TemporalEnrichmentResult:
    """Run temporal enrichment + supersession detection (full, idempotent, LLM-free)."""
    return await enrich_temporal(driver, session)
