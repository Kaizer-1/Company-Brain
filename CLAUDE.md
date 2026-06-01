# Company Brain — Persistent Session Context

> **If you are a fresh Claude Code session, read this entire file before touching any code.**
> Then read `HANDOFF.md`. Then skim relevant ADRs. Only then begin the task.

---

## Project Mission

Company Brain ingests scattered company knowledge — Slack-style messages, architecture decision records, and meeting notes — and builds a self-updating knowledge graph queryable by an AI agent. The goal is a portfolio-grade demo where a natural-language question triggers graph traversal, returns a grounded answer with provenance, and reconciles itself in real time when new events arrive. This is a **synthetic-data portfolio project**, not a production system; that distinction is named, not hidden.

---

## The 4 Killer Queries (LOCKED IN — do not modify in future phases)

These queries are the schema's reason for existing and the demo's centrepiece. Every architectural decision is evaluated against them.

1. **Multi-hop ownership** — Who owns the service that depends on the system deprecated by Decision X?
   *Why RAG fails*: Requires traversing 3+ typed hops (Decision → deprecated System → dependent Service → owner Person). RAG retrieves flat chunks by similarity; it cannot follow edges.

2. **Temporal contradiction** — Which currently-active decisions are contradicted by discussions in the last month?
   *Why RAG fails*: Requires time-filtered set comparison across two document corpora. RAG retrieves nearest neighbours, not logical contradictions, and has no temporal index.

3. **Blast radius** — If the payments service fails, which services, decisions, and people are affected?
   *Why RAG fails*: Requires multi-type graph reachability (Service → Service → Decision → Person). RAG does not model cross-entity structural dependencies; it retrieves semantically similar text.

4. **Provenance + change tracking** — What has changed about the auth system in the last quarter, and who approved each change?
   *Why RAG fails*: Requires temporal edge traversal and approval attribution. RAG retrieves semantically similar text; it cannot reconstruct a change timeline with approvers.

---

## Postgres Schema (LOCKED IN — Phase 1C)

Three tables serve as the immutable raw-event log and the provenance backbone.
Full rationale: `docs/design/postgres-schema.md`. ADR 0009 (design), ADR 0010 (Alembic).

| Table | Role |
|-------|------|
| `events` | Immutable raw-event log. UUID PK referenced by graph nodes' `source_event_ids`. Append-only. |
| `event_embeddings` | One pgvector embedding per event (1536-dim). HNSW index. Separate table to allow re-embedding without mutating events. |
| `extraction_runs` | Audit log for every extraction pipeline invocation. Enables failure detection, re-extraction workflows, model-upgrade auditing. |

**Provenance contract**: graph nodes' `source_event_ids` are UUIDs in `events`. Write order enforced by the extraction pipeline (Postgres first, then Neo4j). Cross-store integrity verified by `backend/scripts/check_provenance.py` (Phase 4).

**Post-Phase-1B Docker-copy baseline (non-negotiable)**: any new directory added to the backend (e.g., `backend/alembic/`, `backend/scripts/`) **must** be copied into the Docker image in the same commit. Verify with `docker compose exec backend find /app -type d`. A migration runner that silently no-ops because its files are absent is an invisible bug.

---

## Graph Schema (LOCKED IN — Phase 1B)

Designed backward from the 4 killer queries; closed set (no new labels/edges at runtime). Full rationale: `docs/design/graph-schema.md`. Summary: [ADR 0007](docs/decisions/0007-graph-schema-v1.md). Python models: `backend/app/schemas/graph.py`.

### Node labels (6)

| Label | One-line description |
|-------|----------------------|
| `Service` | A deployed, running software unit with owners and runtime dependencies (e.g. `payments-api`). |
| `System` | A higher-level named asset/platform a decision can deprecate (e.g. `legacy-auth`). |
| `Person` | An individual: engineer, approver, author, stakeholder. |
| `Team` | An engineering team that owns services and contains people. |
| `Decision` | A choice made, with provenance and temporal validity (`valid_from`/`valid_to`/`status`). |
| `Message` | A Slack-style message — an atom of discussion. |

