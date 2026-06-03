"""KQ4 — provenance + change tracking (Phase 3B).

> What changed about the auth system in the last quarter, and who approved each change?

Cypher pattern (resolved view):

    (d:Decision)-[:ABOUT|DEPRECATES]->(target {canonical_name})
    WHERE d.valid_from IN [as_of - window, as_of]
    (d)-[:APPROVED_BY]->(approver) ; (d)-[:SUPERSEDES]->(older)

Worked example: ``track_changes(target_name="auth-service", window=90d)`` returns D-0010, D-0008,
D-0007, D-0006 (newest first) with their approvers, and D-0010's supersession of D-0004.
Requires the temporal enricher to have populated ``valid_from``/``status``/``SUPERSEDES``.
Provenance includes each decision's node events plus the APPROVED_BY/SUPERSEDES edge events.
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
MATCH (target {canonical_name: $target_name})
WHERE (target:System OR target:Service) AND coalesce(target.status,'active') <> 'merged'
MATCH (d:Decision)-[ab:ABOUT|DEPRECATES]->(target)
WHERE coalesce(d.status,'active') <> 'merged'
  AND d.valid_from IS NOT NULL
  AND d.valid_from >= datetime($start) AND d.valid_from <= datetime($end)
OPTIONAL MATCH (d)-[appr:APPROVED_BY]->(p:Person) WHERE coalesce(p.status,'active') <> 'merged'
OPTIONAL MATCH (d)-[sup:SUPERSEDES]->(older:Decision)
RETURN d.id AS decision_id, d.title AS title, d.status AS status,
       toString(d.valid_from) AS valid_from,
       collect(DISTINCT p.canonical_id) AS approvers,
       collect(DISTINCT older.id) AS supersedes,
       d.source_event_ids AS node_events,
       collect(DISTINCT appr.source_event_id) AS appr_events,
       collect(DISTINCT sup.source_event_id) AS sup_events
ORDER BY valid_from DESC
"""


class DecisionChange(BaseModel):
    """One decision in the change timeline, with approvers and any supersession."""

    decision_id: str
    title: str | None = None
    status: str | None = None
    valid_from: str | None = None
    approvers: list[str] = Field(default_factory=list)
    supersedes: list[str] = Field(default_factory=list)


class ChangeTimeline(BaseModel):
    """KQ4's answer: the change timeline for a target, newest first."""

    target: str
    changes: list[DecisionChange] = Field(default_factory=list)


async def track_changes(
    driver: AsyncDriver,
    *,
    target_name: str,
    window: timedelta = timedelta(days=90),
    as_of: datetime | None = None,
) -> QueryResult[ChangeTimeline]:
    """Return decisions about ``target_name`` within ``window`` of ``as_of``, with approvers."""
    start, end = window_bounds(as_of, window)
    async with driver.session() as session:
        result = await session.run(_QUERY, target_name=target_name, start=start.isoformat(), end=end.isoformat())
        records = [record.data() async for record in result]

    provenance = QueryProvenance()
    changes: list[DecisionChange] = []
    for row in records:
        decision_id = row["decision_id"]
        changes.append(
            DecisionChange(
                decision_id=decision_id,
                title=row.get("title"),
                status=row.get("status"),
                valid_from=row.get("valid_from"),
                approvers=sorted(a for a in (row.get("approvers") or []) if a),
                supersedes=sorted(s for s in (row.get("supersedes") or []) if s),
            )
        )
        node_key = f"node:Decision:{decision_id}"
        for evt in row.get("node_events") or []:
            provenance.add(node_key, [str(evt)])
        for evt in row.get("appr_events") or []:
            if evt:
                provenance.add(f"edge:APPROVED_BY:{decision_id}", [str(evt)])
        for evt in row.get("sup_events") or []:
            if evt:
                provenance.add(f"edge:SUPERSEDES:{decision_id}", [str(evt)])

    return QueryResult(value=ChangeTimeline(target=target_name, changes=changes), provenance=provenance)
