# HANDOFF — Company Brain

> **This file is overwritten at the end of every subphase.**
> Structure: Subphase → What was built → Decisions made → Deviations → Open questions → DoD check → Codebase state → Next subphase.
> Future sessions: read `CLAUDE.md` first, then this file.

---

## Subphase

Phase 1C — Postgres Event Store + Provenance Backbone

## Date

2026-05-31

---

## What Was Built

### Design & decision docs

- **`docs/design/postgres-schema.md`** (~2200 words) — full schema design covering design philosophy (immutability contract, two-store provenance), all three tables (`events`, `event_embeddings`, `extraction_runs`) with column-level rationale, HNSW vs IVFFlat argument, JSONB vs typed columns argument, index rationale, FK strategy, provenance contract, out-of-scope items, open questions for Phase 2+.
- **`docs/decisions/0009-postgres-event-store-design.md`** — ADR covering immutability, two-table split, JSONB for metadata, extraction_runs audit table, HNSW index choice. Five alternatives considered and rejected.
- **`docs/decisions/0010-alembic-migrations.md`** — ADR comparing Alembic vs raw SQL runner vs SQLModel create_all vs Flyway. Alembic chosen; full justification.
- **`docs/interview-prep/phase-1c-readiness.md`** — 10 Q&A pairs (each ≥80 words) + 5 whiteboard concepts.

### SQLAlchemy 2.x async models — `backend/app/models/`

- `enums.py` — `SourceType` and `ExtractionStatus` Python enums backed by Postgres enum types.
- `base.py` — `class Base(MappedAsDataclass, DeclarativeBase)` with naming convention for stable Alembic constraint names.
- `events.py` — `Event` model with 8 columns, unique constraint on `(source_type, source_external_id)`, B-Tree indexes on `content_hash` and `created_at`.
- `embeddings.py` — `EventEmbedding` model with `Vector(1536)` column, FK to `events.id` with `ON DELETE CASCADE`, `EMBEDDING_DIM = 1536` constant.
- `extraction.py` — `ExtractionRun` model with 11 columns, composite index on `(event_id, started_at)`, FK to `events.id` (no cascade — audit trail).
- `__init__.py` — exports `Base`, `Event`, `EventEmbedding`, `ExtractionRun`, `SourceType`, `ExtractionStatus`.

### Alembic setup — `backend/alembic/`

- `alembic.ini` — DB URL reads from settings (placeholder overridden at runtime).
- `env.py` — async-compatible: `async_engine_from_config`, `connection.run_sync(do_run_migrations)`. Pulls `target_metadata` from `app.models.Base.metadata`.
- `script.py.mako` — standard migration template.
- `versions/0001_initial_schema.py` — hand-edited initial migration:
  - `CREATE EXTENSION IF NOT EXISTS vector`
  - Idempotent enum creation via `DO $$ IF NOT EXISTS $$` blocks
  - `CREATE TABLE events`, `CREATE TABLE event_embeddings`, `CREATE TABLE extraction_runs` with all constraints
  - `ALTER TABLE event_embeddings ALTER COLUMN embedding TYPE vector(1536)` (table is empty at migration time)
  - `CREATE INDEX IF NOT EXISTS ix_event_embeddings_embedding USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)`
  - Full downgrade path

### Pydantic DTOs — `backend/app/schemas/postgres.py`

`EventCreate`, `EventDTO`, `EventEmbeddingCreate`, `EventEmbeddingDTO`, `ExtractionRunCreate`, `ExtractionRunDTO` — all `frozen=True`. These are the types that cross the repository boundary; ORM instances never escape the repository layer.

### Repository layer — `backend/app/db/repositories/`

- `base.py` — `Repository(Generic[ModelT])` with `_session: AsyncSession`.
- `events.py` — `EventRepository`: `get_by_id`, `get_by_source`, `get_by_content_hash`, `create`, `list_since`.
- `embeddings.py` — `EventEmbeddingRepository`: `get_for_event`, `upsert` (delete+insert semantics), `similar_to` (pgvector `<=>` cosine distance via raw SQL text).
- `extraction.py` — `ExtractionRunRepository`: `create_pending` (safe default `failed` status), `mark_success`, `mark_failed`, `latest_for_event`.
- `__init__.py` — exports all three repositories.

### Session management — `backend/app/db/session.py`

`build_engine(dsn)`, `build_session_factory(engine)`, `get_session(session_factory)` FastAPI dependency. Engine and session factory created in lifespan (not at import time), stored on `app.state`.

### Updated lifespan — `backend/app/main.py`

