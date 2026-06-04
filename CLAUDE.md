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
| `SUPERSEDES` *(3B)* | Decision → Decision | Change-timeline supersession (KQ4) |

**Identity**: Service/System/Team keyed by `canonical_name`; Person by `canonical_id`; Decision by UUID `id`; Message by `id = "source_id:external_id"`. **Provenance**: every node carries `source_event_ids` (FKs into the Postgres events log); every edge carries `confidence` + `extracted_by`. **Entity resolution is Phase 3** — the v1 write path is best-effort and may create duplicate nodes the schema is designed to later merge.

**Phase 3B updates to this schema**: `SUPERSEDES` (Decision→Decision) added to the closed vocabulary (10 edge types now). Decision nodes now carry **populated** `valid_from`/`valid_to`/`status` (the temporal enricher fills them; extraction left them empty). `Message` nodes and `CONTRADICTS` edges — previously never created — are populated by the Phase-3B contradiction pass (`backend/app/contradiction/`). Resolved-view queries rely on the edge-projection cleanup (`backend/app/resolution/projection.py`) copying loser edges onto canonical winners, because 3A's merger is non-destructive and does not migrate edges.

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

## Extraction Pipeline (Phase 2B)

The graph is populated by an **LLM extraction pipeline**, run **on demand** — never at
startup (it is expensive and idempotent; running it in the FastAPI lifespan would be
wrong). Full rationale: [docs/design/extraction-pipeline.md](docs/design/extraction-pipeline.md).
ADR 0012 (OpenRouter + JSON-mode + curated schema), ADR 0013 (eval ground truth from
`narrative.py`).

**Flow**: Postgres `events` → prompt builder → LLM (OpenRouter, JSON-mode) → strict
Pydantic validation → Neo4j `MERGE` with provenance → `extraction_runs` audit row.

**Extractor** — `backend/app/extraction/`: `models.py` (the LLM's flat output shape, every
item carries a required `evidence_quote`), `prompts.py` (system prompt + curated schema +
2 few-shot examples; `PROMPT_VERSION`), `client.py` (`OpenRouterClient`, async httpx,
429/503 retry, logs `usage.cost`), `parser.py` (strict parse → typed `ExtractionParseError`),
`graph_writer.py` (idempotent `MERGE`, `source_event_ids` set-union, edge confidence/
`extracted_by`/`source_event_id`), `pipeline.py` (`ExtractionPipeline`; per-event
`extraction_runs` lifecycle, failed-by-default, bounded-concurrency `extract_all`).

**Eval harness** — `backend/app/eval/`: `ground_truth.py` (derives the gold set from
`company.py`+`narrative.py` — no hand-labelled file), `matcher.py` (alias-tolerant
canonicalisation; Phase 3B makes this redundant), `metrics.py` (P/R/F1, per-type),
`failure_modes.py` (named taxonomy + worst-case examples + confidence calibration),
`runner.py` (`run_eval`, disk-cached per-event responses), `report.py` (Markdown).

**Three-model comparison** (via OpenRouter): `openai/gpt-4o-mini`,
`anthropic/claude-3.5-haiku`, and `google/gemini-2.5-flash-lite` (substituted for the
specced `gemini-2.0-flash`, which OpenRouter retired). Latest results — entity/relation F1:
gpt-4o-mini 0.87/0.62, haiku 0.91/0.78, gemini-2.5-flash-lite 0.87/0.57; full run $0.42:
[docs/eval/phase-2b-results.md](docs/eval/phase-2b-results.md).

**CLIs**: `uv run python backend/scripts/extract_all.py --model <m> [--limit N]` (reads
Postgres, writes Neo4j); `uv run python backend/scripts/run_eval.py --models <a,b,c>
--output docs/eval/phase-2b-results.md` (builds the corpus deterministically, no DB
needed; `--no-cache` forces fresh calls). `OPENROUTER_API_KEY` lives in `.env`.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+, managed with `uv` |
| API | FastAPI 0.115+, Pydantic v2 |
| Graph DB | Neo4j 5.x community (APOC plugin) |
| Relational + Vector DB | Postgres 16 + pgvector extension |
| ORM | SQLAlchemy 2.x async |
| Frontend (Phase 3C) | React 18 + Vite + TanStack Query + react-force-graph-2d + Tailwind CSS |
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

