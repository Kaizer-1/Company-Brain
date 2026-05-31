# Company Brain

A self-updating knowledge graph that ingests company intelligence — Slack-style messages, architecture decisions, and meeting notes — and answers complex multi-hop questions with full provenance. Built as a portfolio piece demonstrating graph database design, async Python, and the limits of pure RAG on structured reasoning tasks.

## What it does

Company Brain extracts entities (services, decisions, people, systems) and their relationships from unstructured company knowledge. It stores structure in a Neo4j graph and semantics in Postgres + pgvector, then exposes an agent that routes queries to the right store.

**Demo queries (things pure RAG cannot answer):**
- *Who owns the service that depends on the system deprecated by Decision X?* — multi-hop ownership
- *Which currently-active decisions are contradicted by last month's discussions?* — temporal contradiction
- *If the payments service fails, what breaks?* — blast radius
- *What has changed about the auth system this quarter, and who approved each change?* — provenance

## Quickstart

```bash
cp .env.example .env
docker compose up --build
curl localhost:8000/health
# → {"status":"ok","neo4j":"connected","postgres":"connected"}
```

## Development

```bash
# Install uv: https://docs.astral.sh/uv/getting-started/installation/
uv sync --dev           # creates .venv, installs all deps + dev extras
uv run pytest           # run tests (no live DB required)
uv run mypy backend/    # type-check in strict mode
pre-commit install      # wire up ruff + mypy hooks
pre-commit run --all-files
```

## Architecture

- **Graph DB**: Neo4j 5.x — multi-hop traversal, typed relationships, temporal edges
- **Vector + Relational DB**: Postgres 16 + pgvector — embeddings co-located with metadata for single-query hybrid search
- **API**: FastAPI + Pydantic v2 — async, typed, auto-documented
- **Agent** (Phase 4A): routes query components to graph traversal or vector search

See [docs/architecture/overview.md](docs/architecture/overview.md) and the [decision log](docs/decisions/).

## Documentation

| Path | Purpose |
|------|---------|
| [CLAUDE.md](CLAUDE.md) | Persistent session context for Claude Code |
| [HANDOFF.md](HANDOFF.md) | Latest subphase state |
| [docs/decisions/](docs/decisions/) | Architecture Decision Records |
| [docs/concepts/](docs/concepts/) | Technical concept explainers |
| [docs/architecture/overview.md](docs/architecture/overview.md) | System architecture |
| [docs/interview-prep/](docs/interview-prep/) | Interview Q&A per phase |

## Limitations and Future Work

This is a **synthetic-data portfolio project**, not a production system. Named limitations:

- **Synthetic data only** — all entities and messages are generated; no real company data is ingested
- **Closed entity types** — the schema is fixed; no runtime schema evolution
- **Single-tenant** — one organisation model; no row-level isolation between tenants
- **No production auth** — no JWT, OAuth, or access control beyond Docker network
- **No PII handling** — no data residency, encryption at rest, or anonymisation pipeline
- **Demo scale** — designed for ~10k nodes; not benchmarked or optimised for enterprise scale

These are deliberate scope decisions. The architecture section of each ADR notes what would change to remove each limitation.
