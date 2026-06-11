# ADR 0033 — A Single In-Process Writer Lock for Concurrency

## Status

Accepted

## Context

Reconciliation mutates a shared graph across several stages: resolution reads the canonical nodes of
a type and writes `MERGE_INTO` edges; consolidation tombstones decisions; projection copies edges.
Two ingestions touching overlapping subgraphs at the same time could interleave and corrupt that
state (e.g. resolve a node against a set another ingestion is mid-merge on). The demo, however, is a
single user injecting one event at a time — there is no real concurrency to exploit, and a
distributed lock or per-node locking would be machinery without a workload to justify it.

## Decision

**Serialise all ingestions with one process-wide `asyncio.Lock`.** The `POST /api/events` handler
acquires the lock before reconciling and releases it after; a second request waits up to 30s, then
returns **503**. The reconciliation itself is awaited inside the handler (no fire-and-forget 202) so
the user sees the result.

## Alternatives Considered

### Option A — Single asyncio.Lock (chosen)

**What it is**: one in-process lock; ingestions run one at a time.

**Pros**: trivially correct (no interleaving possible); matches the single-writer demo reality; the
503-on-timeout path is honest backpressure; zero new infrastructure.

**Cons**: no parallelism — two ingestions on *disjoint* subgraphs that could safely run together are
serialised; the lock is per-process, so it does not coordinate across replicas.

### Option B — Per-canonical-node locking

**What it is**: lock the specific canonical nodes an event touches; disjoint ingestions parallelise.

**Pros**: real throughput; the correct production shape.

**Cons**: substantial — you need a lock manager, deadlock avoidance across the node set, and a way to
know an event's node set *before* extraction. Pure overhead for a single-user demo.

### Option C — No lock, rely on MERGE idempotency

**What it is**: let ingestions race; trust MERGE to converge.

**Pros**: simplest code.

**Cons**: MERGE makes *writes* idempotent but does not make *read-modify-write* sequences (resolve →
merge → project) atomic; a race can still produce a wrong merge. Rejected.

## Consequences

**Enables**: a correct, simple concurrency story for the demo; predictable 503 backpressure under
accidental concurrent submits.

**Constrains**: throughput is one ingestion at a time; the lock does not span processes, so running
multiple backend replicas would need an external lock (Postgres advisory lock / Redis).

**Locked into**: synchronous, awaited reconciliation in the request handler (the visible-result
requirement), bounded by the 30s lock-wait timeout.

**At larger scale / in production**: replace with per-canonical-node locking for intra-process
parallelism, and a Postgres advisory lock or a partitioned single-writer-per-partition model
(à la Kafka) for cross-replica coordination and ordered, exactly-once processing.

## Interview Defense

> "One asyncio lock — ingestions run one at a time. It's correct because reconciliation is a
> read-modify-write across the graph that MERGE alone doesn't make atomic, and it's sufficient
> because the demo has one writer. The honest cost is zero parallelism and no cross-replica
> coordination. In production I'd lock per canonical node so disjoint ingestions parallelise, and
> use a Postgres advisory lock or Kafka-style partitioning across replicas."