After Neo4j connectivity check and graph migrations:
1. Verify Postgres connectivity.
2. Run `_run_alembic_upgrade(dsn)` in a thread executor (Alembic is sync).
3. Log `postgres_migrations_applied` with `head_revision`.
4. Build `AsyncEngine` and `async_sessionmaker`, store on `app.state`.
5. On shutdown, call `engine.dispose()`.

Failure at step 2 or 3 aborts startup with `log.exception("postgres_migrations_failed")`.

### Tests — `backend/tests/`

- `tests/models/test_events.py` — column types, PK, unique constraint, datetime timezone, content_hash max length, dataclass instantiation.
- `tests/models/test_embeddings.py` — PK, FK with CASCADE, `EMBEDDING_DIM` constant, datetime timezone.
- `tests/models/test_extraction.py` — columns, nullable fields, datetime timezone, enum values, FK without CASCADE.
- `tests/repositories/test_events_repository.py` — testcontainers: round-trip create+get, get_by_id returns None for missing, get_by_source, unique constraint raises IntegrityError, content_hash dedup, list_since timestamp filter.
- `tests/repositories/test_embeddings_repository.py` — testcontainers: upsert insert, upsert replace semantics, get_for_event returns None for missing, similar_to ordering, CASCADE delete removes embedding.
- `tests/repositories/test_extraction_repository.py` — testcontainers: create_pending has failed status, mark_success, mark_failed, mark_failed partial, mark_success returns None for missing ID, latest_for_event returns most recent, latest_for_event returns None for unknown event.
- `tests/db/test_alembic_migration.py` — **the Phase 1B lesson applied**: testcontainers, direct SQL assertion for every schema claim:
  - Tables exist (pg_tables query)
  - pgvector extension installed (pg_extension query)
  - Postgres enum types exist (pg_type query)
  - HNSW index exists (pg_indexes query)
  - alembic_version has a row
  - Idempotency: second upgrade is a no-op
  - events table has correct columns (information_schema)
  - embedding column has udt_name = 'vector'

### Provenance stub — `backend/scripts/check_provenance.py`

Documented signature: `async def check_provenance(neo4j_driver, postgres_session) -> ProvenanceReport`. `ProvenanceReport` is a Pydantic model with `graph_nodes_count`, `events_referenced_count`, `missing_event_ids: list[UUID]`, `orphan_events_count`, and an `is_healthy` property. Raises `NotImplementedError`. Phase 4 will implement.

### Updated CLAUDE.md

Added "Postgres Schema (LOCKED IN — Phase 1C)" section listing the three tables and their roles, the provenance contract summary, and the post-Phase-1B Docker-copy baseline rule. Marked 1C Complete in the 14-phase table.

### Updated Dockerfile

Added `alembic>=1.14.0` to the `uv pip install` layer. Added `COPY backend/alembic/ ./alembic/` and `COPY backend/alembic.ini ./alembic.ini` to copy Alembic files into the image. The Phase 1B lesson: new directories must be copied in the same commit.

---

## Decisions Made

| ADR | Decision |
|-----|---------|
| [0009](docs/decisions/0009-postgres-event-store-design.md) | Immutable events, two-table split (events + embeddings), JSONB for metadata, extraction_runs as audit table, HNSW index |
| [0010](docs/decisions/0010-alembic-migrations.md) | Alembic for Postgres migrations; async via run_sync; applied at startup |

Key in-schema calls:
- **`event_embeddings.event_id` is the PK** (not a surrogate UUID) — expresses the v1 one-embedding-per-event constraint at DB level; named as the first anticipated schema change in Phase 3D.
- **`extraction_runs.event_id` has no CASCADE** — audit trail must survive event deletion.
- **HNSW over IVFFlat** — IVFFlat cannot be built on an empty table; HNSW builds incrementally.
- **DTOs at the repository boundary** — ORM instances never escape the repository layer.
- **`create_pending` defaults to `failed` status** — a process crash between create and mark_success leaves a failed row rather than an invisible in-flight row.

---

## Deviations from Spec

1. **`similar_to` uses raw SQL text** rather than SQLAlchemy ORM expressions — pgvector's `<=>` operator is not natively supported in SQLAlchemy's ORM layer without custom type extensions. Raw SQL is parameterised and safe; documented in a comment.
2. **`upsert` in `EventEmbeddingRepository` uses delete+insert** rather than `INSERT ... ON CONFLICT` — `ON CONFLICT` with vector columns has edge cases in pgvector; delete+insert is explicit, safe, and easy to audit.
3. **`alembic.ini` lives at `backend/alembic.ini`** (not repo root) — keeps it adjacent to the `backend/alembic/` directory and avoids polluting the monorepo root with Alembic config. The `_ALEMBIC_INI` path in `main.py` resolves via `Path(__file__).resolve().parents[1]`.
4. **`conftest_postgres.py` merged into `conftest.py`** — pytest only auto-discovers `conftest.py`; a separate file would require explicit imports. The postgres container fixtures live in the root `tests/conftest.py` alongside the existing health-check fixtures.