## Production Verification (apply at the end of every subphase, from 3A on)

Three Docker bugs hit Phases 1B, 1C, and 2B because development-environment success does not
prove production-container success. Run this checklist against a clean Docker volume at the
end of every subphase:

1. **Dependencies sync.** If `pyproject.toml` changed, a clean image rebuild must install the
   new packages. Verify: `docker compose exec backend python -c "import <pkg>; print(<pkg>.__version__)"`.
2. **Directory copies.** If a new directory was added under `backend/`, the Dockerfile must
   `COPY` it (or it sits under an already-copied parent like `backend/app/`). Verify:
   `docker compose exec backend ls /app/<dir>`.
3. **Environment passthrough.** If a new env var was added to settings/`.env`, the backend
   service's `environment:` block in `docker-compose.yml` must include it. Verify:
   `docker compose exec backend env | grep <VAR>`.
4. **End-to-end smoke against real services.** Run the new code's entry point against the live
   stack with a small sample. Unit tests do not prove a new process boundary works.

## Entity Resolution (LOCKED IN — Phase 3A)

Resolves the duplicate nodes the best-effort write path creates (`@alice`, `Alice Chen`,
`alice.chen@northwind.io` → one Person). Full rationale:
[docs/design/entity-resolution.md](docs/design/entity-resolution.md). ADR 0014 (tiered model),
ADR 0015 (audit table). Module: `backend/app/resolution/`.

- **Three tiers** (`resolver.py`): **Tier 1** auto-merges when a deterministic exact-identity
  rule fires (shared email/handle, curated known-alias, equal/former canonical name) —
  authoritative over embeddings. **Tier 2** sends the close-but-no-rule band (cosine ≥ 0.75) to
  `claude-3.5-haiku`. **Tier 3** leaves the rest alone. Embeddings are local
  `BAAI/bge-small-en-v1.5` (sentence-transformers), never a hosted API.
- **`MERGE_INTO` edge model** (`merger.py`): merges are **non-destructive** —
  `(loser)-[:MERGE_INTO {confidence, tier, created_at}]->(winner)`, `loser.status = "merged"`,
  loser's `source_event_ids` unioned onto the winner. Queries see the resolved view with
  `WHERE n.status <> "merged"`; dropping that clause shows the fragmented view. Reversible.
- **`merge_decisions` audit table** (Postgres; ADR 0015): one row per resolution *attempt*
  (auto_merge / llm_merge / llm_no_merge / below_threshold) with tier, rules matched, embedding
  similarity, and LLM reasoning. A non-merge has no edge, so the record lives in Postgres.
- **Eval** (`app/eval/resolution_eval.py`): ground truth is `narrative.ALIAS_GROUPS` (positives)
  + `LOOK_ALIKE_PAIRS` (negatives), the same single-source-of-truth discipline as 2B (ADR 0013).
  Seeds a deterministic fragmented graph, resolves it, scores precision / recall / false-merge /
  missed-merge over node pairs. CLIs: `backend/scripts/resolve_entities.py [--node-type T]
  [--dry-run]`, `backend/scripts/run_resolution_eval.py --output docs/eval/phase-3a-resolution-results.md`.
- **Run modes**: post-merge batch this phase; the resolver is a standalone module built to be
  called from the at-write-time path in Phase 4 too.

## Query Engine (LOCKED IN — Phase 3B)

The four killer queries are implemented as typed Cypher over the resolved, temporally-enriched
graph. Full rationale: [docs/design/query-engine.md](docs/design/query-engine.md). ADR 0016
(temporal model + `as_of` + `SUPERSEDES`), 0017 (Decision consolidation), 0018 (provenance shape),
0019 (contradiction/Message population). Modules: `backend/app/queries/`, `backend/app/temporal/`,
`backend/app/contradiction/`, `backend/app/resolution/{consolidator,projection}.py`.

