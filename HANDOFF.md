# HANDOFF — Company Brain

> **This file is overwritten at the end of every subphase.**
> Structure: Subphase → What was built → Decisions made → Deviations → Open questions → DoD check → Codebase state → Next subphase.
> Future sessions: read `CLAUDE.md` first, then this file.

---

## Subphase

Phase 2A — Adversarial Synthetic Data Generation

## Date

2026-06-01

---

## What Was Built

### Design & decision docs

- **`docs/design/synthetic-company.md`** (~2400 words) — the locked fictional company
  **Northwind Payments** (13 people / 5 teams / 12 services / 5 systems / 10 decisions),
  with all six required sections: narrative, org chart, service inventory (+ dependency
  graph), system inventory, decision history (chronological, with a supersession), and the
  adversarial planted-case list (§6). The interview-readable answer to "you wrote the data".
- **`docs/decisions/0011-synthetic-data-strategy.md`** — ADR: hand-curated adversarial
  fictional company over (A) Faker random, (B) real OSS data e.g. Apache lists, (C) Enron;
  why deterministic seeding, why design-before-generate, why raw events not graph nodes.

### Synthetic module — `backend/app/synthetic/`

- `company.py` — frozen dataclasses (`SyntheticPerson/Team/Service/System/Decision/Company`)
  and the single `COMPANY` constant mirroring the design doc. `REFERENCE_NOW = 2026-06-01`
  and `HANDLE_CHANGE_AGE_DAYS` constants. `handle_at_age()` models Ben's `@bsmith`→`@ben`.
- `narrative.py` — the planted cases **as data**, each with a `kq` field: `AliasGroup` (6),
  `LookAlikePair` (1), `DeprecationChain` (KQ1), `ContradictionPair` (KQ2), `DependencyGraph`
  (KQ3) + pure `blast_radius`/`max_dependency_depth`/`dependents_of` helpers, `ChangeTimeline`
  (KQ4), `OwnershipAmbiguity`, `StaleDoc` (2), `DepartureTransfer`. `all_planted_cases()`.
- `templates.py` — `TemplateStyle` enum + `Template` dataclass (each phrasing carries a
  style) + tuples of varied phrasings (dependency, deprecation, contradiction, change,
  alias-person, alias-service, look-alike, ownership, departure, handle-change, ambient) +
  document scaffold functions (decision record, arch overview, org chart, catalog, wiki,
  stale wiki) that take pre-rendered lines so this module stays decoupled from `company.py`.
- `generator.py` — `SyntheticDataGenerator(seed=42)`; `generate() -> list[EventCreate]`.
  One threaded `random.Random(seed)` (no global `random`); resets RNG + slack counter at the
  top of `generate()` so repeat calls are byte-identical. Fourteen `_emit_*` passes compose
  the corpus; `created_at` is `REFERENCE_NOW - age` with deterministic intra-day jitter.
- `seeder.py` — `async seed_postgres(repo, events) -> int` (idempotent via `get_by_source`;
  flushes, does **not** commit — caller owns the transaction) + `async main()` + a
  `python -m app.synthetic.seeder` entrypoint that connects via settings and commits once.
- `__init__.py` — package docstring.

### CLI — `backend/scripts/seed_synthetic.py`

One-shot script (`uv run python backend/scripts/seed_synthetic.py`) that inserts `backend/`
onto `sys.path`, configures logging, and calls `app.synthetic.seeder.main()` (DRY).
Replaces the old root `scripts/seed_db.py.placeholder` (deleted).

### Tests — `backend/tests/synthetic/` (61 new tests)

- `test_company.py` (14) — counts within design-doc bounds + exact locked counts, unique
  ids, namespace disjointness, every reference resolves, departed person, handle change.
- `test_narrative.py` (18) — every planted case has a valid `kq`; category counts; alias
  forms consistent with the company; deprecation chain is a real 4-hop path; contradiction
  active + recent; **depth ≥ 4**; **blast radius ≥ 10 services**; ≥4 direct dependents;
  timeline has ≥4 in-quarter auth decisions + a supersession; ambiguity resolves to authority.
