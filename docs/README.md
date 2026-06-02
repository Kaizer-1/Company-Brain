# Documentation Index

Every file in `docs/` is listed here with a one-line summary. Update this index at the end of every subphase that adds or removes docs.

---

## Architecture

| File | Summary |
|------|---------|
| [architecture/overview.md](architecture/overview.md) | System component diagram, data flow (write path + read path), storage design, phase 1A state |

---

## Architecture Decision Records

ADRs record non-trivial design choices: what we picked, what we rejected, and why. Prior decisions are binding; deviations require a new ADR.

| File | Decision |
|------|---------|
| [decisions/template.md](decisions/template.md) | Template for all ADRs — copy this when writing a new one |
| [decisions/0001-monorepo-structure.md](decisions/0001-monorepo-structure.md) | Single monorepo over polyrepo; justified by tight coupling and one-person team |
| [decisions/0002-neo4j-as-graph-database.md](decisions/0002-neo4j-as-graph-database.md) | Neo4j over Postgres recursive CTEs and ArangoDB; O(1) traversal, APOC temporal functions |
| [decisions/0003-pgvector-vs-dedicated-vector-db.md](decisions/0003-pgvector-vs-dedicated-vector-db.md) | pgvector over Pinecone/Weaviate/Qdrant; co-location enables single-query hybrid search |
| [decisions/0004-fastapi-as-backend.md](decisions/0004-fastapi-as-backend.md) | FastAPI over Flask/Django REST; async-first, Pydantic v2 native, auto-docs |
| [decisions/0005-uv-and-pydantic-v2.md](decisions/0005-uv-and-pydantic-v2.md) | uv over pip/poetry (speed, PEP 621); Pydantic v2 over v1 (performance, strict mode) |
| [decisions/0006-structured-logging.md](decisions/0006-structured-logging.md) | structlog over stdlib+json-logger and loguru; contextvars for request_id; JSON in prod |
| [decisions/0007-graph-schema-v1.md](decisions/0007-graph-schema-v1.md) | Graph schema v1: 6 labels / 9 edges, backward-designed from killer queries; confidence on edges; validity-interval temporal model |
| [decisions/0008-cypher-migration-strategy.md](decisions/0008-cypher-migration-strategy.md) | Homemade Python Cypher migration runner over neo4j-migrations/Liquibase; idempotent via `IF NOT EXISTS` + `_Migration` ledger |
| [decisions/0009-postgres-event-store-design.md](decisions/0009-postgres-event-store-design.md) | Immutable events table, two-table split (events + embeddings), JSONB for metadata, extraction_runs audit, HNSW index |
| [decisions/0010-alembic-migrations.md](decisions/0010-alembic-migrations.md) | Alembic over raw SQL runner / SQLModel create_all / Flyway; async via run_sync; applied at startup |
| [decisions/0011-synthetic-data-strategy.md](decisions/0011-synthetic-data-strategy.md) | Hand-curated adversarial fictional company over Faker / real OSS data / Enron; deterministic; raw events not graph nodes |
| [decisions/0012-extraction-via-openrouter.md](decisions/0012-extraction-via-openrouter.md) | Extraction via OpenRouter (one API, model comparison, cost visibility); JSON-mode over free-form parsing; curated schema over a Pydantic JSON-Schema dump; three models compared |
| [decisions/0013-eval-ground-truth-from-narrative.md](decisions/0013-eval-ground-truth-from-narrative.md) | Eval ground truth derived from `narrative.py` (single source of truth, no drift) rather than a hand-labelled file; named limitations |

---

## Concepts

Technical concept explainers for the hard parts of the stack. Each is written to support interview prep and onboarding.

| File | Summary |
|------|---------|
| [concepts/what-is-a-knowledge-graph.md](concepts/what-is-a-knowledge-graph.md) | Nodes, edges, properties; graph vs. relational; when graphs win/lose; Company Brain schema preview |
| [concepts/pgvector-and-embeddings.md](concepts/pgvector-and-embeddings.md) | What embeddings are, cosine similarity, pgvector index strategy, co-location rationale, scale thresholds |
| [concepts/why-graph-beats-rag-here.md](concepts/why-graph-beats-rag-here.md) | Why each of the 4 killer queries fails with pure RAG; the hybrid graph + vector architecture |

---

## Design

Long-form design documents. UX wireframes and visual artefacts arrive in Phase 4B.

| File | Summary |
|------|---------|
| [design/graph-schema.md](design/graph-schema.md) | The Neo4j graph schema, designed backward from the 4 killer queries: 6 node labels, 9 relationship types, temporal/provenance/identity models, and each killer query written as validated Cypher |
| [design/postgres-schema.md](design/postgres-schema.md) | The Postgres event store schema: three tables, HNSW vs IVFFlat argument, JSONB rationale, provenance contract, index explanations |
| [design/synthetic-company.md](design/synthetic-company.md) | The locked fictional company (Northwind Payments): org, services, systems, decisions, and the adversarial planted cases tied to each killer query |
| [design/extraction-pipeline.md](design/extraction-pipeline.md) | The LLM extraction pipeline + eval harness: structured-output prompting, the curated prompt (verbatim), chunking, validation, provenance, cost telemetry, and the failure-mode taxonomy |

---

## Eval

Generated quality reports. Numbers are honest and reproducible from the deterministic seed.

| File | Summary |
|------|---------|
| [eval/phase-2b-results.md](eval/phase-2b-results.md) | Three-model extraction eval (gpt-4o-mini, claude-3.5-haiku, gemini-2.5-flash-lite): per-type precision/recall/F1, failure-mode counts, worst-case examples, cost, and a hand-written Discussion |

---

## Interview Prep

One doc per subphase. Contains Q&A pairs and key whiteboard concepts for that phase's technical decisions.

| File | Summary |
|------|---------|
| [interview-prep/phase-1a-readiness.md](interview-prep/phase-1a-readiness.md) | 10 Q&A pairs: Neo4j vs Postgres, pgvector vs Pinecone, mypy strict, FastAPI vs Flask, monorepo, Docker healthchecks, uv vs poetry, pgvector internals, Neo4j driver, multi-tenancy |
| [interview-prep/phase-1b-readiness.md](interview-prep/phase-1b-readiness.md) | 10 Q&A pairs: node-type count, confidence on edges, entity resolution honesty, temporal model + limits, KQ2 execution, Cypher migrations vs write-time DDL, dangling edges, models vs migrations, production migration strategy, biggest weakness |
| [interview-prep/phase-1c-readiness.md](interview-prep/phase-1c-readiness.md) | 10 Q&A pairs: event immutability, two-table split, duplicate ingest, JSONB rationale, cross-store provenance, HNSW vs IVFFlat, DTO pattern, extraction_runs utility, re-extraction workflow, schema weaknesses |
| [interview-prep/phase-2a-readiness.md](interview-prep/phase-2a-readiness.md) | 10 Q&A pairs: hand-curated vs Faker/Enron, cases-before-code discipline, KQ1 deprecation chain as events, deterministic seeding, REFERENCE_NOW, ben-smith alias trap, "you wrote the data" critique, user-store as System, look-alike pair, dataset weakness + v2 fix |
| [interview-prep/phase-2b-readiness.md](interview-prep/phase-2b-readiness.md) | 10 Q&A pairs: OpenRouter rationale, extraction pipeline modules, evidence_quote discipline, curated schema vs JSON-Schema dump, ground truth from narrative.py, alias-tolerant matcher, three-model comparison + production pick, F1=0.78 breakdown, max_tokens/chunking trade-off, audit + confidence + provenance honesty |
