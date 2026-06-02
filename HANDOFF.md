# HANDOFF — Company Brain

> **This file is overwritten at the end of every subphase.**
> Structure: Subphase → What was built → Decisions made → Deviations → Open questions → DoD check → Codebase state → Next subphase.
> Future sessions: read `CLAUDE.md` first, then this file.

---

## Subphase

Phase 2B — LLM Extraction Pipeline + Eval Harness

## Date

2026-06-01

---

## What Was Built

### Design & decision docs

- **`docs/design/extraction-pipeline.md`** (~2600 words) — the full pipeline rationale:
  structured-output prompting vs free-form parsing, the curated prompt (verbatim, ~220
  assembled lines), one-event-one-chunk chunking (+ future overlap), curated schema vs a
  Pydantic JSON-Schema dump (side-by-side), strict validation, provenance writing, cost
  telemetry, and the named failure-mode taxonomy.
- **ADR 0012** — extraction via OpenRouter (one API, model comparison, cost visibility);
  JSON-mode over free-form parsing; curated schema over the full JSON Schema; three models.
- **ADR 0013** — eval ground truth derived from `narrative.py` (single source of truth, no
  drift) rather than a hand-labelled file; the inclusion rule and named limitations.

### Extraction module — `backend/app/extraction/`

- `models.py` — LLM-output Pydantic models (`ExtractedEntity/Relationship/Result`). Every
  item carries a **required `evidence_quote`**; `extra="forbid"`; a before-validator coerces
  the edge type string into `RelationshipType` so strict scalar validation holds elsewhere.
- `prompts.py` — `SYSTEM_PROMPT`, hand-curated `SCHEMA_DESCRIPTION`, two `FEW_SHOT_EXAMPLES`
  (one rich positive, one empty-answer negative), `build_messages`, `PROMPT_VERSION=2b-v1`,
  `prompt_fingerprint()`.
- `client.py` — `OpenRouterClient` (async httpx, JSON-mode, `usage.cost` logging, 429/503
  retry with inline exponential backoff). Reads the key from settings, never `os.environ`.
- `parser.py` — strict `parse_extraction` → typed `ExtractionParseError` (with raw + stage);
  fence-stripping; missing-key guard.
- `graph_writer.py` — idempotent `MERGE` into Neo4j; `source_event_ids` set-union; edge
  `confidence`/`extracted_by`/`source_event_id`/`evidence_quote`; per-event single
  transaction; unresolved-endpoint edges skipped + counted.
- `pipeline.py` — `ExtractionPipeline.extract_event` (full `extraction_runs` lifecycle,
  failed-by-default → success only on clean parse+write) and `extract_all` (bounded
  concurrency = 5, per-event session+commit, progress every 10). Shared `run_extraction`
  seam reused by the eval.

### Eval harness — `backend/app/eval/`

- `ground_truth.py` — `build_ground_truth()` from `company.py`+`narrative.py`: **45
  entities**, **70 relationships** (19 DEPENDS_ON, 13 ABOUT, 13 OWNED_BY, 12 APPROVED_BY,
  12 MEMBER_OF, 1 DEPRECATES). Documented inclusion rule.
- `matcher.py` — alias-tolerant canonicalisation (type-scoped entities; schema-implied
  endpoint resolution for edges); `SurfaceIndex` from company + `ALIAS_GROUPS`.
- `metrics.py` — precision/recall/F1 (PEP-695 generics), per-type breakdowns, zero-division-safe.
- `failure_modes.py` — the named taxonomy, worst-case examples, confidence calibration.
- `runner.py` — `run_eval` with on-disk per-event response cache (`.eval_cache/`, keyed by
  model + prompt-fingerprint + event id); `EvalResult`.
- `report.py` — Markdown renderer (overall table, per-type, failure counts, worst examples,
  cost, Discussion marker).

### CLIs — `backend/scripts/`

- `extract_all.py` (`--model`, `--limit`) — reads Postgres, applies graph migrations, writes
  Neo4j, prints a summary.
- `run_eval.py` (`--models`, `--output`, `--no-cache`, `--limit`) — builds the corpus
  deterministically (no DB needed), runs the eval, writes the report, logs total cost;
  resilient to a single model failing.

