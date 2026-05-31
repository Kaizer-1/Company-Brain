"""Provenance reconciliation check between Neo4j graph and Postgres event store.

STUB — Phase 4 will implement this fully.

This script scans the Neo4j graph for all ``source_event_ids`` referenced by
any node, then verifies that each UUID exists in the Postgres ``events`` table.
It also identifies ``events`` rows that have no graph nodes derived from them
(unextracted or failed extractions older than a configurable age).

Usage (once implemented)::

    uv run python backend/scripts/check_provenance.py

The script exits with code 0 if no orphans are found, 1 if orphans exist,
2 if a connection error occurs.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession


class ProvenanceReport(BaseModel):
    """Summary of a provenance reconciliation check.

    Attributes:
        graph_nodes_count: Total number of graph nodes inspected.
        events_referenced_count: Number of distinct event UUIDs found in
            ``source_event_ids`` across all graph nodes.
        missing_event_ids: Event UUIDs referenced by graph nodes but not found
            in the Postgres ``events`` table.  A non-empty list indicates a
            provenance integrity violation.
        orphan_events_count: Number of ``events`` rows with no corresponding
            graph nodes.  Expected during active ingestion; becomes a warning
            after a configurable age threshold.
    """

    graph_nodes_count: int
    events_referenced_count: int
    missing_event_ids: list[uuid.UUID]
    orphan_events_count: int

    @property
    def is_healthy(self) -> bool:
        """Return True if no provenance violations are found."""
        return len(self.missing_event_ids) == 0


async def check_provenance(
    neo4j_driver: "AsyncDriver",
    postgres_session: "AsyncSession",
) -> ProvenanceReport:
    """Reconcile graph node provenance against the Postgres event store.

    STUB: raises NotImplementedError.  Phase 4 will implement by:
      1. Running a Cypher query to collect all ``source_event_ids`` from every
         graph node across all labels (Service, System, Person, Team, Decision,
         Message).
      2. Querying the Postgres ``events`` table for each collected UUID.
      3. Building the ``ProvenanceReport`` from the diff.

    Args:
        neo4j_driver: A connected Neo4j async driver.
        postgres_session: An open SQLAlchemy async session.

    Returns:
        A ``ProvenanceReport`` summarising any provenance violations.

    Raises:
        NotImplementedError: Always, until Phase 4 implements this function.
    """
    raise NotImplementedError(
        "check_provenance is a Phase 4 stub. "
        "Implementation requires the graph write path (Phase 2E) to be complete."
    )
