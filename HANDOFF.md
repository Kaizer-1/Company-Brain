# HANDOFF — Company Brain

> **This file is overwritten at the end of every subphase.**
> Structure: Subphase → What was built → Decisions made → Deviations → Open questions → DoD check → Codebase state → Next subphase.
> Future sessions: read `CLAUDE.md` first, then this file.

---

## Subphase

Phase 1B — Neo4j Graph Schema Design + Cypher Migrations

## Date

2026-05-31

---

## What Was Built

### Design & decision docs

- **`docs/design/graph-schema.md`** (centerpiece, ~3800 words) — the schema designed backward from the 4 killer queries. Covers design philosophy, all 6 node types and 9 relationship types, the Service-vs-System argument, temporal model, provenance model, confidence/extraction metadata, identity strategy, all 4 killer queries written as validated Cypher (with the indexes that serve them), out-of-scope rejections, and open Phase 2+ questions.
- **`docs/decisions/0007-graph-schema-v1.md`** — ADR summarising the high-level schema decisions (closed 6-label set, confidence-on-edges, validity-interval temporal model, property-based provenance).
- **`docs/decisions/0008-cypher-migration-strategy.md`** — ADR for the homemade Python migration runner over neo4j-migrations / Liquibase / no-system.
- **`docs/interview-prep/phase-1b-readiness.md`** — the 10 mandated Q&A pairs + 5 whiteboard concepts.

### Cypher migrations — `backend/migrations/graph/`

- `001_constraints.cypher` — 6 node uniqueness constraints + 1 on `_Migration.name`; all `CREATE CONSTRAINT ... IF NOT EXISTS`.
- `002_indexes.cypher` — range indexes on `Decision.status`, `Decision.valid_from`, `Message.created_at` (canonical keys are already constraint-backed, so not re-indexed).
- `003_existence_constraints.cypher` — intentionally comment-only: property-existence constraints are Neo4j Enterprise-only; enforcement happens at the Pydantic boundary on Community. Recorded as an applied no-op.

### Code

- **`backend/app/db/migrations.py`** (new) — `apply_migrations(driver, *, migrations_dir=None) -> list[str]`. Reads `*.cypher` in name order, splits on `;` (stripping `//` comments), runs each pending file's statements as auto-commit transactions, records `(:_Migration {name, applied_at})`, logs `migration_applied`, returns newly applied names. Idempotent.
- **`backend/app/schemas/graph.py`** (new) — Pydantic v2 models: `Node` base + `Service`, `System`, `Team` (via private `_NameKeyedNode`), `Person`, `Decision`, `Message`; `Relationship` base + `RelationshipType` enum. All `frozen=True, extra="forbid"`. Heavy docstrings naming the motivating killer query. `id` auto-mirrors the canonical key (name/canonical_id) and is composed for `Message`.
- **`backend/app/schemas/__init__.py`** (new).
- **`backend/app/db/neo4j_client.py`** (updated) — added a read-only `driver` property (sanctioned raw-driver access for the migration runner; queries still go via `session()`).
- **`backend/app/main.py`** (updated) — lifespan now verifies Neo4j connectivity, then calls `apply_migrations(neo4j.driver)`; logs `migrations_applied`; a migration failure logs `migrations_failed` and aborts startup.

### Tests

- **`backend/tests/test_schemas.py`** (new) — per-model valid + invalid parses; parametrized `frozen` and `extra="forbid"` suites across all 8 models; id-mirroring / id-composition assertions; confidence-range and unknown-relationship-type rejection.
- **`backend/tests/test_migrations.py`** (new) — mocked async driver (hand-rolled async CM + AsyncMock session); asserts name-order application, skip-already-applied, idempotency, ledger-first read, and comment-only no-op handling; plus direct `_split_statements` unit tests.

### Doc index / context

- **`CLAUDE.md`** — added "Graph Schema (LOCKED IN — Phase 1B)" section (node + edge tables, identity/provenance summary); marked phase 1B **Complete**.
- **`docs/README.md`** — indexed ADR 0007/0008, the design doc, and the phase-1b interview-prep doc.
- **`docs/concepts/what-is-a-knowledge-graph.md`** — added a note marking its schema *preview* as superseded by the locked schema (preview used `OWNS`/`DEPRECATED_BY`; locked uses `OWNED_BY`/`DEPRECATES`).

---

## Decisions Made

| ADR | Decision |
|-----|---------|
| [0007](docs/decisions/0007-graph-schema-v1.md) | Graph schema v1 — 6 labels / 9 edges, backward-designed; confidence-on-edges; validity-interval temporal; property-based provenance |
| [0008](docs/decisions/0008-cypher-migration-strategy.md) | Homemade Python Cypher migration runner; idempotent via `IF NOT EXISTS` + `_Migration` ledger |

Key in-schema calls (full rationale in the design doc):
- **`Service` and `System` are distinct labels** (not one `Component {kind}`). Argued both sides; committed to two because killer query 1 distinguishes the deprecated *system* from the dependent *service*. Named as the schema's softest spot.
- **`Project` rejected** for v1 (no killer query traverses it) — flagged as the first v2 addition.
- **Provenance is a node property (`source_event_ids`)**, FK into the Postgres events log, not a `SourceEvent` graph node — keeps traversals clean; raw events already live immutably in Postgres.

---

## Deviations from Spec

