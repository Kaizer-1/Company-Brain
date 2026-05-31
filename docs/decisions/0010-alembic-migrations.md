# ADR 0010 — Alembic for Postgres Schema Migrations

## Status

Accepted

## Context

Phase 1C introduces the Postgres schema for Company Brain: three tables (`events`, `event_embeddings`, `extraction_runs`) plus two Postgres enum types and a pgvector HNSW index. These must be created on a fresh database at startup, kept in sync across developer machines and Docker environments, and evolved safely as later phases add columns or tables. We need a migration strategy that: (1) handles async SQLAlchemy 2.x and asyncpg correctly; (2) can create Postgres-specific objects that SQLAlchemy's autogenerate does not cover natively (enums, HNSW vector indexes, extensions); (3) applies idempotently at startup; and (4) is a standard tool a hiring interviewer will recognise.

The Phase 1B Neo4j migration runner was homemade, justified by Neo4j's lack of a mature migration ecosystem (see ADR 0008). Postgres has a mature migration ecosystem, so a homemade solution is not appropriate here.

## Decision

Alembic with async engine support (`run_sync` inside a connected async engine), autogenerate from SQLAlchemy models, with hand-edited initial migration for pgvector extension, Postgres enum types, and HNSW index. Applied at FastAPI startup via `command.upgrade(cfg, "head")`.

## Alternatives Considered

### Option A — Raw SQL files with a custom runner (same pattern as Neo4j)

**What it is**: maintain numbered `.sql` files in `backend/migrations/postgres/` and apply them with a homemade Python runner, mirroring the approach in `backend/app/db/migrations.py` for Cypher.

**Pros**:
- Consistency with the existing Neo4j migration approach — one mental model for both stores
- No additional dependency
- Full control over SQL

**Cons**:
- Re-inventing what Alembic already does, worse. Alembic provides: autogenerate from ORM models (detects schema drift), versioned migration graph with branching, the `alembic_version` tracking table, rollback scripts (`downgrade`), and a well-understood CLI. A homemade runner has none of this
- Autogenerate is the killer feature: when a future phase adds a column to `Event`, Alembic detects the diff between the ORM model and the live schema and generates the ALTER TABLE statement. A homemade runner requires the developer to write it by hand and remember to do so
- A homemade SQL runner is a hiring anti-signal in a Postgres context. The Neo4j runner was justified because Neo4j lacks Alembic. Postgres does not lack Alembic
- The Phase 1B lesson (migrations that silently no-op) applies here too: Alembic's `alembic_version` table is a standard, well-tested ledger. A homemade runner's ledger needs to be tested from scratch

**Rejected**: the homemade approach is correct for Neo4j where no good tool exists; it is wrong for Postgres where the standard tool is mature and expected.

### Option B — SQLModel's built-in migration (via `SQLModel.metadata.create_all`)

**What it is**: use `SQLModel.metadata.create_all(engine)` in the lifespan to create all tables that don't exist, instead of Alembic.

**Pros**:
- Zero migration files — schema is always derived from the current models
- Simple to understand; works for rapid prototyping