- **The four KQs as endpoints** (FastAPI, `backend/app/api/queries.py`, registered in `main.py`):
  `GET /api/queries/multihop-ownership?decision_id=D-0006` (KQ1),
  `GET /api/queries/contradictions?window_days=30` (KQ2),
  `GET /api/queries/blast-radius?service=payments-api&max_depth=5` (KQ3),
  `GET /api/queries/change-tracking?target=auth-service&window_days=90` (KQ4). 404 if the seed
  entity is absent. Each returns a `QueryResult` JSON.
- **`as_of` convention**: every temporal query takes `as_of: datetime | None = None` defaulting to
  `synthetic.REFERENCE_NOW` for dev/eval; production passes wall-clock now. Windows = `as_of - window`.
- **`QueryResult[T]` shape** (`backend/app/queries/result_types.py`): `value: T` +
  `provenance: QueryProvenance` (`by_element: dict[str, list[event_uuid]]` + `all_event_ids`).
  Provenance is structural, not optional — every KQ populates it from edge `source_event_id` / node
  `source_event_ids`.
- **Resolved-view discipline**: every KQ filters `WHERE n.status <> 'merged'`; no KQ traverses
  `MERGE_INTO`. Loser edges are made reachable by the projection cleanup, run after resolution +
  consolidation.
- **Pipeline order** (also the integration eval order): seed → extract → resolve entities →
  consolidate decisions → project edges → **enrich temporal → ingest messages + detect
  contradictions** → query. (Temporal enrichment precedes contradiction detection so the detector
  filters on normalised decision statuses, not raw extraction output.)
- **Integration eval** lives at `backend/app/eval/query_eval.py` (run via
  `backend/scripts/run_query_eval.py --output docs/eval/phase-3b-query-results.md`); it runs the full
  pipeline and scores all four KQs against expected answers hand-derived from `narrative.py`, using
  `claude-3.5-haiku` for reliability. Demo CLI: `backend/scripts/run_killer_queries.py`.

## 14-Subphase Plan

| # | Phase | Description | Status |
|---|-------|-------------|--------|
| 1A | Foundation | Scaffolding, documentation infrastructure, session context files | **Complete** |
| 1B | Neo4j Schema | Node labels, relationship types, constraints, Cypher migrations | **Complete** |
| 1C | Postgres Models | SQLAlchemy models, Alembic migrations, pgvector column setup | **Complete** |
| 2A | Synthetic Generator | Adversarial hand-curated generator → raw Postgres events (graph stays empty) | **Complete** |
| 2B | Extraction + Eval | LLM extraction pipeline (events→Neo4j w/ provenance) + 3-model eval harness (P/R/F1 + failure modes). Folds the originally-separate entity-extraction (2D) and graph-write (2E) work. | **Complete** |
| 2C | Document Parser | Decision doc and meeting note parser (source-type-specific normalisation) | Pending |
| 2D | Entity Extraction | *(folded into 2B)* | **Complete** |
| 2E | Graph Write Path | *(folded into 2B graph_writer; entity dedup deferred to 3B)* | **Complete** |
| 3A | Entity Resolution | Tiered resolver (rules → LLM → no-merge), MERGE_INTO edges, `merge_decisions` audit table, eval vs `ALIAS_GROUPS` | **Complete** |
| 3B | Query Engine + Temporal | Multi-hop ownership/dependency traversal, temporal edges, contradiction detection, killer-query Cypher | **Complete** |
| 3C | Frontend + Demo | React frontend (4 pages + react-force-graph-2d), 3 new backend API endpoints, Docker integration, demo script | **Complete** |
| 3D | Semantic Search | Embedding pipeline, pgvector indexing, hybrid graph-vector queries | Pending |

> **Resequencing note (Phase 3A):** entity resolution was pulled forward to 3A because the
> fragmented nodes from 2B's best-effort write path block the killer-query traversals. The
> originally-planned 3A "multi-hop traversal" and "temporal queries" fold into **3B**. The
> closed schema and the 4 killer queries are unchanged.
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