### Relationship types (9)

| Type | Direction | Enables |
|------|-----------|---------|
| `DEPENDS_ON` | Service → Service\|System | Blast radius, ownership chain |
| `OWNED_BY` | Service\|System → Person\|Team | Ownership queries |
| `MEMBER_OF` | Person → Team | Team→people expansion (blast radius) |
| `DEPRECATES` | Decision → System | Multi-hop ownership (KQ1) |
| `ABOUT` | Decision → System\|Service | Change tracking (KQ4) |
| `APPROVED_BY` | Decision → Person | Approval attribution (KQ4) |
| `AUTHORED` | Person → Message\|Decision | Authorship / provenance |
| `MENTIONS` | Message → any entity | Grounding discussions to entities |
| `CONTRADICTS` | Message → Decision | Temporal contradiction (KQ2) |

**Identity**: Service/System/Team keyed by `canonical_name`; Person by `canonical_id`; Decision by UUID `id`; Message by `id = "source_id:external_id"`. **Provenance**: every node carries `source_event_ids` (FKs into the Postgres events log); every edge carries `confidence` + `extracted_by`. **Entity resolution is Phase 3** — the v1 write path is best-effort and may create duplicate nodes the schema is designed to later merge.

---

## Synthetic Company (LOCKED IN — Phase 2A)

The eval fixture for every later phase is one hand-curated fictional company:
**Northwind Payments**, a ~6-year-old B2B payments processor mid-migration on two fronts
(strangling a `core-monolith`; replacing `legacy-auth` with `auth-service`). Modelled:
13 people / 5 teams / 12 services / 5 systems / 10 decisions. The generator
(`backend/app/synthetic/`) composes this company plus a hand-designed set of adversarial
planted cases — name aliases, a 4-hop deprecation→ownership chain (KQ1), an
active-decision-vs-recent-discussion contradiction (KQ2), a depth-≥4 / 10-service blast
radius (KQ3), and a multi-month auth change timeline with a supersession (KQ4) — into raw
**Postgres `events` rows** (the graph stays empty; extraction is Phase 2B). Generation is
fully deterministic (one seeded RNG + a fixed `REFERENCE_NOW`) so downstream eval numbers
reproduce. Full design: [docs/design/synthetic-company.md](docs/design/synthetic-company.md);
strategy: [ADR 0011](docs/decisions/0011-synthetic-data-strategy.md). Run the seeder with
`docker compose exec backend python -m app.synthetic.seeder`. **Do not change the company
definition or the seed (`42`) without updating the design doc — it invalidates eval baselines.**

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+, managed with `uv` |
| API | FastAPI 0.115+, Pydantic v2 |
| Graph DB | Neo4j 5.x community (APOC plugin) |
| Relational + Vector DB | Postgres 16 + pgvector extension |
| ORM | SQLAlchemy 2.x async |
| Frontend (Phase 4B) | React + react-force-graph |
| Logging | structlog 24.x — JSON in prod, ConsoleRenderer in debug; contextvars for request_id |
| Tooling | ruff (lint + format), mypy strict, pytest + pytest-asyncio, pre-commit |

---

## Project Values (Non-Negotiable)

1. **Documentation first** — every non-trivial decision gets an ADR; every hard concept gets a concept doc.
2. **Type safety everywhere** — mypy strict mode; no `# type: ignore` without a documented reason.
3. **Tests for everything with logic** — no deferred tests.
4. **Reproducibility** — `docker compose up` brings up the entire stack on any machine.
5. **Scope honesty** — synthetic data only, closed entity types, no multi-tenancy, no production auth, no PII. These are named limitations, not hidden ones.

---

## Coding Conventions

- Imports ordered by ruff/isort defaults: stdlib → third-party → local (`app.*`)
- All public functions and classes have docstrings explaining **intent**, not mechanics
- Type hints on every function signature; `mypy --strict` must pass
- No `os.environ` reads outside `backend/app/config.py`
- No string-concatenated SQL or Cypher — parameterised queries only
- One concept per module; split files that exceed ~300 lines
- No `Any` without explicit justification in a comment

