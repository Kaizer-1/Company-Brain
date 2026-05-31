# ADR 0008 — Cypher Migration Strategy

## Status

Accepted

## Context

The graph schema ([ADR 0007](./0007-graph-schema-v1.md)) needs uniqueness constraints and indexes created in Neo4j before any data is written, and those DDL statements must be applied **reproducibly** on every machine that runs `docker compose up` (project value #4). The forcing constraints are: a one-person project that should not adopt heavyweight tooling; a Python/async codebase where adding a JVM dependency is disproportionate; and the requirement that running migrations twice must be a safe no-op. Unlike Postgres (where Alembic is the obvious choice in Phase 1C), Neo4j's migration tooling ecosystem is thinner and mostly JVM-based.

## Decision

A **homemade Python migration runner** (`backend/app/db/migrations.py`) that applies numbered Cypher files from `backend/migrations/graph/` idempotently, recording applied migrations as `(:_Migration {name, applied_at})` nodes.

## Alternatives Considered

### Option A — neo4j-migrations (Michael Simons / Neo4j Labs)

**What it is**: a mature JVM tool (with a CLI and Spring integration) that versions Cypher migrations Flyway-style.

**Pros**: battle-tested; checksum validation; supports both Cypher and Java migrations.

**Cons**: requires a JVM in the image (our stack is pure Python); its lifecycle does not integrate with FastAPI's async lifespan; it is far more machinery than six constraints and four indexes warrant.

### Option B — Liquibase Neo4j extension

**What it is**: the Liquibase changelog model adapted to Neo4j.

**Pros**: XML/YAML changelogs; rollback support; enterprise familiarity.

**Cons**: heaviest option; JVM + Liquibase + an extension; rollback is illusory for schema DDL we never intend to reverse; changelog XML is ceremony for a demo-scale graph.

### Option C — No migration system; create constraints on application write

**What it is**: have the write path issue `CREATE CONSTRAINT ... IF NOT EXISTS` lazily.

**Pros**: zero extra files; nothing to run at startup.

**Cons**: scatters schema definition across application code; no single source of truth for "what is the schema"; constraint creation races under concurrent writers; impossible to review the schema as a unit. The schema stops being a reviewable artefact.

### Option D — Homemade Python runner (chosen)

**What it is**: numbered `*.cypher` files plus a ~60-line async runner invoked from lifespan startup.

**Pros**: no new language or dependency (uses the Neo4j driver we already have); integrates with the async lifespan; the migration files are a single, reviewable source of truth; idempotency comes free from Cypher's `IF NOT EXISTS` plus a `_Migration` ledger; trivially testable with a mocked driver.

**Cons**: we own the runner (no community support); no checksum validation of already-applied files; no down-migrations. All acceptable at this scope.

## Consequences

**Enables**: `docker compose up` brings up a fully-constrained graph with no manual step; the schema is reviewable as four small files; the runner is unit-tested against a mocked driver.

**Constrains**: migrations are forward-only and not checksum-validated — editing an already-applied file will not re-run it. Convention: never edit an applied migration; add a new numbered file.

**Locked into**: the numbered-file + `_Migration` ledger pattern. The same pattern is reused if we add graph migrations in later phases.

**At larger scale / in production**: with live data and multiple instances, we would add an advisory lock so only one instance runs migrations, checksum validation to detect drift, and a separate migrate-then-deploy step rather than running migrations in application startup. At that point neo4j-migrations becomes worth its weight.