**Cons**:
- `create_all` is not a migration system: it creates tables that don't exist but does not alter tables that have drifted. If a column is added to a model, `create_all` does nothing — the existing table is untouched and the new column is silently absent
- No history, no rollback, no autogenerate, no `alembic_version` table
- `create_all` cannot create Postgres enum types before the table that uses them (ordering problem that Alembic solves with `op.execute` pre-statements)
- Cannot install extensions (`CREATE EXTENSION`) or create HNSW indexes (not natively supported by SQLAlchemy's DDL layer)
- This is the pattern that causes "the tests passed but the schema is wrong" bugs — exactly the Phase 1B anti-pattern we are explicitly guarding against

**Rejected**: `create_all` is appropriate for throwaway demos; it is incompatible with any schema that needs to evolve.

### Option C — Flyway or Liquibase

**What it is**: Java-based migration frameworks that manage versioned SQL scripts, commonly used in enterprise environments.

**Pros**:
- Industry-standard; supports rollback, checksums, and locking
- Works with any SQL database without Python-specific coupling

**Cons**:
- Requires JVM in the Docker image, adding ~200MB to image size
- No integration with SQLAlchemy autogenerate — migrations must be written by hand
- Not a Python-native tool; a Python team using Flyway is surprising and raises questions in interviews about why they didn't use Alembic
- Overkill for a single-developer portfolio project

**Rejected**: JVM dependency and no autogenerate make this a poor fit.

### Option D — Alembic (chosen)

**What it is**: the standard Python database migration library, tightly integrated with SQLAlchemy. Maintains a migration graph in `alembic/versions/`, tracks applied revisions in an `alembic_version` table, and supports autogenerate from ORM metadata.

**Pros**:
- Autogenerate: `alembic revision --autogenerate` detects diff between ORM models and live schema, generates an ALTER TABLE / CREATE TABLE migration
- Async support via `run_sync`: the `env.py` can use `AsyncEngine.connect()` and run migrations synchronously inside the async context via `connection.run_sync(do_run_migrations)` — the recommended pattern for SQLAlchemy 2.x + asyncpg
- Hand-editable migrations: the initial migration is autogenerated and then hand-edited to add `CREATE EXTENSION IF NOT EXISTS vector`, raw SQL for the HNSW index, and enum type creation with `op.execute`
- Startup integration: `from alembic import command; command.upgrade(cfg, "head")` runs at FastAPI startup, inside a `run_sync` call, so the schema is always current before the app serves traffic
- Industry standard: a hiring interviewer sees `alembic/versions/` and immediately understands the migration strategy
- `alembic_version` table: the built-in ledger means `command.upgrade("head")` is idempotent — re-running it on an already-migrated DB is a no-op, not a duplicate

**Cons**:
- async setup is slightly more complex than sync (requires `run_sync` wrapper in `env.py`)
- Autogenerate does not detect HNSW indexes or Postgres enum types; those must be written manually in the migration

**Chosen**: the async complexity is a known, well-documented pattern. The manual enum/index additions are a one-time cost. Every other migration going forward is autogenerated.

## Consequences

**Enables**: Autogenerated migrations for future schema changes. Idempotent startup-time application. Standard `alembic_version` ledger for migration state. Rollback scripts (downgrade path).

**Constrains**: All schema changes must go through Alembic migration files. Direct `CREATE TABLE` in application code is forbidden. New Postgres enum values must use `op.execute("ALTER TYPE ... ADD VALUE ...")` with conditional logic.

**Locked into**: Alembic as the migration tool. The `alembic_version` table (do not rename or drop it). The `alembic/` directory layout inside `backend/`.

**At larger scale / in production**: Add `alembic check` to CI to detect uncommitted schema drift (fails if autogenerate would produce a non-empty migration). Use Alembic's branching and merging for concurrent feature branches. Consider `alembic stamp head` for blue-green deployment scenarios.

## Gotchas

### `fileConfig` in `env.py` destroys structlog's handler chain

**Symptom**: After `alembic_command.upgrade(cfg, "head")` runs at startup, all subsequent `log.info(...)` calls produce zero output. The app functions correctly but `postgres_migrations_applied` and `startup_complete` never appear in logs.

**Root cause**: The stock Alembic `env.py` template includes:

```python
from logging.config import fileConfig

if config.config_file_name is not None:
    fileConfig(config.config_file_name)
```

When `alembic.ini` contains `[loggers]`, `[handlers]`, and `[formatters]` sections, `fileConfig` is called with `disable_existing_loggers=True` (the Python default). `logging.config.fileConfig` begins by calling `_clearExistingHandlers()`, which wipes **all** existing handlers from `logging._handlers` before installing its own. This destroys the structlog `ProcessorFormatter` handler that `configure_logging()` installed at startup.

The bug is silent: the app still starts, `/health` returns 200, migrations run correctly — you only discover the clobber by noticing that every log line after Alembic runs disappears.

**Fix applied (Phase 1C follow-up)**:

1. Removed the `[loggers]`, `[handlers]`, `[formatters]`, and related sections from `alembic.ini`. These sections are only used by the Alembic CLI; they are not needed when `upgrade()` is called programmatically.

2. Removed the `fileConfig(config.config_file_name)` call from `alembic/env.py` (and the associated import). Alembic's own log output (`alembic.*` loggers) routes through the existing stdlib root handler as structured JSON — no separate configuration is needed.

**Rule for future sessions**: Never add `[loggers]`/`[handlers]`/`[formatters]` sections to `alembic.ini` in this project. If Alembic CLI logging needs tuning, do it in `alembic/env.py` using `logging.getLogger("alembic").setLevel(...)` rather than `fileConfig`.

## Interview Defense

> "We use Alembic because it's the standard Python migration tool, it integrates with SQLAlchemy autogenerate to detect schema drift, and it handles async engines via the run_sync pattern. The alternative was create_all, which is what caused the Phase 1B silent-no-op bug: it creates tables but never alters them, so a drifted schema is indistinguishable from a correct one. Alembic's alembic_version table gives us a reliable ledger. The only manual work is the initial migration, where we hand-edit to add the pgvector extension install and the HNSW index — both are beyond SQLAlchemy's DDL layer."
