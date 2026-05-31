# Phase 1A Interview Readiness

This document covers the technical decisions and concepts introduced in Phase 1A. It is written in Q&A format to make it easy to use as mock interview prep. Every answer here should be deliverable in under 90 seconds verbally.

---

## Q&A

### 1. Why Neo4j over Postgres for the graph layer?

The 4 killer queries all require multi-hop traversal over heterogeneous node types. Postgres can do this with recursive CTEs, but the query code becomes unmaintainable at 3+ hops and the query planner degrades because Postgres is not optimised for graph traversal — each hop is effectively a join against a potentially large table.

Neo4j's storage model keeps adjacency as direct pointers: following an edge from one node to another is O(1), not O(log n). The multi-hop ownership query is one MATCH pattern in Cypher; the equivalent recursive CTE would be 40+ lines. The APOC library also provides temporal functions critical for Phase 3B contradiction detection, which would require custom implementation on Postgres.

The cost is a second database to operate (Neo4j adds ~30s to cold start and more memory). That cost is justified because the query expressiveness difference is the central technical point of the project.

---

### 2. Why pgvector over Pinecone or Weaviate?

The core reason is co-location with relational data. Our most interesting queries combine semantic similarity with relational filters: "find messages semantically similar to X authored by the payments team in Q3." With pgvector, that is one SQL query using the `<=>` cosine distance operator plus a WHERE clause. With Pinecone or Weaviate, it is two round trips plus application-level join logic — more code, more latency, more failure modes.

At demo scale (<100k vectors), pgvector with HNSW delivers comparable performance to dedicated systems (>95% recall, <10ms). The trade-off is that pgvector cannot scale vector search independently of Postgres, but we're explicitly outside the scale threshold (~10M vectors or >1000 QPS) where that matters.

---

### 3. What does mypy strict mode catch that regular mypy doesn't?

Strict mode enables several checks that regular mypy leaves off:

- `--disallow-untyped-defs`: every function must have annotated parameters and return type — no silently-untyped code paths
- `--disallow-any-generics`: `list`, `dict`, `tuple` must be parameterised (`list[str]`, `dict[str, int]`) — no bare generic containers that hide type errors
- `--warn-return-any`: cannot silently return `Any` from a typed function
- `--strict-equality`: catches comparisons that can never be true given the types (e.g., comparing `int` with `str`)
- `--no-implicit-reexport`: names imported in a module are not re-exported unless explicitly declared — prevents accidental public API

Collectively, strict mode catches the class of bugs where runtime behaviour diverges from programmer intent — especially important in async code where error propagation is less obvious, and in ingestion pipelines where silent coercion (`"42"` passing as an `int`) could corrupt the graph.

---

### 4. FastAPI vs Flask — when would you choose each?

FastAPI for async-first, type-annotated, API-centric applications — especially when the primary I/O is database or external HTTP calls, and when auto-generated OpenAPI docs add value. The decision factor in this project was async: both the Neo4j driver and SQLAlchemy 2.x require an asyncio event loop. Running them in Flask would require a thread pool executor or Flask's experimental async support, both of which are worse than using a natively async framework.

Flask for simpler synchronous applications, server-side HTML rendering (with Jinja2), or when the Flask extension ecosystem is a strong requirement. Flask's simplicity is a genuine advantage for small tools and internal scripts.

---

### 5. What are the trade-offs of a monorepo?

**Pros**: Atomic commits across all layers (a schema change in backend + its reflection in frontend + the relevant ADR can be one commit). Single CI pipeline. Zero overhead for internal package imports. Docs are always adjacent to the code they document.

**Cons**: CI runs the full test suite on every push regardless of which component changed (mitigated by path filters). Cannot grant partial repo access to contractors without workarounds. All components share the same Python version pin. As the repo grows, a single `pyproject.toml` starts mixing concerns.

For this project, with one developer and tight coupling between backend, frontend, and docs, the monorepo decision is clear. The natural evolution point is introducing uv workspaces when backend and frontend genuinely have different dependency graphs and different release cadences.

---

### 6. Why do Docker healthchecks matter?

`depends_on: condition: service_healthy` in docker-compose only waits for the container to *start*, not for the service inside to be *ready*. Neo4j and Postgres both take 10–40 seconds after the container starts before they accept connections.

Without healthchecks, the backend container starts immediately, tries to connect to Neo4j and Postgres, fails, and crashes — or silently starts with broken DB connections. Healthchecks define a probe command that must succeed before dependent services start. They also make `docker ps` useful in operations: you can see at a glance which services are actually serving traffic vs. starting up vs. unhealthy.

In our Compose file, the postgres healthcheck uses `pg_isready`, which is the correct utility (it tests the actual Postgres listener, not just a TCP port). The Neo4j healthcheck uses `wget` to probe the HTTP browser interface on port 7474.

---

### 7. What's the difference between uv and pip/poetry?

**pip** has no lockfile and a weak dependency resolver. Repeatable installs require manual pinning or pip-tools (`pip-compile`). Managing Python versions requires a separate tool (pyenv).