- `test_generator_determinism.py` (4) — two fresh instances identical; same instance twice
  identical; content + timestamps + ids byte-identical; different seed changes output.
- `test_generator_event_count_and_shape.py` (9) — 80–150 messages, 20–40 docs; every event
  is an `EventCreate`; `content_hash == sha256(content)`; hash unique per content; ids unique
  per type; timestamps tz-aware and within the window; a recent tail exists for KQ2.
- `test_generator_planted_cases_are_extractable.py` (12) — every alias form, look-alike pair,
  deprecation link, contradiction, **every dependency edge co-occurring in one event**, deep
  chain, timeline decisions + supersession + approvers, ambiguity, stale docs, departure,
  and both Ben handles appear in the raw text.
- `test_seeder.py` (4, testcontainers) — full seed inserts all events; second seed is a
  no-op (idempotent); events are chronologically spread; both source types present.
- `conftest.py` — `corpus` + `blob` module-scoped fixtures.

### Updated docs / infra

- **CLAUDE.md** — new "Synthetic Company (LOCKED IN — Phase 2A)" section; 2A marked
  **Complete** (and its description corrected — it is *not* Faker-based, per ADR 0011).
- **docs/README.md** — indexed ADR 0011 and the synthetic-company design doc.
- **README.md** — quickstart now shows `docker compose exec backend python -m app.synthetic.seeder`.
- **backend/Dockerfile** — `COPY backend/scripts/ ./scripts/` added (Docker-copy baseline rule).

---

## Decisions Made

| ADR | Decision |
|-----|---------|
| [0011](docs/decisions/0011-synthetic-data-strategy.md) | Hand-curated adversarial fictional company; deterministic seeding; design-before-generate; raw events not graph nodes |

Key in-code calls:
- **`REFERENCE_NOW` is a fixed constant**, not `datetime.now()` — the only way `generate()`
  can be byte-identical across runs (and days). All ages are measured back from it.
- **`user-store` is a System, not a Service** — a deliberate exercise of the schema's named
  soft spot (graph-schema.md "Service vs. System"); also frees a service slot so the
  `payments-api` blast radius reaches exactly 10 services inside the 8–12 budget.
- **`seed_postgres` flushes but never commits** — the caller owns the transaction boundary,
  so tests roll back for isolation and the CLI commits once. Idempotency uses `get_by_source`
  (a SELECT) rather than catching `IntegrityError`, which would poison the transaction.
- **Supersession is data, not a graph edge** — represented by `status="superseded"` on
  D-0004 + the textual "Supersedes: D-0004" signal (graph-schema.md open question #5 defers a
  `SUPERSEDES` edge); extraction can populate whatever Phase 4 chooses.

---

## Deviations from Spec

1. **Recent-tail timing vs "~30 days before today".** The bulk of events end ~35–360 days
   before `REFERENCE_NOW`, but the KQ2 contradiction thread (~20–22d) and the Bob-left
   transfer (~19–20d) are a deliberate fresh tail so KQ2's "last month" and KQ4's "last
   quarter" windows have data. Everything is still strictly in the past with a freshness
   buffer (nothing newer than ~16 days, nothing in the future). Documented in §1 / §6.3 of
   the design doc and ADR 0011.
2. **`scripts/seed_synthetic.py` is a thin wrapper** around `app.synthetic.seeder.main()`
   rather than re-inlining the engine/session/generate steps — DRY; the seeder module already
   owns that logic and is the Docker entrypoint.
3. **`backend/scripts/` is now copied into the image** for baseline compliance, though the
   canonical Docker entrypoint remains the module form `python -m app.synthetic.seeder`.

---

## Open Questions

1. **Reference-now at demo time (Phase 3B).** KQ2/KQ4 filter on "last month"/"last quarter".
   The query engine must evaluate those windows relative to `REFERENCE_NOW` (or the data must
   be re-seeded with a current anchor), or the recent tail will fall outside a real-`now`
   window. This is the first thing Phase 3B's temporal queries must wire up.