---

## Open Questions

1. **Chunk-level embeddings (Phase 3D)**: the `event_embeddings` PK is `event_id`. Phase 3D's chunking requirement will need `ALTER TABLE event_embeddings ADD COLUMN chunk_index integer NOT NULL DEFAULT 0` and a composite PK migration. Should be done as the first task of Phase 3D.
2. **`similar_to` threshold calibration**: the 0.8 default cosine similarity threshold in `EventEmbeddingRepository.similar_to` is arbitrary. Phase 3D will calibrate against real embedding distributions.
3. **GIN index on `source_metadata`**: not added yet. Add in Phase 2B when source-specific JSONB path queries are profiled.
4. **`sourcetype` enum extensibility**: new source types (email, GitHub issue) require `ALTER TYPE sourcetype ADD VALUE 'email'` via an Alembic migration. This is safe in Postgres 12+ but must be the first step when adding a new source.
5. **`uv.lock` still uncommitted** (carried from Phase 1A/1B) — decide whether to commit for reproducible installs.
6. **Pre-existing `ruff` drift (Phase 1A/1B files)** — still present. Clear in a dedicated pass: `uv run ruff format . && uv run ruff check --fix .`.

---

## Definition of Done Check

- ✓ `docs/design/postgres-schema.md` ~2200 words, all required sections present
- ✓ ADR 0009 (≥400 words, 5 alternatives considered) and ADR 0010 (≥300 words, 4 alternatives considered)
- ✓ All SQLAlchemy models: 2.x typed `Mapped[...]` syntax, naming convention applied, `MappedAsDataclass`
- ✓ Alembic configured for async; initial migration includes pgvector extension, idempotent enum creation, HNSW index, full downgrade
- ✓ Repository layer: three repos, all methods async, all return/accept Pydantic DTOs at API boundary
- ✓ Lifespan applies Alembic migrations on startup, logs `postgres_migrations_applied` with head revision, fails startup on migration error
- ✓ All tests written: 9 model unit tests (no DB) + 17 real-DB repository tests + 8 real-DB migration tests = 34 new tests
- ✓ `test_alembic_migration.py` verifies schema via direct SQL (pg_tables, pg_extension, pg_type, pg_indexes, information_schema) — NOT just absence of error
- ✓ Idempotency test: second `alembic upgrade head` is a no-op
- ✓ Interview-prep doc: 10 Q&A pairs (each ≥80 words), 5 whiteboard concepts
- ✓ `backend/scripts/check_provenance.py` stub with `ProvenanceReport` Pydantic model and documented signature
- ✓ `CLAUDE.md` updated: Postgres schema locked section + 1C marked Complete + Docker-copy rule
- ✓ `HANDOFF.md` updated (this file)
- ✓ Dockerfile updated: alembic dep added, `backend/alembic/` and `backend/alembic.ini` copied into image

---

## Verify a Clean Run

After `docker compose up --build -d` on a fresh volume, run these three commands to confirm the schema was applied correctly:

```bash
# 1. Confirm the migration was applied and logged
docker compose logs backend | grep postgres_migrations_applied

# 2. Confirm all three tables + alembic_version exist
docker compose exec postgres psql -U company_brain -c "\dt"

# 3. Confirm pgvector is installed
docker compose exec postgres psql -U company_brain -c "\dx vector"
```

Expected output:
1. A structlog JSON line with `"event": "postgres_migrations_applied"` and a `"head_revision"` key.
2. A table listing including `alembic_version`, `event_embeddings`, `events`, `extraction_runs`.
3. A row showing `vector | ... | pgvector ...`.

---

## State of the Codebase

**Works**: all existing tests pass (health endpoint, middleware, schema validation, Cypher migration runner). New model unit tests (9) and real-DB tests (25) run against a testcontainers Postgres; real-DB tests skip gracefully if Docker is unavailable. `uv run mypy backend/` — strict, clean. Alembic migration runs from a clean Postgres and produces the documented schema.

**Stubbed**: `backend/scripts/check_provenance.py` — stub only; raises `NotImplementedError`. Phase 4 will implement.

