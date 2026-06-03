"""KQ1 — multi-hop ownership (Phase 3B).

> Who owns the service that depends on the system deprecated by Decision X?

Cypher pattern (resolved view; edges already projected onto canonical winners by
``resolution.projection``):

    (d:Decision {id})-[:DEPRECATES]->(sys:System)
    (svc:Service)-[:DEPENDS_ON]->(sys)
    (svc)-[:OWNED_BY]->(owner)            # owner is a Person or a Team
    (owner)<-[:MEMBER_OF]-(member:Person) # if owner is a Team, expand to its people

Worked example: ``find_chain_owner(decision_id="D-0006")`` returns Diego Ramirez via
``D-0006 → legacy-auth → payments-api → payments → diego-ramirez`` (a 4-hop chain), plus the
secondary dependent ``subscriptions-service`` owned by growth/priya-nair. Provenance is the set
of events that asserted each edge in every chain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.queries.result_types import QueryProvenance, QueryResult

if TYPE_CHECKING:
    from neo4j import AsyncDriver

# Read-only; ``as_of`` is accepted for signature symmetry with the temporal queries but KQ1 is
# not time-windowed.
_QUERY = """
MATCH (d:Decision {id: $decision_id})-[dep:DEPRECATES]->(sys:System)
WHERE coalesce(d.status,'active') <> 'merged' AND coalesce(sys.status,'active') <> 'merged'
MATCH (svc:Service)-[r1:DEPENDS_ON]->(sys)
WHERE coalesce(svc.status,'active') <> 'merged'
MATCH (svc)-[r2:OWNED_BY]->(owner)
WHERE coalesce(owner.status,'active') <> 'merged'
OPTIONAL MATCH (owner)<-[r3:MEMBER_OF]-(member:Person)
WHERE owner:Team AND coalesce(member.status,'active') <> 'merged'
RETURN d.title AS decision_title,
       sys.canonical_name AS system,
       svc.canonical_name AS service,
       labels(owner)[0] AS owner_type,
       coalesce(owner.canonical_name, owner.canonical_id) AS owner_id,
       owner.display_name AS owner_name,
       member.canonical_id AS member_id,
       member.display_name AS member_name,
       dep.source_event_id AS dep_evt,
       r1.source_event_id AS dependson_evt,
       r2.source_event_id AS owned_evt,
       r3.source_event_id AS member_evt
"""


class OwnershipChain(BaseModel):
    """One Decision→System→Service→owner(→person) path that answers KQ1."""

    deprecated_system: str
    dependent_service: str
    owner_type: str  # "Person" | "Team"
    owner_id: str
    person_id: str | None = None
    person_display_name: str | None = None
    nodes: list[str] = Field(default_factory=list)

    @property
    def hops(self) -> int:
        """Number of edges in the chain (4 for the canonical team-owned path)."""
        return max(len(self.nodes) - 1, 0)


class ChainOwnerAnswer(BaseModel):
    """KQ1's answer: the people who own a service depending on the deprecated system."""

    decision_id: str
    decision_title: str | None = None
    deprecated_systems: list[str] = Field(default_factory=list)
    owner_people: list[str] = Field(default_factory=list)
    chains: list[OwnershipChain] = Field(default_factory=list)


async def find_chain_owner(
    driver: AsyncDriver,
    *,
    decision_id: str,
    as_of: object | None = None,  # noqa: ARG001 - symmetry with temporal queries; KQ1 is not windowed
) -> QueryResult[ChainOwnerAnswer]:
    """Return the Person(s) who own the Service(s) depending on the System deprecated by X.

    A Team owner is expanded to its members so the answer is always at the Person granularity
    KQ1 asks for. The full chain is returned in each result's ``nodes`` for the demo, and every
    edge's source event is recorded in provenance.
    """
    async with driver.session() as session:
        result = await session.run(_QUERY, decision_id=decision_id)
        records = [record.data() async for record in result]

    provenance = QueryProvenance()
    chains: list[OwnershipChain] = []
    systems: set[str] = set()
    people: set[str] = set()
    title: str | None = None

    for row in records:
        title = row.get("decision_title") or title
        system = row["system"]
        service = row["service"]
        owner_type = row["owner_type"]
        owner_id = row["owner_id"]
        systems.add(system)

        if owner_type == "Team" and row.get("member_id"):
            person_id = row["member_id"]
            nodes = [decision_id, system, service, owner_id, person_id]
        elif owner_type == "Person":
            person_id = owner_id
            nodes = [decision_id, system, service, person_id]
        else:
            # A Team owner with no resolved members — record the chain to the team, no person.
            person_id = None
            nodes = [decision_id, system, service, owner_id]

        if person_id is not None:
            people.add(person_id)

        chains.append(
            OwnershipChain(
                deprecated_system=system,
                dependent_service=service,
                owner_type=owner_type,
                owner_id=owner_id,
                person_id=person_id,
                person_display_name=row.get("member_name") or row.get("owner_name"),
                nodes=nodes,
            )
        )

        edge_key = f"chain:{system}->{service}->{owner_id}"
        for evt in (
            row.get("dep_evt"),
            row.get("dependson_evt"),
            row.get("owned_evt"),
            row.get("member_evt"),
        ):
            if evt:
                provenance.add(edge_key, [str(evt)])

    answer = ChainOwnerAnswer(
        decision_id=decision_id,
        decision_title=title,
        deprecated_systems=sorted(systems),
        owner_people=sorted(people),
        chains=chains,
    )
    return QueryResult(value=answer, provenance=provenance)
