"""Scoped contradiction detection for live ingestion (Phase 5A).

The batch detector (``detect_contradictions``) re-scans *all* recent Messages against *all*
active Decisions every run — correct for a one-shot pipeline, but at ingestion time it would
re-adjudicate (and re-pay for) every pre-existing pair on every new event. These two entry
points scope detection to just the node a live event introduced:

- ``detect_for_new_message`` — one new Message vs. all active Decisions.
- ``detect_for_new_decision`` — one new Decision vs. all recent Messages.

Both reuse the batch detector's candidate gate (``is_candidate``), adjudicator, and idempotent
``MERGE`` writer, so a scoped pass and a batch pass write byte-identical edges; only the work
done differs. They live in the contradiction package (not ``app.ingestion``) so the Cypher and
the detector internals they reuse stay intra-package.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from app.contradiction.detector import (  # noqa: PLC2701 — intra-package reuse of detector internals
    DETECTION_WINDOW,
    ContradictionAdjudicator,
    _first_event,
    _load_active_decisions,
    _load_recent_messages,
    _write_contradicts,
    is_candidate,
)
from app.contradiction.models import ContradictionResult, WrittenContradiction
from app.observability import metrics
from app.queries.temporal import resolve_as_of

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from neo4j import AsyncDriver

    from app.extraction.client import OpenRouterClient

log = structlog.get_logger(__name__)

# Adjudications of distinct (message, decision) pairs are independent, so we fan them out with a
# bounded concurrency rather than awaiting each in turn — the single biggest ingestion-latency win
# (the first smoke spent ~2s per sequential call). The cap protects the OpenRouter rate limit.
_ADJUDICATION_CONCURRENCY = 5


def _subjects(decision: dict[str, object]) -> list[str]:
    """The decision's ABOUT/DEPRECATES subject names as a clean list of strings."""
    value = decision.get("subjects")
    return [str(s) for s in value if s] if isinstance(value, list) else []


async def _load_one_message(driver: AsyncDriver, message_id: str) -> dict[str, object] | None:
    """Load a single non-merged Message by id, regardless of the detection window.

    We load by id (not by window) because the message was just ingested and is known to be the
    scope; the window only constrains which *decisions'* peers we compare a new decision against.
    """
    query = (
        "MATCH (m:Message {id: $mid}) WHERE coalesce(m.status,'active') <> 'merged' "
        "RETURN m.id AS id, m.content AS content, m.source_event_ids AS source_event_ids"
    )
    async with driver.session() as session:
        record = await (await session.run(query, mid=message_id)).single()
    if record is None:
        return None
    return {
        "id": record["id"],
        "content": record["content"],
        "source_event_ids": record["source_event_ids"],
    }


async def detect_for_new_message(
    driver: AsyncDriver,
    *,
    message_id: str,
    client: OpenRouterClient | None = None,
    as_of: datetime | None = None,
    window: timedelta = DETECTION_WINDOW,
) -> tuple[ContradictionResult, list[WrittenContradiction]]:
    """Detect contradictions between one new Message and every active Decision.

    Returns the count summary plus the list of edges actually written. With no client the pass
    generates candidates but writes nothing (the same conservative no-op the batch detector uses).
    """
    message = await _load_one_message(driver, message_id)
    if message is None:
        return ContradictionResult(), []

    decisions = await _load_active_decisions(driver)
    content = str(message["content"])
    candidates = [
        dec
        for dec in decisions
        if is_candidate(content, decision_id=str(dec["id"]), subjects=_subjects(dec))
    ]

    result = ContradictionResult(messages_ingested=1, candidate_pairs=len(candidates))
    written: list[WrittenContradiction] = []
    if client is None:
        return result, written

    adjudicator = ContradictionAdjudicator(client)
    sem = asyncio.Semaphore(_ADJUDICATION_CONCURRENCY)

    async def _judge(dec: dict[str, object]) -> tuple[str, float] | None:
        async with sem:
            verdict = await adjudicator.adjudicate(
                message_content=content,
                decision_id=str(dec["id"]),
                title=str(dec.get("title") or ""),
            )
        metrics.record_contradiction()
        return (str(dec["id"]), verdict.confidence) if verdict.contradicts else None

    verdicts = await asyncio.gather(*[_judge(dec) for dec in candidates])
    src = _first_event(message)
    for hit in verdicts:
        if hit is None:
            continue
        decision_id, confidence = hit
        await _write_contradicts(
            driver,
            message_id=str(message["id"]),
            decision_id=decision_id,
            confidence=confidence,
            source_event_id=src,
        )
        written.append(
            WrittenContradiction(
                message_id=str(message["id"]), decision_id=decision_id, confidence=confidence
            )
        )
    result.contradicts_written = len(written)
    result.llm_cost_usd = adjudicator.cost_usd
    log.info("scoped_contradiction_for_message", message_id=message_id, written=len(written))
    return result, written


async def detect_for_new_decision(
    driver: AsyncDriver,
    *,
    decision_id: str,
    client: OpenRouterClient | None = None,
    as_of: datetime | None = None,
    window: timedelta = DETECTION_WINDOW,
) -> tuple[ContradictionResult, list[WrittenContradiction]]:
    """Detect contradictions between one new Decision and every recent Message.

    The window is computed relative to ``as_of`` (the ingest time), so a live decision is
    compared against messages from the period leading up to it.
    """
    effective = resolve_as_of(as_of)
    window_start = effective - window
    decisions = await _load_active_decisions(driver)
    decision = next((d for d in decisions if str(d["id"]) == decision_id), None)
    if decision is None:
        return ContradictionResult(), []

    subjects = _subjects(decision)
    messages = await _load_recent_messages(driver, window_start, effective)
    candidates = [
        msg
        for msg in messages
        if is_candidate(str(msg["content"]), decision_id=decision_id, subjects=subjects)
    ]

    result = ContradictionResult(messages_ingested=len(messages), candidate_pairs=len(candidates))
    written: list[WrittenContradiction] = []
    if client is None:
        return result, written

    adjudicator = ContradictionAdjudicator(client)
    sem = asyncio.Semaphore(_ADJUDICATION_CONCURRENCY)
    title = str(decision.get("title") or "")

    async def _judge(msg: dict[str, object]) -> tuple[str, str | None, float] | None:
        async with sem:
            verdict = await adjudicator.adjudicate(
                message_content=str(msg["content"]), decision_id=decision_id, title=title
            )
        metrics.record_contradiction()
        return (
            (str(msg["id"]), _first_event(msg), verdict.confidence)
            if verdict.contradicts
            else None
        )

    verdicts = await asyncio.gather(*[_judge(msg) for msg in candidates])
    for hit in verdicts:
        if hit is None:
            continue
        message_id, src, confidence = hit
        await _write_contradicts(
            driver,
            message_id=message_id,
            decision_id=decision_id,
            confidence=confidence,
            source_event_id=src,
        )
        written.append(
            WrittenContradiction(
                message_id=message_id, decision_id=decision_id, confidence=confidence
            )
        )
    result.contradicts_written = len(written)
    result.llm_cost_usd = adjudicator.cost_usd
    log.info("scoped_contradiction_for_decision", decision_id=decision_id, written=len(written))
    return result, written