2. **Phase 2B gold set.** The extraction/resolution eval should derive ground truth directly
   from `company.py` + `narrative.py` (recommended — single source of truth) rather than a
   separate hand-labelled file. Decide the exact shape when the eval harness is built.
3. **Content-hash uniqueness.** The generator guarantees globally-unique content today; if a
   future planted case reuses phrasing, add a deterministic disambiguator rather than relying
   on luck (the shape test will catch a regression).

---

## Definition of Done Check

- ✓ `docs/design/synthetic-company.md` ~2400 words; all 6 sections present
- ✓ ADR 0011 written per template (4 alternatives, deterministic/adversarial/raw-events rationale)
- ✓ `backend/app/synthetic/` module structure exactly as specified (company, narrative, templates, generator, seeder, __init__)
- ✓ All planted-case categories implemented: ER traps (3 people + 3 services + 1 look-alike), KQ1 chain, KQ2 contradiction, KQ3 depth ≥4 + 10-service blast radius, KQ4 timeline + supersession, bonus messiness (2 stale docs, departure, ambiguous ownership)
- ✓ Deterministic generation — `test_generator_determinism.py` passes (byte-identical incl. timestamps)
- ✓ Event counts in bounds — 89 messages, 22 docs (111 total) at seed=42
- ✓ Every planted case references its anchor entities in generated text — `test_generator_planted_cases_are_extractable.py` passes
- ✓ Seeder idempotent — second run inserts 0 (`test_seeder.py`)
- ✓ `uv run pytest` — **160 passed** (99 prior + 61 new)
- ✓ `uv run mypy backend/` — strict, clean (36 source files)
- ✓ `uv run ruff check` on new files — clean
- ✓ CLAUDE.md, HANDOFF.md, docs/README.md updated; Dockerfile copies `backend/scripts/`

---

## Verify a Clean Run

After `docker compose up --build -d` on a fresh volume:

```bash
# Run the seeder against the fresh DB (idempotent; safe to re-run)
docker compose exec backend python -m app.synthetic.seeder

# Verify event count + distribution by source type
docker compose exec postgres psql -U company_brain -c \
  "SELECT source_type, COUNT(*) FROM events GROUP BY source_type"

# Verify a planted case landed: the deprecated-system anchor appears in many events
docker compose exec postgres psql -U company_brain -c \
  "SELECT COUNT(*) FROM events WHERE content ILIKE '%legacy-auth%'"
```

Expected:
1. `synthetic_seed_complete` structlog line with `generated=111 inserted=111` (then
   `inserted=0` on a second run).
2. Two rows: `doc | 22` and `slack_message | 89`.
3. `legacy-auth` count ≥ 5 (actually 17) — the KQ1 deprecation anchor is well represented.

---

## State of the Codebase

**Works**: all 160 tests pass (`uv run pytest`); `uv run mypy backend/` strict-clean (36
files). The synthetic generator is deterministic and idempotently seedable into Postgres;
real-DB seeder tests run against a testcontainers Postgres and skip gracefully without Docker.

**Graph is intentionally empty** after this phase — the generator writes only raw `events`
rows; extraction is Phase 2B (ADR 0011).

**Stubbed**: `backend/scripts/check_provenance.py` (Phase 4). **Does not exist**: extraction
pipeline, query engine, agent layer, frontend.

---

## Next Subphase

**Phase 2B — LLM extraction pipeline + eval harness (Opus-level).**

Build the extraction pipeline that reads `events` from Postgres and produces graph nodes/edges
conforming to `backend/app/schemas/graph.py`, writing to Neo4j (Postgres-first write order per
the provenance contract). Stand up an extraction **eval harness** whose ground truth derives
from `company.py` + `narrative.py`, reporting precision/recall/F1 per entity and relationship
type — the numbers the deterministic seed (this phase) exists to make reproducible. The
adversarial planted cases (aliases, the KQ1 chain, the KQ2 contradiction, the KQ3 depth, the
KQ4 timeline) are exactly what the eval must show the extractor handling or honestly failing.
