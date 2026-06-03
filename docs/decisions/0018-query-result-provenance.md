# ADR 0018 — Query result provenance as a structural type

## Status

Accepted

## Context

The project's thesis is that a graph answers questions RAG cannot *and shows its work*: every
answer ties back to the source events that justify it. If provenance were an optional field
some queries forgot to populate, the demo's central claim ("grounded answer with provenance")
would be unverifiable and the eval could not check that an answer's evidence actually exists in
Postgres. The four killer queries return heterogeneous shapes (an owner, a list of
contradictions, a blast-radius set, a timeline), so we need one uniform envelope that carries
both the answer and its evidence.

## Decision

Every query returns `QueryResult[T]` — a frozen generic dataclass with `value: T` and
`provenance: QueryProvenance`. `QueryProvenance` maps a stable element key (e.g.
`"edge:DEPRECATES:D-0006->legacy-auth"`, `"node:Decision:D-0006"`) to the list of Postgres
event UUIDs that asserted it, and exposes `all_event_ids` (the flat union) for validation and
demo display. Provenance is **not optional**: every KQ populates it from the `source_event_id`
on each traversed edge and the `source_event_ids` on each node, and the integration eval
validates every id against the `events` table.

## Alternatives Considered

### Option A — return bare data, add provenance later

**Pros**: simplest signatures now.

**Cons**: provenance bolted on after the fact is always incomplete; the eval can't validate
grounding; defeats the project thesis. Rejected.

### Option B — `QueryResult[T]` with a structured `QueryProvenance` *(chosen)*

**Pros**: one envelope for all four queries; keyed provenance lets the demo highlight *which*
edge each event justifies; `all_event_ids` makes validation trivial; generic `T` keeps each
query's answer strongly typed.

**Cons**: every query must thread `source_event_id` through its Cypher `RETURN` and build the
provenance map — a little boilerplate per query.

### Option C — a free-form `dict[str, Any]` provenance blob

**Pros**: flexible.

**Cons**: `Any` violates the project's type discipline; no compile-time guarantee provenance is
populated; serialisation shape drifts per query. Rejected.

## Consequences

**Enables**: a uniform JSON shape across the FastAPI endpoints; the eval's provenance-validity
check; the Phase-4 agent can render "this answer is justified by events X, Y, Z" mechanically.

**Constrains**: every new query must populate provenance — enforced by the return type, not a
convention.

**At larger scale / in production**: provenance keys could reference an immutable event store
with content hashes; large result sets might paginate provenance separately from values.

## Interview Defense

> "Provenance is a structural part of every result type, not an optional field — `QueryResult[T]`
> with `value` and a keyed `QueryProvenance` of source-event IDs. We made it non-optional
> because the whole point is grounded answers, and our eval literally checks that every event ID
> behind an answer exists in Postgres. The cost is a little boilerplate threading `source_event_id`
> through each query; the payoff is the demo can show exactly which event justified which edge."