## Frontend (LOCKED IN — Phase 3C)

The React frontend lives in `frontend/`. It is a demo-grade app — no auth, no real-time
features, no production hardening. Its job is to make the backend's capabilities visible in
a 3-minute walkthrough.

### Four pages

| Route | Job |
|-------|-----|
| `/` | Landing — single-column (max-w 720px), KQ list with "Try it" links, no hero |
| `/graph` | Full-page react-force-graph-2d canvas + sidebar; resolved/fragmented toggle; node hover/click; source-event modal |
| `/queries` | KQ explorer — 2-pane layout; all four KQs with params; answer + provenance chain + source events |
| `/audit` | Merge-decision audit trail — filterable table (tier, decision type, node type); expandable LLM reasoning |

### Tech stack

- **Vite 6 + React 18 + TypeScript strict** — Vitest + React Testing Library for tests
- **React Router v6** — client-side routing
- **TanStack Query v5** — all API state; `staleTime: 30s` for graph data, `0` for query results, `∞` for events (immutable)
- **react-force-graph-2d** — canvas-based force graph; `nodeCanvasObject` for custom rendering; `linkCanvasObject` for dashed MERGE_INTO edges
- **Tailwind CSS 3** — fully customized; theme tokens override defaults; **no shadcn/ui**
- Custom primitives only: Button, Badge, Skeleton, ProgressBar, ErrorMessage

### Design conventions (see ADR 0020 for full rationale)

- Dark mode default (`html.dark`); `#0C0E12` background; `#E2E8F0` primary text
- 7-color palette: bg / surface / s2 / border / txt / txt-muted / accent
- Node colors: Decision=amber, Service=blue, System=gray, Person=green, Team=lavender, Message=slate
- Monospace (JetBrains Mono) for: IDs, timestamps, UUIDs, code-like data only
- **No**: gradient backgrounds, centered hero, glass-morphism, shadcn defaults, icons as decoration

### New backend endpoints (Phase 3C)

- `GET /api/graph?view=resolved|fragmented` — `backend/app/api/graph.py`
- `GET /api/events/{event_id}` — `backend/app/api/events.py`
- `GET /api/audit/merge-decisions` — `backend/app/api/audit.py`

All three registered in `main.py`. CORS allows `localhost:3000` and `localhost:5173`.

### Docker

- `frontend/Dockerfile` — multi-stage: node:20-alpine build, nginx:1.27-alpine serve
- `frontend/nginx.conf` — proxies `/api/` → `http://backend:8000`, SPA routing via `try_files`
- `docker-compose.yml` — `frontend` service on port 3000, depends on `backend`
- `docker compose up` brings up the full stack (Neo4j, Postgres, backend, frontend)

---

## Known Gaps and Deferred Decisions

These are intentional omissions, not unfinished work. They are named here so future sessions do not accidentally "fix" them without a deliberate decision.

1. **No observability beyond structured logs** — no metrics (Prometheus/StatsD), no distributed tracing (OpenTelemetry). Structured JSON logs are the only signal. ADR 0006 documents the upgrade path to OTel.

2. **Background worker architecture TBD (Phase 4)** — the ingestion pipeline and embedding jobs will eventually need async workers. Whether to use Celery, arq, or a simple asyncio task queue is deferred. Do not introduce a task queue before Phase 4 without an ADR.

3. **No rate limiting** — the API accepts unlimited requests. Acceptable for a demo; a production system would add rate limiting at the reverse proxy (nginx/Caddy) or API gateway layer.

4. **No auth on `/health`** — the health endpoint is intentionally unauthenticated. It exposes DB connectivity state to anyone with network access. Acceptable on a private Docker network; would need a bearer token or IP allow-list in production.

5. **No CI pipeline** — there is no GitHub Actions, GitLab CI, or equivalent. Tests are run locally via `uv run pytest`. Adding CI is straightforward (one YAML file) but out of scope for a solo portfolio project until the repo is public.