---

## Documentation Conventions

- Every non-trivial design choice → ADR in `docs/decisions/` using `template.md`
- Every hard technical concept → concept doc in `docs/concepts/`
- Every subphase → `docs/interview-prep/phase-Xy-readiness.md`
- `HANDOFF.md` is **overwritten** at the end of every subphase
- `docs/README.md` is updated to list every new doc added

---

## Scope Honesty (LOCKED IN)

Synthetic data only. Entity types are closed (no new types added at runtime). No multi-tenancy. No production authentication. No PII handling. These limitations are listed in `README.md` under "Limitations and Future Work" — they are deliberate scope decisions, not unfinished work.

---

## 14-Subphase Plan

| # | Phase | Description | Status |
|---|-------|-------------|--------|
| 1A | Foundation | Scaffolding, documentation infrastructure, session context files | **Complete** |
| 1B | Neo4j Schema | Node labels, relationship types, constraints, Cypher migrations | **Complete** |
| 1C | Postgres Models | SQLAlchemy models, Alembic migrations, pgvector column setup | **Complete** |
| 2A | Synthetic Generator | Adversarial hand-curated generator → raw Postgres events (graph stays empty) | **Complete** |
| 2B | Message Parser | Slack-style message ingestion pipeline and normalisation | Pending |
| 2C | Document Parser | Decision doc and meeting note parser | Pending |
| 2D | Entity Extraction | LLM-powered entity + relationship extraction pipeline | Pending |
| 2E | Graph Write Path | Upsert to Neo4j, entity deduplication, write validation | Pending |
| 3A | Multi-hop Traversal | Query engine: ownership and dependency traversal | Pending |
| 3B | Temporal Queries | Query engine: contradiction detection across time windows | Pending |
| 3C | Blast Radius | Query engine: reachability analysis from a seed node | Pending |
| 3D | Semantic Search | Embedding pipeline, pgvector indexing, hybrid graph-vector queries | Pending |
| 4A | Agent Layer | Query router, graph-RAG fusion, answer generation with provenance | Pending |
| 4B | Frontend | react-force-graph visualisation, demo polish, interview prep | Pending |

---

## Session Bootstrap Protocol

**If you are a fresh Claude Code session, follow these steps exactly:**

1. Read this entire `CLAUDE.md`. It is the ground truth for conventions, decisions, and roadmap.
2. Read `HANDOFF.md` for the latest subphase state: what was built, what decisions were made, what is open.
3. Skim `docs/decisions/` for ADRs relevant to your current task. Prior decisions are **binding** unless explicitly revisited with a new ADR.
4. Only then begin the task in the user's prompt.

Do not re-derive architectural decisions already captured in ADRs. Do not silently expand scope beyond named limitations. If a task requires deviating from a prior decision, write a new ADR first and link it in HANDOFF.md.

---

## Known Gaps and Deferred Decisions

These are intentional omissions, not unfinished work. They are named here so future sessions do not accidentally "fix" them without a deliberate decision.

1. **No observability beyond structured logs** — no metrics (Prometheus/StatsD), no distributed tracing (OpenTelemetry). Structured JSON logs are the only signal. ADR 0006 documents the upgrade path to OTel.

2. **Background worker architecture TBD (Phase 4)** — the ingestion pipeline and embedding jobs will eventually need async workers. Whether to use Celery, arq, or a simple asyncio task queue is deferred. Do not introduce a task queue before Phase 4 without an ADR.

3. **No rate limiting** — the API accepts unlimited requests. Acceptable for a demo; a production system would add rate limiting at the reverse proxy (nginx/Caddy) or API gateway layer.

4. **No auth on `/health`** — the health endpoint is intentionally unauthenticated. It exposes DB connectivity state to anyone with network access. Acceptable on a private Docker network; would need a bearer token or IP allow-list in production.

5. **No CI pipeline** — there is no GitHub Actions, GitLab CI, or equivalent. Tests are run locally via `uv run pytest`. Adding CI is straightforward (one YAML file) but out of scope for a solo portfolio project until the repo is public.
