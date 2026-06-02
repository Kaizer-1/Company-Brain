"""Write a validated ``ExtractionResult`` into Neo4j with provenance.

The translation from the LLM's flat output to the locked graph schema lives here. Two
invariants:

- **Idempotent** — every node/edge is ``MERGE``d on its canonical key, so re-extracting
  the same event never duplicates nodes; a node's ``source_event_ids`` accumulates as a
  set union across the events that mention it (multi-source provenance is in the schema
  today even though entity *resolution* is Phase 3B).
- **Best-effort identity** — entity resolution is not this phase. ``Alice Chen`` and
  ``@alice`` legitimately become two ``Person`` nodes here; the schema is designed to let
  Phase 3B merge them later. This is named, not hidden.

A relationship whose endpoints were not also returned as entities cannot be given a node
label, so it is skipped and counted (not silently dropped — the count surfaces in the
``WriteSummary`` and the logs).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from app.schemas.graph import RelationshipType

if TYPE_CHECKING:
    from uuid import UUID

    from neo4j import AsyncDriver, AsyncManagedTransaction

    from app.extraction.models import EntityType, ExtractedEntity, ExtractionResult

log = structlog.get_logger(__name__)

# Property keys the writer manages itself; never let the model's free-form ``properties``
# overwrite identity/provenance columns.
_RESERVED_PROPS = frozenset(
    {"id", "canonical_name", "canonical_id", "source_event_ids", "created_at"}
)

# The canonical-key *property name* for each label (matches the uniqueness constraints in
# migrations/graph/001_constraints.cypher).
_KEY_FIELD: dict[EntityType, str] = {
    "Service": "canonical_name",
    "System": "canonical_name",
    "Team": "canonical_name",
    "Person": "canonical_id",
    "Decision": "id",
}


@dataclass(frozen=True)
class WriteSummary:
    """Counts returned from a single-event write, for the audit row and logs."""

    nodes_written: int
    edges_written: int
    edges_skipped: int


def _slug(text: str) -> str:
    """Best-effort slug for a Person canonical_id (resolution is Phase 3B)."""
    cleaned = text.strip().lower().lstrip("@")
    return re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-") or "unknown"


def _key_value(entity: ExtractedEntity) -> str:
    """The canonical key value used to MERGE this entity's node.

    Service/System/Team and Decision key on the name/id verbatim; Person keys on a slug
    of its name so ``Alice Chen`` and ``alice chen`` at least collapse, while distinct
    surface forms (``@alice``) remain separate until Phase 3B.
    """
    if entity.type == "Person":
        return _slug(entity.canonical_name)
    return entity.canonical_name


def _safe_props(properties: dict[str, object]) -> dict[str, object]:
    """Keep only scalar, non-reserved properties (Neo4j stores scalars/arrays only)."""
    return {
        k: v
        for k, v in properties.items()
        if k not in _RESERVED_PROPS and isinstance(v, str | int | float | bool)
    }


async def write_extraction(
    driver: AsyncDriver,
    event_id: UUID,
    result: ExtractionResult,
    *,
    extracted_by: str,
    event_created_at: datetime | None = None,
) -> WriteSummary:
    """MERGE ``result`` into Neo4j as nodes/edges tagged with this event's provenance.

    Args:
        driver: a connected Neo4j async driver.
        event_id: the Postgres ``events`` UUID this extraction came from — written into
            every node's ``source_event_ids`` and every edge's ``source_event_id``.
        result: the validated extraction output.
        extracted_by: model name+version, recorded on every edge (schema requirement).
        event_created_at: the event's timestamp, used as ``created_at`` for newly
            created nodes; defaults to now (UTC) if unknown.

    Returns:
        A ``WriteSummary`` with node/edge/skip counts. The whole event is written in one
        transaction, so a mid-write failure leaves no partial graph state.
    """
    eid = str(event_id)
    created_at_iso = (event_created_at or datetime.now(UTC)).isoformat()

    # name -> (label, key_value) for resolving relationship endpoints to labelled nodes.
    entity_index: dict[str, tuple[EntityType, str]] = {
        e.canonical_name: (e.type, _key_value(e)) for e in result.entities
    }

    edges_skipped = 0
    edge_specs: list[dict[str, object]] = []
    for rel in result.relationships:
        src = entity_index.get(rel.source_canonical_name)
        tgt = entity_index.get(rel.target_canonical_name)
        if src is None or tgt is None:
            edges_skipped += 1
            log.warning(
                "edge_endpoint_unresolved",
                rel_type=str(rel.type),
                source=rel.source_canonical_name,
                target=rel.target_canonical_name,
                event_id=eid,
            )
            continue
        edge_specs.append(
            {
                "type": rel.type,
                "src_label": src[0],
                "src_key_field": _KEY_FIELD[src[0]],
                "src_key": src[1],
                "tgt_label": tgt[0],
                "tgt_key_field": _KEY_FIELD[tgt[0]],
                "tgt_key": tgt[1],
                "confidence": rel.confidence,
                "evidence_quote": rel.evidence_quote,
            }
        )

    node_specs = [
        {
            "label": e.type,
            "key_field": _KEY_FIELD[e.type],
            "key": _key_value(e),
            "props": _safe_props(e.properties),
            "confidence": e.confidence,
        }
        for e in result.entities
    ]

    async def _txn(tx: AsyncManagedTransaction) -> None:
        for node in node_specs:
            await _merge_node(tx, node, eid=eid, created_at_iso=created_at_iso)
        for edge in edge_specs:
            await _merge_edge(
                tx, edge, eid=eid, extracted_by=extracted_by, created_at_iso=created_at_iso
            )

    async with driver.session() as session:
        await session.execute_write(_txn)

    summary = WriteSummary(
        nodes_written=len(node_specs),
        edges_written=len(edge_specs),
        edges_skipped=edges_skipped,
    )
    log.info(
        "graph_write_complete",
        event_id=eid,
        nodes=summary.nodes_written,
        edges=summary.edges_written,
        edges_skipped=summary.edges_skipped,
    )
    return summary


async def _merge_node(
    tx: AsyncManagedTransaction,
    node: dict[str, object],
    *,
    eid: str,
    created_at_iso: str,
) -> None:
    label = node["label"]
    key_field = node["key_field"]
    # label and key_field come from closed vocabularies (_KEY_FIELD / EntityType), never
    # user text — safe to interpolate where Cypher forbids parameters (labels/keys).
    assert label in _KEY_FIELD  # noqa: S101 - defensive invariant on a closed set
    query = (
        f"MERGE (n:{label} {{{key_field}: $key}}) "
        f"ON CREATE SET n.id = $key, n.source_event_ids = [$eid], "
        f"  n.created_at = datetime($created_at) "
        "ON MATCH SET n.source_event_ids = "
        "  CASE WHEN $eid IN n.source_event_ids THEN n.source_event_ids "
        "       ELSE n.source_event_ids + $eid END "
        "SET n += $props"
    )
    await tx.run(
        query,
        key=node["key"],
        eid=eid,
        created_at=created_at_iso,
        props=node["props"],
    )


async def _merge_edge(
    tx: AsyncManagedTransaction,
    edge: dict[str, object],
    *,
    eid: str,
    extracted_by: str,
    created_at_iso: str,
) -> None:
    rel_type = edge["type"]
    assert isinstance(rel_type, RelationshipType)  # noqa: S101 - closed vocabulary
    src_label, tgt_label = edge["src_label"], edge["tgt_label"]
    src_field, tgt_field = edge["src_key_field"], edge["tgt_key_field"]
    query = (
        f"MATCH (s:{src_label} {{{src_field}: $skey}}) "
        f"MATCH (t:{tgt_label} {{{tgt_field}: $tkey}}) "
        f"MERGE (s)-[r:{rel_type.value}]->(t) "
        "ON CREATE SET r.created_at = datetime($created_at) "
        "SET r.confidence = $confidence, r.extracted_by = $extracted_by, "
        "    r.source_event_id = $eid, r.evidence_quote = $evidence_quote"
    )
    await tx.run(
        query,
        skey=edge["src_key"],
        tkey=edge["tgt_key"],
        created_at=created_at_iso,
        confidence=edge["confidence"],
        extracted_by=extracted_by,
        eid=eid,
        evidence_quote=edge["evidence_quote"],
    )
