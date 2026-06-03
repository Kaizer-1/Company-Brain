"""Project schema edges onto canonical winners after resolution (Phase 3B).

Phase 3A's merger is non-destructive: it tombstones a loser (``status='merged'``) and links it to
its winner with ``MERGE_INTO``, but it does **not** move the loser's schema edges. So a
``MEMBER_OF``/``OWNED_BY``/``DEPENDS_ON`` edge written on a surface form that later loses
resolution is left attached to a tombstoned node, where a ``status <> 'merged'`` query cannot see
it (e.g. KQ1 would miss the owner). The post-3A HANDOFF (open question #4) left this to 3B; this
module is the "one-pass chain-collapse cleanup" it named.

For every schema edge whose endpoints are not already canonical, we ``MERGE`` an equivalent edge
between the canonical winners (following ``MERGE_INTO`` transitively to the head of each chain).
The original edges stay on the tombstoned losers, so resolution remains reversible; queries see
only the projected edges via the ``status <> 'merged'`` filter. Idempotent: re-running re-MERGEs
the same canonical edges and creates nothing new.

Plain Cypher (one statement per edge type, the label interpolated from the closed
``RelationshipType`` vocabulary) — deliberately APOC-free so it runs on the testcontainer Neo4j
image, which does not load the APOC plugin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from app.schemas.graph import RelationshipType

if TYPE_CHECKING:
    from neo4j import AsyncDriver

log = structlog.get_logger(__name__)

# Every schema edge except MERGE_INTO itself (which encodes the resolution, not the domain).
_PROJECTED_TYPES = tuple(RelationshipType)


def _projection_query(rel_type: str) -> str:
    """Cypher that copies every non-canonical-endpoint ``rel_type`` edge onto canonical winners."""
    return (
        f"MATCH (a)-[r:{rel_type}]->(b) "
        "OPTIONAL MATCH (a)-[:MERGE_INTO*]->(ac) WHERE NOT (ac)-[:MERGE_INTO]->() "
        "OPTIONAL MATCH (b)-[:MERGE_INTO*]->(bc) WHERE NOT (bc)-[:MERGE_INTO]->() "
        "WITH r, a, b, coalesce(ac, a) AS src, coalesce(bc, b) AS tgt "
        "WHERE (a <> src OR b <> tgt) AND src <> tgt "
        f"MERGE (src)-[nr:{rel_type}]->(tgt) "
        "ON CREATE SET nr = properties(r)"
    )


async def project_resolved_edges(driver: AsyncDriver) -> int:
    """Project loser schema edges onto canonical winners; return edges created.

    Run after entity resolution and Decision consolidation, before the killer queries.
    """
    created = 0
    async with driver.session() as session:
        for rel_type in _PROJECTED_TYPES:
            result = await session.run(_projection_query(rel_type.value))
            summary = await result.consume()
            created += summary.counters.relationships_created
    log.info("edges_projected_to_canonical", edges_created=created)
    return created
