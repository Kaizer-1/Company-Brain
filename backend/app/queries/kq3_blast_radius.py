"""KQ3 — blast radius (Phase 3B).

> If the payments service fails, which services, decisions, and people are affected?

Cypher pattern (resolved view): walk ``DEPENDS_ON`` *into* the seed (affected = upstream
dependents), then expand each affected service to owners, team members, and decisions.

    (affected:Service)-[:DEPENDS_ON*1..max_depth]->(seed:Service)
    (svc)-[:OWNED_BY]->(owner) ; (owner)<-[:MEMBER_OF]-(person)
    (dec:Decision)-[:ABOUT|DEPRECATES]->(svc)

Worked example: ``compute_blast_radius(service_name="payments-api")`` returns the 10 services
that transitively depend on it (incl. ``web-storefront`` two hops up), the people who own any of
them, and the active decisions about them. Provenance is the dependency-chain edge events. The
``*1..max_depth`` bound is the tunable safety rail against exponential blow-up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.queries.result_types import QueryProvenance, QueryResult

if TYPE_CHECKING:
    from neo4j import AsyncDriver

_MAX_DEPTH_CEILING = 10


class BlastRadius(BaseModel):
    """KQ3's answer: everything affected if the seed service fails."""

    seed_service: str
    affected_services: list[str] = Field(default_factory=list)
    affected_people: list[str] = Field(default_factory=list)
    affected_decisions: list[str] = Field(default_factory=list)
    max_depth_reached: int = 0


def _impact_query(max_depth: int) -> str:
    # max_depth is an int validated in [1, ceiling] — safe to interpolate where Cypher forbids
    # a parameter (the variable-length bound).
    return f"""
MATCH (seed:Service {{canonical_name: $service_name}})
WHERE coalesce(seed.status,'active') <> 'merged'
OPTIONAL MATCH p = (affected:Service)-[:DEPENDS_ON*1..{max_depth}]->(seed)
WHERE all(n IN nodes(p) WHERE coalesce(n.status,'active') <> 'merged')
WITH seed, collect(DISTINCT affected) AS deps
WITH [seed] + deps AS impacted
UNWIND impacted AS svc
OPTIONAL MATCH (svc)-[:OWNED_BY]->(owner) WHERE coalesce(owner.status,'active') <> 'merged'
OPTIONAL MATCH (owner)<-[:MEMBER_OF]-(person:Person) WHERE coalesce(person.status,'active') <> 'merged'
OPTIONAL MATCH (dec:Decision)-[:ABOUT|DEPRECATES]->(svc) WHERE coalesce(dec.status,'active') <> 'merged'
RETURN collect(DISTINCT svc.canonical_name) AS services,
       collect(DISTINCT dec.id) AS decisions,
       collect(DISTINCT coalesce(person.canonical_id, owner.canonical_id)) AS people
"""


def _provenance_query(max_depth: int) -> str:
    return f"""
MATCH (seed:Service {{canonical_name: $service_name}})
MATCH p = (affected:Service)-[:DEPENDS_ON*1..{max_depth}]->(seed)
WHERE all(n IN nodes(p) WHERE coalesce(n.status,'active') <> 'merged')
RETURN affected.canonical_name AS svc, length(p) AS depth,
       [r IN relationships(p) | r.source_event_id] AS edge_events
"""


async def compute_blast_radius(
    driver: AsyncDriver,
    *,
    service_name: str,
    max_depth: int = 5,
    as_of: object | None = None,  # noqa: ARG001 - symmetry with temporal queries; KQ3 is structural
) -> QueryResult[BlastRadius]:
    """Return all services transitively depending on ``service_name``, plus people and decisions."""
    depth = max(1, min(max_depth, _MAX_DEPTH_CEILING))

    async with driver.session() as session:
        impact = await (await session.run(_impact_query(depth), service_name=service_name)).single()
        prov_result = await session.run(_provenance_query(depth), service_name=service_name)
        prov_rows = [record.data() async for record in prov_result]

    provenance = QueryProvenance()
    max_reached = 0
    for row in prov_rows:
        svc = row["svc"]
        max_reached = max(max_reached, int(row["depth"]))
        key = f"chain:{svc}->{service_name}"
        for evt in row.get("edge_events") or []:
            if evt:
                provenance.add(key, [str(evt)])

    if impact is None:
        answer = BlastRadius(seed_service=service_name)
        return QueryResult(value=answer, provenance=provenance)

    services = sorted(s for s in (impact["services"] or []) if s and s != service_name)
    answer = BlastRadius(
        seed_service=service_name,
        affected_services=services,
        affected_people=sorted(p for p in (impact["people"] or []) if p),
        affected_decisions=sorted(d for d in (impact["decisions"] or []) if d),
        max_depth_reached=max_reached,
    )
    return QueryResult(value=answer, provenance=provenance)
