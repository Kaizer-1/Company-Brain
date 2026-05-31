# What Is a Knowledge Graph?

A knowledge graph is a data model that represents information as a network of **nodes** (entities) and **edges** (relationships), both of which can carry typed properties. The defining feature is that relationships are first-class citizens stored at the data layer — not derived at query time via JOINs the way relational databases work.

## Nodes, Edges, and Properties

A **node** represents a real-world entity: a Service, a Person, a Decision, a System. Every node has:
- One or more **labels** — the entity type(s): `:Service`, `:Person`, `:Decision`
- **Properties** — key-value pairs on the node: `{name: "payments-api", language: "Go", owner_team: "payments"}`

An **edge** (or relationship) connects two nodes and represents a typed connection:
```
(:Service {name: "checkout"})-[:DEPENDS_ON]->(:Service {name: "payments-api"})
(:Person {name: "Alice"})-[:OWNS]->(:Service {name: "payments-api"})
```

Edges are **directed** (they have a source and a target) and can carry properties too:
```
(:Person)-[:APPROVED_BY {timestamp: "2025-01-15"}]->(:Decision)
```

This means "Person approved Decision, and that approval happened on 2025-01-15." The timestamp is a property of the relationship itself, not of either node.

## How It Differs from a Relational Schema

In a relational database, a "relationship" between two entities is an implicit encoding in foreign keys:

```sql
CREATE TABLE service_dependencies (
    from_service_id uuid REFERENCES services(id),
    to_service_id   uuid REFERENCES services(id)
);
```

To follow that relationship at query time, you write a JOIN. To follow two hops ("find services that depend on services that depend on payments"), you write two JOINs — or a recursive CTE. Three hops: three JOINs or a deeper recursion. Each JOIN is computed at query time by scanning an index, and the query planner has no way to know that following the dependency chain is your primary access pattern.

In a graph database, the adjacency is stored directly in the node's record as a pointer to its connected edges. Following an edge from one node to the next is **O(1)** — a pointer dereference, not an index lookup. A 3-hop traversal is three pointer follows, not three table scans. The query planner traverses the *topology* of the data, not the *shape* of the storage.

In Cypher (Neo4j's query language), the three-hop ownership query is:
```cypher
MATCH (d:Decision {id: $decision_id})
      -[:DEPRECATED]->(sys:System)
      <-[:DEPENDS_ON]-(svc:Service)
      <-[:OWNS]-(p:Person)
RETURN p.name, svc.name, sys.name
```

The equivalent in SQL, written as a recursive CTE, would be 40+ lines. More importantly, the SQL version obscures the *intent* of the query — a graph reader can see the traversal path immediately; a SQL reader has to parse the JOIN conditions.

## When Graphs Win vs. Lose

**Graphs win when:**
- Data is deeply connected and queries traverse multiple hops with diverse relationship types
- Relationships are themselves interesting — they have properties, directions, and temporal context
- Schema evolves by adding new relationship types, not by altering tables
- You need graph algorithms: shortest path, cycle detection, community detection, centrality
- The traversal pattern is your primary access pattern, not an occasional analytical query

**Graphs lose when:**
- You need aggregation over large datasets: `SUM`, `GROUP BY`, `WINDOW` — relational is orders of magnitude faster
- Data is tabular with few connections (time-series logs, financial ledgers, IoT sensor data)
- Your query workload is overwhelmingly key-value lookups: "fetch entity by ID" is faster in Postgres with a B-tree index than in Neo4j
- You need full-text search on content — use a search engine or pgvector, not a graph DB

Company Brain's workload lives firmly in the "graphs win" column. The 4 killer queries are all graph traversals. Aggregation exists but is secondary (e.g., "how many services are affected" is computed after the graph traversal, not as the primary operation).

## Preview of Company Brain's Schema

> **Note**: this section is an early teaching *preview*. The schema was finalised in Phase 1B and locked in `CLAUDE.md` — see `docs/design/graph-schema.md` and [ADR 0007](../decisions/0007-graph-schema-v1.md) for the authoritative version. A few names changed on the way (the locked schema uses `OWNED_BY` not `OWNS`, and `DEPRECATES` (Decision → System) not `DEPRECATED_BY`), exactly as the "backwards-designed from the queries" process below predicted.

### Node types

| Label | Represents | Key properties |
|-------|-----------|----------------|
| `Service` | A deployed software service | `name`, `language`, `tier` |
| `System` | A higher-level system/platform | `name`, `status` (active/deprecated) |
| `Person` | An engineer or stakeholder | `name`, `email`, `team` |
| `Team` | An engineering team | `name`, `slack_channel` |
| `Decision` | An architecture decision record | `id`, `title`, `status`, `date` |
| `Message` | A Slack-style message | `id`, `content`, `channel`, `timestamp` |

### Relationship types

| Relationship | Direction | Properties | Enables |
|-------------|-----------|------------|---------|
| `DEPENDS_ON` | Service → Service | `since` | Blast radius, ownership chain |
| `OWNS` | Person/Team → Service | `since` | Ownership queries |
| `DEPRECATED_BY` | System → Decision | `date` | Multi-hop ownership query |
| `CONTRADICTS` | Decision → Decision | `detected_at` | Temporal contradiction query |
| `APPROVED_BY` | Decision → Person | `timestamp` | Provenance query |
| `AUTHORED` | Person → Message/Decision | `timestamp` | Attribution |
| `MEMBER_OF` | Person → Team | `since` | Team-based filtering |

### Schema is backwards-designed from the queries

This schema was not designed generically. Each relationship type exists because at least one of the 4 killer queries requires it. `DEPRECATED_BY` exists because the multi-hop ownership query traverses it. `CONTRADICTS` exists because the temporal contradiction query needs it as an explicit, computed edge. The schema design process in Phase 1B will start by writing each killer query in Cypher and working backwards to the node/edge types needed to answer it.