**Poetry** adds proper lockfile support (`poetry.lock`) and a better resolver, but uses a non-standard `[tool.poetry.dependencies]` table in pyproject.toml (not PEP 621 `[project]`), is notably slow at resolution on large dependency trees, and has a history of resolver edge-case bugs.

**uv** is a Rust-based reimplementation that replaces pip, pip-tools, and virtualenv in a single binary. It is 10–100× faster than pip/Poetry at resolution and installation, uses the standard PEP 621 `[project]` table, generates a `uv.lock` lockfile, and manages virtual environments. `uv sync --dev` installs all deps including dev extras; `uv run <command>` runs in the project's venv without activating it.

---

### 8. What does pgvector actually store, and how does similarity search work?

pgvector adds a `vector(n)` column type to Postgres that stores fixed-width arrays of 32-bit floats. A `vector(1536)` column stores OpenAI `text-embedding-3-small` embeddings; `vector(768)` stores BERT-family embeddings.

Similarity search uses the cosine distance operator `<=>`:
```sql
SELECT id FROM messages ORDER BY embedding <=> $1 LIMIT 10;
```
Where `$1` is the query embedding as a Postgres `vector` literal. Without an index, this is a sequential scan — O(n) comparisons. With an HNSW index, Postgres builds a multilayer graph where each layer connects nodes to their approximate nearest neighbours; queries descend from the top layer, narrowing the candidate set at each level. The result is approximate (not exact) but achieves >95% recall at 10–100× the speed of a brute-force scan.

---

### 9. What does the Neo4j async driver give us vs. raw HTTP?

Neo4j exposes both an HTTP API and the Bolt binary protocol. The official Python driver uses Bolt, which offers:
- **Binary encoding**: Bolt is more compact and faster to serialize/deserialize than JSON
- **Connection pooling**: the driver maintains a pool of persistent TCP connections; each query reuses a connection rather than paying the TCP handshake cost
- **Multiplexed sessions**: multiple logical sessions can share one physical connection
- **Async I/O**: the `AsyncGraphDatabase.driver` wraps Bolt in asyncio; queries do not block the event loop while waiting for Neo4j. This is critical in FastAPI — a request handler that awaits Neo4j and Postgres calls concurrently runs both in parallel rather than sequentially

The `verify_connectivity()` method runs `RETURN 1` through a real session, which exercises the full Bolt connection stack including auth, rather than just probing a TCP port.

---

### 10. What would need to change to add multi-tenancy?

Currently there is a single Neo4j database and a single Postgres schema — all data is implicitly scoped to one organisation. Three isolation models, in increasing strength:

1. **Node-level isolation**: add `org_id` to every Neo4j node and every Postgres row; filter all queries on `org_id`. Simplest to implement, but a misconfigured query is a data leak. Requires application-level discipline on every query.

2. **Database-level isolation**: Neo4j 5.x supports multiple databases per instance; each organisation gets its own Neo4j database. In Postgres, use row-level security (RLS) policies keyed on `org_id` extracted from the JWT claim. Much stronger isolation; Neo4j database-level guarantees no cross-tenant query leakage. Cost: higher memory per tenant.

3. **Instance-level isolation**: one Neo4j instance and one Postgres schema per organisation. Maximum isolation; operationally expensive. For a SaaS product, this is overkill unless compliance requires it.

All three also require a proper auth layer (JWT with org claim, probably OAuth 2.0), which doesn't exist today — named scope limitation.

---

## Key Concepts to Whiteboard

These are the 5 concepts from Phase 1A that you should be able to sketch on a whiteboard in under 5 minutes each:

1. **Graph traversal vs. relational JOIN**: draw two nodes connected by an edge (pointer in memory) vs. two rows connected via a foreign key (index lookup). Label the traversal costs: O(1) pointer follow vs O(log n) B-tree lookup per hop.

2. **Embedding space and cosine similarity**: draw a 2D projection of a high-dimensional embedding space. Plot 3–4 sentence embeddings; show that similar sentences cluster together. Draw the query vector and the nearest-neighbour search. Label the cosine distance formula.

3. **FastAPI lifespan + asyncio event loop**: draw the event loop. Show that when a request handler awaits Neo4j and Postgres calls concurrently (`asyncio.gather`), both I/O operations are in-flight simultaneously — the loop is not blocked. Contrast with Flask where the handler is synchronous.

4. **Docker healthcheck chain**: draw the Compose dependency graph: backend `depends_on` neo4j and postgres `condition: service_healthy`. Show the timeline: container starts → healthcheck probe begins → probe passes → dependent container allowed to start. Explain what breaks without this (race condition on startup).

5. **Pydantic v2 strict mode and coercion**: write `class Entity(BaseModel): model_config = ConfigDict(strict=True)` with an `int` field. Show that `Entity(value="42")` raises a `ValidationError` in strict mode but silently passes in lenient mode. Explain why this matters for ingestion pipelines where an LLM might return `"42"` instead of `42`.