1. **Relationship names differ from the Phase 1A concept-doc preview** — locked schema uses `OWNED_BY` (not `OWNS`) and `DEPRECATES` Decision→System (not `DEPRECATED_BY` System→Decision). The preview was explicitly non-binding; the concept doc now carries a superseded-by note.
2. **9 relationship types, not the 6 the HANDOFF preview listed** — added `ABOUT`, `MENTIONS`, `MEMBER_OF` (each justified by a killer query: KQ4 subject edge, KQ2 grounding, KQ3 team→people expansion). Node count held at 6.
3. **Added `_NameKeyedNode` private base** — shared structure for the three name-keyed node labels; not itself a node label.
4. **Added a `driver` property to `Neo4jClient`** — the migration runner takes an `AsyncDriver` by contract; documented as the one sanctioned raw-driver use.
5. **`apply_migrations` has an optional `migrations_dir` keyword** — for test injection; the required `apply_migrations(driver)` call signature is unchanged.
6. **`RelationshipType` enum instead of a bare `type: str`** — stricter (rejects unknown edge types at construction); the enum is a `str` subclass, so it remains str-compatible.

---

## Open Questions

1. **How is `CONTRADICTS` populated?** Inline at extraction (Phase 2D) or via a dedicated detection pass (Phase 3B)? Schema slot exists; mechanism deferred (may need a `detection_method` edge property).
2. **`SUPERSEDES` edge between decisions?** Not needed by any killer query today; would make KQ4's timeline read more naturally. Held until Phase 4A rendering.
3. **Confidence threshold** for keep-vs-drop edges — cannot calibrate until real extractor confidence distributions exist (Phase 2D).
4. **`OWNED_BY` co-ownership** — modelled N:M but typically N:1; revisit a `primary: bool` property once the generator (Phase 2A) shows how often co-ownership occurs.
5. **`uv.lock` still uncommitted** (carried over from Phase 1A) — `uv sync` now generates one; decide whether to commit for reproducible installs.
6. **Pre-existing `ruff` drift (Phase 1A files)** — `ruff format --check .` flags `config.py`, `logging_config.py`, `test_health.py`, `test_middleware.py` (formatted narrower than the configured `line-length = 100`), and `ruff check .` flags one `TC002` in `logging_config.py`. These predate Phase 1B and were left untouched to keep this subphase's diff focused. Clear them in a dedicated pass: `uv run ruff format . && uv run ruff check --fix .`.

---

## Definition of Done Check

- ✓ `docs/design/graph-schema.md` ≥1500 words (~3800), all required sections present
- ✓ ADR 0007 (≥400 words) and ADR 0008 (≥300 words) per template
- ✓ All Cypher migrations use `IF NOT EXISTS` → idempotent and runnable
- ✓ `apply_migrations` idempotent: reads ledger, skips applied, records new, returns newly applied (proven by `test_migrations.py`)
- ✓ All Pydantic schemas `frozen=True` + `extra="forbid"`, full docstrings
- ✓ `uv run pytest` — **44 passed** (4 pre-existing + 40 new: 33 schema, 7 migration)
- ✓ `uv run mypy backend/` — strict, **no issues in 13 source files**
- ✓ Lifespan applies migrations after connectivity check and logs `migrations_applied`; failure aborts startup
- ✓ All 4 killer queries written as Cypher in the design doc, each annotated with serving indexes
- ✓ Interview-prep doc: 10 Q&A pairs, each ≥80 words
- ✓ `CLAUDE.md` locked-schema section added + 1B marked Complete; `HANDOFF.md` (this file) updated; `docs/README.md` updated

---

## State of the Codebase

**Works**: `/health` endpoint (unchanged); the migration runner is fully unit-tested against a mocked driver; all Pydantic graph models validate, freeze, and reject unknown fields. **`uv run pytest` → 44 passed; `uv run mypy backend/` → clean (13 files).** The real `.cypher` files parse to 7 constraints + 3 indexes + 1 no-op, all carrying `IF NOT EXISTS`. New/changed files are `ruff`-clean (lint + format). Install dev tools with `uv sync --extra dev` (this `pyproject.toml` uses `[project.optional-dependencies]`, so `uv sync --dev` does not install them). `uv` resolves the `neo4j` Python driver to 6.x, which is Bolt-compatible with the pinned `neo4j:5.26-community` server.
**Stubbed**: nothing new stubbed — the schema is fully specified, but no real Neo4j data exists yet and the write path that produces these models is Phase 2E.
**Does not exist**: synthetic data generator, ingestion/extraction pipeline, query engine, agent layer, frontend. Postgres `events` table (the provenance target) is Phase 1C.

---

## Next Subphase

**Phase 1C — Adversarial synthetic data generation** (per this subphase's brief).

Generate synthetic Services, Systems, Persons, Teams, Decisions, and Messages that exercise the schema *adversarially* — name aliasing (`@alice` / `Alice Chen` / `alice@company.com`) to stress the deferred entity-resolution gap, deprecation chains for KQ1, deliberately contradictory message/decision pairs for KQ2, and deep dependency graphs for KQ3 blast radius. The generated objects should validate against `backend/app/schemas/graph.py`.

> **⚠ Roadmap reconciliation needed.** This "next subphase" follows the Phase 1B brief, which names 1C as *adversarial synthetic data generation*. The **locked 14-phase table in `CLAUDE.md`** instead lists **1C = Postgres Models** and **2A = Synthetic Generator**. These disagree. I did **not** silently re-order the locked table (the brief only authorised marking 1B complete). A future session should reconcile: either (a) renumber the table, or (b) treat synthetic-data generation as the next concrete task and slot Postgres Models around it. Note that synthetic generation has a soft dependency on the Postgres `events` table, since `source_event_ids` are FKs into it — which is an argument for doing Postgres Models first.
