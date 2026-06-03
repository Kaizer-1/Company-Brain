"""Derive ``SUPERSEDES`` edges from decision text (Phase 3B; ADR 0016).

The extractor cannot emit ``SUPERSEDES`` — the signal is free text in the decision body
("supersedes D-0004"). So this module reads each Decision's source-event content from Postgres,
matches the supersession signal, and writes ``(newer)-[:SUPERSEDES]->(older)`` idempotently,
then marks the older decision ``status='superseded'`` with ``valid_to`` set to the newer
decision's ``valid_from``. Deriving from authoritative source text (not an LLM guess) keeps the
eval deterministic.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

import structlog

from app.schemas.graph import RelationshipType

if TYPE_CHECKING:
    from neo4j import AsyncDriver

    from app.db.repositories.events import EventRepository

log = structlog.get_logger(__name__)

# "supersedes D-0004", "superseding the D-0004 session model", "supersede D-0004".
_SUPERSEDES_RE = re.compile(r"supersed\w*\s+(?:the\s+)?(D-\d{3,4})", re.IGNORECASE)

_EXTRACTED_BY = "temporal-enricher@3b"


def detect_superseded_target(texts: list[str], *, self_id: str) -> str | None:
    """Return the decision id this decision supersedes, from its source text, or None.

    Ignores a self-reference (a decision quoting its own id) so a decision never supersedes
    itself. Returns the first distinct target found across the provided texts.
    """
    for text in texts:
        for match in _SUPERSEDES_RE.finditer(text):
            target = match.group(1)
            if target != self_id:
                return target
    return None


async def _decision_texts(events: EventRepository, source_event_ids: list[str]) -> list[str]:
    """Fetch the source-event contents for a decision (skipping non-UUID/absent ids)."""
    texts: list[str] = []
    for raw in source_event_ids:
        try:
            event_uuid = uuid.UUID(raw)
        except (ValueError, AttributeError):
            continue
        event = await events.get_by_id(event_uuid)
        if event is not None:
            texts.append(event.content)
    return texts


async def apply_supersessions(
    driver: AsyncDriver,
    events: EventRepository,
    decisions: list[dict[str, object]],
) -> tuple[int, int]:
    """Write SUPERSEDES edges and mark superseded decisions; return (edges, marked).

    ``decisions`` is a list of ``{"id", "source_event_ids"}`` dicts for every non-merged
    Decision node (``valid_from`` already populated on the graph by the enricher, so the writer
    can read ``newer.valid_from`` directly). Idempotent: re-running MERGEs the same edge and
    re-sets the same status/valid_to.
    """
    by_id = {str(d["id"]): d for d in decisions}
    edges_written = 0
    marked = 0

    for d in decisions:
        self_id = str(d["id"])
        raw_ids = d.get("source_event_ids") or []
        source_ids = [str(x) for x in raw_ids] if isinstance(raw_ids, (list, tuple)) else []
        texts = await _decision_texts(events, source_ids)
        target_id = detect_superseded_target(texts, self_id=self_id)
        if target_id is None or target_id not in by_id:
            continue

        await _write_supersedes(driver, newer_id=self_id, older_id=target_id)
        edges_written += 1
        marked += 1
        log.info("supersedes_detected", newer=self_id, older=target_id)

    return edges_written, marked


async def _write_supersedes(driver: AsyncDriver, *, newer_id: str, older_id: str) -> None:
    """MERGE the SUPERSEDES edge and mark the older decision superseded with valid_to."""
    query = (
        "MATCH (newer:Decision {id: $newer_id}) "
        "MATCH (older:Decision {id: $older_id}) "
        f"MERGE (newer)-[r:{RelationshipType.SUPERSEDES.value}]->(older) "
        "ON CREATE SET r.created_at = datetime(), r.extracted_by = $extracted_by "
        "SET older.status = 'superseded', older.valid_to = newer.valid_from"
    )
    async with driver.session() as session:
        await (
            await session.run(
                query, newer_id=newer_id, older_id=older_id, extracted_by=_EXTRACTED_BY
            )
        ).consume()
