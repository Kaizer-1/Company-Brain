# ADR 0002 — Neo4j as Graph Database

## Status

Accepted

## Context

The 4 killer queries all require multi-hop traversal over heterogeneous node types. The multi-hop ownership query follows a chain: Decision → deprecated System → dependent Service → owner Person. The blast radius query requires reachability from a seed node across mixed edge types. The temporal contradiction query needs to compare two time-windowed sets of decision nodes and find logical opposites — which requires knowing the topology of the decision graph.

The central architectural question is whether a dedicated graph database is justified, or whether Postgres (already in the stack for pgvector) could handle graph queries via recursive CTEs, eliminating a second database and its operational overhead.

## Decision

Neo4j 5.x community edition with the APOC plugin, over Postgres recursive CTEs and ArangoDB.

## Alternatives Considered

### Option A — Postgres with recursive CTEs

**What it is**: Model the graph as adjacency tables (`nodes`, `edges`) in Postgres and express multi-hop queries with `WITH RECURSIVE` CTEs.

**Pros**:
- Eliminates a second database — simpler Docker Compose, fewer moving parts, one backup strategy
- SQL is universally understood; Cypher is a niche language
- Postgres with good indexes handles small graphs (< ~1M edges) adequately

**Cons**:
- Multi-hop traversal over heterogeneous types (Service, Decision, Person on the same hop path) requires deeply nested CTEs with multiple `UNION ALL` branches — the blast-radius query would be 40+ lines of recursive SQL for what Cypher expresses in 3
- Postgres's query planner is not designed for graph traversal; each hop is effectively a join, and the plan degrades at 3+ hops even with covering indexes
- No native support for graph algorithms (shortest path, degree centrality, community detection) that we will want in Phase 3. Adding these means either implementing them in application code or installing AGE (Apache Graph Extension), which is less mature than Neo4j
- Temporal edge support (edges with `valid_from`/`valid_until`) is awkward in adjacency tables and has no query-level syntax support

**Verdict**: Would work at demo scale. Would be unmaintainable at 3+ hop queries and insufficient for Phase 3 algorithm queries.

### Option B — ArangoDB

**What it is**: A multi-model database (document + graph) with AQL (ArangoDB Query Language).

**Pros**:
- Multi-model: documents and graphs in one system; no separate Postgres needed (though we still need pgvector)
- AQL is expressive; traversal syntax is similar to Cypher
- Open source, self-hostable

**Cons**:
- Much smaller community than Neo4j — fewer Stack Overflow answers, fewer tutorials, fewer third-party integrations
- Python driver is less mature and less actively maintained than the official Neo4j driver
- APOC equivalent does not exist; temporal functions would need custom implementation
- Weaker interview recognition: Neo4j is the industry-standard graph database that engineers know; ArangoDB proficiency is niche

### Option C — Neo4j 5.x community (chosen)

**What it is**: Purpose-built graph database with Cypher query language, native graph storage (pointer-based adjacency), and the APOC standard library.

**Pros**:
- Traversal is O(1) per hop (pointer follow in native graph storage, no index lookup). The blast-radius and ownership queries are simple MATCH patterns; the Cypher for the 3-hop ownership query is 5 lines
- APOC provides temporal functions (`apoc.date.*`, temporal procedures) needed for Phase 3B contradiction detection
- Neo4j 5.x supports vector indexes (experimental) for potential Phase 3D hybrid integration
- Industry standard — Neo4j knowledge is directly marketable
- Async Python driver (`neo4j>=5.x`) is well-maintained and ships its own type stubs

**Cons**:
- Second database to operate — adds to Docker Compose complexity, increases cold-start time (~30s for Neo4j to become ready vs ~5s for Postgres)
- Cypher is a domain-specific language; team members unfamiliar with it have a learning curve
- Community edition has some limitations (no clustering, no multi-database in some versions) — not relevant at demo scale

## Consequences

**Enables**: Expressive multi-hop queries in 3–10 lines of Cypher. Native shortest-path and reachability algorithms for Phase 3. Temporal edge modeling for Phase 3B. Direct mapping of the 4 killer queries to single MATCH clauses.

**Constrains**: Two databases to operate and monitor. Cypher knowledge required for all query development. Data must be written to both Neo4j (structure) and Postgres (relational + vector) — the write path is more complex.

**Locked into**: The Cypher query model and Neo4j's graph schema conventions. Migrating to a different graph DB later would require rewriting all queries.

**At larger scale / in production**: Neo4j Enterprise (paid) adds clustering, multi-database isolation per tenant, and advanced security. At 10M+ nodes or multi-tenant requirements, the community edition is insufficient. An alternative at scale is Amazon Neptune (managed, no ops), though it uses Gremlin/OpenCypher rather than APOC Cypher — some Phase 3 queries would need rewriting.

## Interview Defense

> "Neo4j earns its complexity cost specifically on multi-hop traversal. The ownership query — find the person who owns the service that depends on the system deprecated by a decision — is one MATCH clause in Cypher and 40 lines of recursive SQL in Postgres. At demo scale, Postgres would technically work, but the query code would be unreadable, and we'd have no path to graph algorithms in Phase 3. The cost is a second database and a Cypher learning curve, both of which are bounded."
