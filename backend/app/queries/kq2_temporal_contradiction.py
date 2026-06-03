"""KQ2 — temporal contradiction (Phase 3B).

> Which currently-active decisions are contradicted by discussions in the last month?

Cypher pattern (resolved view):

    (m:Message)-[:CONTRADICTS]->(d:Decision)
    WHERE d.status = 'active' AND m.created_at IN [as_of - window, as_of]

The ``CONTRADICTS`` edges and ``Message`` nodes are populated by the Phase-3B contradiction pass
(``app.contradiction``); without it this query has no data (ADR 0019). Windows evaluate against
``as_of`` (default ``REFERENCE_NOW``) so "last month" lands on the corpus's planted tail.

Worked example: ``find_contradictions(window=30d)`` returns ``D-0005`` (still active — no
superseding decision), contradicted by the ~22-day-old ``#auth-migration`` thread. Provenance
includes the decision's node events and each contradicting message's ``CONTRADICTS`` edge event.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.queries.result_types import QueryProvenance, QueryResult
from app.queries.temporal import window_bounds

if TYPE_CHECKING:
    from datetime import datetime

    from neo4j import AsyncDriver

_QUERY = """
MATCH (m:Message)-[c:CONTRADICTS]->(d:Decision)
WHERE coalesce(d.status,'active') = 'active'
  AND coalesce(m.status,'active') <> 'merged'
  AND m.created_at >= datetime($start) AND m.created_at <= datetime($end)
RETURN d.id AS decision_id, d.title AS decision_title,
       collect({message_id: m.id, said_at: toString(m.created_at),
                confidence: c.confidence, evt: c.source_event_id,
                node_events: m.source_event_ids}) AS messages,
       d.source_event_ids AS decision_events
ORDER BY size(messages) DESC
"""


class ContradictingMessage(BaseModel):
    """One message that contradicts a decision, with when it was said and the LLM confidence."""

    message_id: str
    said_at: str | None = None
    confidence: float | None = None


class Contradiction(BaseModel):
    """An active decision and the recent messages that contradict it."""

    decision_id: str
    decision_title: str | None = None
    messages: list[ContradictingMessage] = Field(default_factory=list)


async def find_contradictions(
    driver: AsyncDriver,
    *,
    window: timedelta = timedelta(days=30),
    as_of: datetime | None = None,
) -> QueryResult[list[Contradiction]]:
    """Return active decisions contradicted by messages within ``window`` of ``as_of``."""
    start, end = window_bounds(as_of, window)
    async with driver.session() as session:
        result = await session.run(_QUERY, start=start.isoformat(), end=end.isoformat())
        records = [record.data() async for record in result]

    provenance = QueryProvenance()
    contradictions: list[Contradiction] = []
    for row in records:
        decision_id = row["decision_id"]
        messages = [
            ContradictingMessage(
                message_id=m["message_id"],
                said_at=m.get("said_at"),
                confidence=m.get("confidence"),
            )
            for m in row["messages"]
        ]
        contradictions.append(
            Contradiction(
                decision_id=decision_id,
                decision_title=row.get("decision_title"),
                messages=messages,
            )
        )
        node_key = f"node:Decision:{decision_id}"
        for evt in row.get("decision_events") or []:
            provenance.add(node_key, [str(evt)])
        for m in row["messages"]:
            edge_key = f"edge:CONTRADICTS:{m['message_id']}->{decision_id}"
            if m.get("evt"):
                provenance.add(edge_key, [str(m["evt"])])
            for evt in m.get("node_events") or []:
                provenance.add(edge_key, [str(evt)])

    return QueryResult(value=contradictions, provenance=provenance)