### Tests — `backend/tests/extraction/` + `backend/tests/eval/` (57 new; 217 total pass)

- extraction: `test_models`, `test_parser`, `test_graph_writer` (real Neo4j testcontainer),
  `test_pipeline_with_mock_llm` + `test_pipeline_handles_extraction_failure` (real
  Postgres+Neo4j, mocked LLM), `test_real_openrouter_call` (one real API call, skips without
  a key, records a cassette), `test_openrouter_replay` (offline cassette replay for CI).
- eval: `test_ground_truth`, `test_matcher`, `test_metrics`, `test_failure_modes`,
  `test_runner_with_mock` (full eval against a fake client — the "build the eval correct
  first" discipline: a perfect mock scores 1.0).
- Committed cassette: `backend/tests/extraction/cassettes/openrouter_decision.json`.

### Config / infra

- `backend/app/config.py` — `openrouter_api_key`, `openrouter_base_url`, `extraction_model`,
  `extraction_temperature=0.0`, `extraction_max_tokens=2000`; **`extra="ignore"`** so the
  shared `.env`'s Postgres-container vars don't crash Settings locally.
- `pyproject.toml` — `httpx` promoted to a main dependency; `uv.lock` regenerated.
- `.env.example` — documented `OPENROUTER_API_KEY`. `.gitignore` — `.eval_cache/`.
- `main.py` lifespan unchanged: **no startup extraction** (one-shot script only).

---

## Eval Results (seed 42, prompt 2b-v1) — the honest numbers

| Model | Entity F1 | Relation F1 | Cost (full corpus) |
|-------|-----------|-------------|--------------------|
| `openai/gpt-4o-mini` | **0.87** | **0.62** | $0.035 |
| `anthropic/claude-3.5-haiku` | **0.91** | **0.78** | $0.347 |
| `google/gemini-2.5-flash-lite` | **0.87** | **0.57** | $0.038 |

Total three-model run: **$0.42** (target <$5). Full per-type tables, failure-mode counts,
worst-case examples, and the hand-written Discussion: `docs/eval/phase-2b-results.md`.

Top findings: entities are easy (Person/Decision/Service ~1.0); relationships separate the
models. Haiku leads but costs ~10×. Universal weak spots: `MEMBER_OF`/`OWNED_BY` (concentrated
in mega-docs that truncate at `max_tokens=2000`), Service-vs-System wrong-typing (the
schema's named soft spot), and `ABOUT` over-extraction. gemini over-generates edges
(`OWNED_BY` precision 0.14). Confidence is well-calibrated for all three. `alias_not_merged`
(10–13/model) is the entity-resolution debt made visible (e.g. `ben-smith` →
`['Ben Smith','ben','ben.smith@…','bsmith']`) — costs no F1 (alias-tolerant matcher), fixed
upstream in Phase 3B.

---

## Decisions Made

| ADR | Decision |
|-----|---------|
| [0012](docs/decisions/0012-extraction-via-openrouter.md) | Extraction via OpenRouter; JSON-mode over free-form; curated schema over JSON-Schema dump; three-model comparison |
| [0013](docs/decisions/0013-eval-ground-truth-from-narrative.md) | Eval ground truth derived from `narrative.py`, not a hand-labelled file |

Key in-code calls: eval judges the extractor's **output** (not the Neo4j graph) so eval
correctness is independent of graph-writer correctness and runs with only an API key;
pipeline **commits per event** (unlike the seeder) so a long batch survives a late failure;
the graph writer is best-effort on identity (`Alice Chen`/`@alice` → two nodes), which the
eval measures (`alias_not_merged`) without penalising.

---

## Deviations from Spec

1. **`google/gemini-2.0-flash` → `google/gemini-2.5-flash-lite`.** OpenRouter has retired
   2.0-flash; the cheap-tier successor was used. Noted in ADR 0012, the design doc, and the
   report. The model *tier* (cheap, capable) is what the comparison turns on.
2. **`Settings(extra="ignore")`** added — the shared local `.env` carries Postgres *container*
   credentials (`POSTGRES_USER`/`DB`) that aren't app settings; prior phases never hit this
   because they ran inside Docker where those vars aren't set.
3. **Eval reads the corpus from the generator, not Postgres** — deterministic, DB-free,
   reproducible. `extract_all.py` (the real pipeline) does read Postgres.
4. **`max_tokens=2000` truncates the few mega-docs** (org chart, dependency map, service
   catalog) → 1–6 parse failures per model and depressed `MEMBER_OF`/`OWNED_BY` recall. Kept
   at the specced 2000 and reported honestly; the documented fix is chunking (future work).

---

## Open Questions

1. **Chunking the mega-docs (highest-ROI next change).** `MEMBER_OF`/`OWNED_BY`/`Team` are
   hostage to one large document each parsing inside the token cap. Chunking-with-overlap is
   designed for in the doc; the idempotent writer already supports it.
2. **`ABOUT` ground-truth strictness.** GT lists only a decision's declared subjects, but the
   text mentions related entities (`D-0007` mentions `user-store`); models extract those as
   `ABOUT`, hurting precision. Decide in Phase 3 whether "mentioned-in" should count.
3. **`CONTRADICTS`/`AUTHORED`/`MENTIONS` are out of this eval** (Message-anchored). When the
   message-grounding pass lands, extend ground truth and the matcher accordingly.
4. **Confidence threshold for the write path.** Calibration is good; pick the cut that trades
   recall for precision once the query engine (Phase 3) shows what it needs.

---

## Definition of Done Check

- ✓ `docs/design/extraction-pipeline.md` ≥1500 words; all sections; prompt verbatim (>150 lines)
- ✓ ADRs 0012 and 0013 written per template
- ✓ Extraction module produces valid `ExtractionResult` from a real event via OpenRouter
  (`test_real_openrouter_call.py` — verified, cassette committed)
- ✓ Graph writer writes nodes/edges with provenance; idempotent on re-extraction (real-Neo4j test)
- ✓ `extraction_runs` populated for every attempt; failed extractions don't pollute the graph
- ✓ Eval ground truth derived from `narrative.py` (no hand-labelled file)
- ✓ Three-model eval runs end-to-end → `docs/eval/phase-2b-results.md`
- ✓ Total eval cost logged and reported: **$0.42** (< $5 budget)
- ✓ `uv run pytest` — **217 passed** (160 prior + 57 new)
- ✓ `uv run mypy backend/` — strict, clean (54 source files)
- ✓ `ruff check` clean on all new files
- ✓ Honest numbers; Discussion names the top-3 failure modes per model with concrete examples
- ✓ CLAUDE.md, HANDOFF.md, docs/README.md, README.md, .env.example updated; no startup extraction

---

## State of the Codebase

**Works**: 217 tests pass (`uv run pytest`); mypy strict-clean; ruff-clean on new files. The
extraction pipeline turns Postgres events into a provenance-tagged Neo4j graph via OpenRouter
and audits every attempt; the eval harness scores three models against generator-derived
ground truth and emits a Markdown report. Real-DB tests use testcontainers (Postgres +
Neo4j) and skip gracefully without Docker; the one real-API test skips without a key and
replays a committed cassette in CI.

**Populating the graph is on-demand** (`extract_all.py`), never at startup. The graph is
empty until that script runs against a seeded Postgres + a reachable Neo4j.

**Does not exist yet**: query engine (Phase 3), entity resolution (Phase 3B), agent layer
(Phase 4), frontend (Phase 4B). `check_provenance.py` remains a Phase-4 stub.

---

## Next Subphase

**Phase 3A — second source-type ingestion + temporal edges** (preparing for Phase 3B entity
resolution). Add a second ingestion source-type beyond the synthetic seed, and start
populating the temporal edge properties (`valid_from`/`valid_to`, `deprecated_at`) the schema
reserves, so the temporal killer queries (KQ2/KQ4) have the data they filter on. Carry
forward Open Question #1 from Phase 2A (evaluate "last month"/"last quarter" windows relative
to `REFERENCE_NOW`) and #1 above (chunk the mega-docs before relying on `MEMBER_OF`/`OWNED_BY`
recall).
