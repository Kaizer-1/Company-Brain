"""Real-Neo4j tests for the graph writer: provenance, properties, idempotency."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.extraction.graph_writer import write_extraction
from app.extraction.models import ExtractedEntity, ExtractedRelationship, ExtractionResult
from app.schemas.graph import RelationshipType

pytestmark = pytest.mark.asyncio


def _result() -> ExtractionResult:
    return ExtractionResult(
        entities=[
            ExtractedEntity(
                type="Service",
                canonical_name="payments-api",
                properties={"tier": "critical"},
                evidence_quote="payments-api is critical",
                confidence=0.95,
            ),
            ExtractedEntity(
                type="System",
                canonical_name="legacy-auth",
                properties={"status": "deprecated"},
                evidence_quote="legacy-auth is deprecated",
                confidence=0.9,
            ),
        ],
        relationships=[
            ExtractedRelationship(
                type=RelationshipType.DEPENDS_ON,
                source_canonical_name="payments-api",
                target_canonical_name="legacy-auth",
                evidence_quote="payments-api depends on legacy-auth",
                confidence=0.88,
            )
        ],
    )


async def _node(driver: Any, label: str, key_field: str, key: str) -> dict[str, Any] | None:
    async with driver.session() as s:
        result = await s.run(
            f"MATCH (n:{label} {{{key_field}: $key}}) RETURN n", key=key
        )
        record = await result.single()
        return dict(record["n"]) if record else None


async def test_writes_nodes_edges_with_provenance(neo4j_driver: Any) -> None:
    event_id = uuid.uuid4()
    created = datetime(2026, 1, 1, tzinfo=UTC)
    summary = await write_extraction(
        neo4j_driver, event_id, _result(), extracted_by="test@v1", event_created_at=created
    )
    assert summary.nodes_written == 2
    assert summary.edges_written == 1
    assert summary.edges_skipped == 0

    svc = await _node(neo4j_driver, "Service", "canonical_name", "payments-api")
    assert svc is not None
    assert svc["source_event_ids"] == [str(event_id)]
    assert svc["tier"] == "critical"

    async with neo4j_driver.session() as s:
        rel = await (
            await s.run(
                "MATCH (:Service {canonical_name:'payments-api'})-[r:DEPENDS_ON]->"
                "(:System {canonical_name:'legacy-auth'}) RETURN r"
            )
        ).single()
    assert rel is not None
    assert rel["r"]["extracted_by"] == "test@v1"
    assert rel["r"]["source_event_id"] == str(event_id)
    assert 0.0 <= rel["r"]["confidence"] <= 1.0


async def test_idempotent_reextraction_unions_provenance(neo4j_driver: Any) -> None:
    event_a, event_b = uuid.uuid4(), uuid.uuid4()
    await write_extraction(neo4j_driver, event_a, _result(), extracted_by="test@v1")
    await write_extraction(neo4j_driver, event_b, _result(), extracted_by="test@v1")

    # No duplicate nodes.
    async with neo4j_driver.session() as s:
        count = await (
            await s.run("MATCH (n:Service {canonical_name:'payments-api'}) RETURN count(n) AS c")
        ).single()
    assert count["c"] == 1

    svc = await _node(neo4j_driver, "Service", "canonical_name", "payments-api")
    assert svc is not None
    # source_event_ids is the set-union of both events (order-independent).
    assert set(svc["source_event_ids"]) == {str(event_a), str(event_b)}


async def test_unresolved_edge_endpoint_is_skipped(neo4j_driver: Any) -> None:
    result = ExtractionResult(
        entities=[
            ExtractedEntity(
                type="Service", canonical_name="checkout-service",
                evidence_quote="checkout", confidence=0.9,
            )
        ],
        relationships=[
            ExtractedRelationship(
                type=RelationshipType.DEPENDS_ON,
                source_canonical_name="checkout-service",
                target_canonical_name="payments-api",  # not in entities
                evidence_quote="checkout depends on payments-api",
                confidence=0.8,
            )
        ],
    )
    summary = await write_extraction(
        neo4j_driver, uuid.uuid4(), result, extracted_by="test@v1"
    )
    assert summary.nodes_written == 1
    assert summary.edges_written == 0
    assert summary.edges_skipped == 1