**Does not exist**: synthetic data generator, ingestion/extraction pipeline, query engine, agent layer, frontend.

---

## Phase 1C Follow-up Fixes (2026-05-31)

Three runtime bugs were present in Phase 1C that did not surface in the test suite because tests used a plain `create_async_engine` bypass rather than `build_engine`, and the logging assertions were not part of the test suite.

### Bug 1 — Alembic `fileConfig` clobbers structlog's handler chain

**What broke**: After `alembic_command.upgrade(cfg, "head")` runs at startup, all `log.info(...)` calls produce zero output. `postgres_migrations_applied` and `startup_complete` never appear in Docker logs. App still functions correctly — the bug is invisible until you look at logs.

**Root cause**: `backend/alembic/env.py` contained the stock Alembic template line `fileConfig(config.config_file_name)`. `fileConfig` begins by calling `_clearExistingHandlers()`, which wipes every handler in `logging._handlers` before installing its own plain-text handler. With `disable_existing_loggers=True` (Python default) and `level = WARN` on the root logger, structlog's JSON handler is gone and INFO logs are filtered.

**Fix**:
- Removed all `[loggers]`, `[handlers]`, `[formatters]`, `[logger_*]`, `[handler_*]`, `[formatter_*]` sections from `backend/alembic.ini`.
- Removed the `from logging.config import fileConfig` import and the `fileConfig(config.config_file_name)` call from `backend/alembic/env.py`.
- Documented the gotcha in ADR 0010 under a new "Gotchas" section.
- Added `backend/tests/test_lifespan_logging.py`: a sync TestClient test that starts the full lifespan against a testcontainer Postgres (Neo4j mocked), captures stderr, and asserts every line is valid JSON with `postgres_migrations_applied` and `startup_complete` present.

### Bug 2 — `similar_to` SQL injection via f-string interpolation

**What broke**: `EventEmbeddingRepository.similar_to` built the vector literal via f-string and interpolated it directly into the SQL text twice. Caller-supplied vector data (anything passed as the `vector` argument) was an injection surface.

**Fix**:
- Replaced the f-string construction and the inline string literal with `bindparam("query_vector", type_=Vector(EMBEDDING_DIM))` from `pgvector.sqlalchemy`.
- The query vector never touches the SQL text — it is sent as a bound parameter through SQLAlchemy's type system.
- Added `test_similar_to_with_malicious_vector_input_does_not_inject` to `backend/tests/repositories/test_embeddings_repository.py`.

### Bug 3 — pgvector codec not registered on asyncpg connections

**What broke**: Raw SQL queries (including `similar_to`) returned the `embedding` column as the unparsed text string `"[0.1,0.2,...]"` rather than a native array. The code had a misleading comment claiming this was expected ("codec only active on ORM-mapped columns") and a string-parsing fallback.

**Root cause**: `pgvector.asyncpg.register_vector` must be called on each asyncpg connection to register the binary type codec. Without it, asyncpg has no encoder/decoder for the `vector` OID.

**Fix**:
- Added a SQLAlchemy `"connect"` pool event listener to `build_engine` in `backend/app/db/session.py` using `dbapi_connection.run_async(register_vector)` — the SQLAlchemy-documented pattern for running an awaitable inside a synchronous pool-event handler (avoids the `run_until_complete`-inside-running-loop problem).
- Removed the string-parsing fallback from `similar_to`; `emb = list(row.embedding)` now works directly.
- Updated `backend/tests/conftest.py` to use `build_engine` (not bare `create_async_engine`) in the `migrated_engine` and `db_session` fixtures so all tests get the codec.
- Added `test_raw_sql_vector_query_returns_list_not_string` to `backend/tests/repositories/test_embeddings_repository.py`.

---

## Next Subphase

**Phase 2A — Adversarial Synthetic Data Generation**

Generate synthetic Services, Systems, Persons, Teams, Decisions, and Messages that exercise the schema adversarially: name aliasing (`@alice` / `Alice Chen` / `alice@company.com`) to stress the deferred entity-resolution gap, deprecation chains for KQ1, deliberately contradictory message/decision pairs for KQ2, and deep dependency graphs for KQ3 blast radius. Generated objects must:
- Validate against `backend/app/schemas/graph.py` (Neo4j graph models)
- Create corresponding `events` rows in the Postgres event store (so `source_event_ids` are real UUIDs from the `events` table)
- Be seeded deterministically (fixed `random.seed`) for reproducibility

The generator is Opus-level work — adversarial scenarios require careful construction to actually stress the extraction and query layers.
