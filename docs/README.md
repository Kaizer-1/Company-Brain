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
| [decisions/0014-entity-resolution-tiered-confidence.md](decisions/0014-entity-resolution-tiered-confidence.md) | Tiered-confidence entity resolution (deterministic rules → LLM adjudicator → no-merge); local sentence-transformers embeddings over a hosted API; non-destructive MERGE_INTO edges over deletion |
| [decisions/0015-merge-decisions-audit-table.md](decisions/0015-merge-decisions-audit-table.md) | Every resolution attempt (merge and non-merge) recorded in a Postgres `merge_decisions` table; why Postgres not a Neo4j edge; seed for a future human-review UI |
| [decisions/0016-temporal-query-model.md](decisions/0016-temporal-query-model.md) | `as_of` parameter defaulting to `REFERENCE_NOW` for reproducible temporal windows; `SUPERSEDES` edge pulled into the schema; why wall-clock now is the wrong default |
| [decisions/0017-multi-source-decision-consolidation.md](decisions/0017-multi-source-decision-consolidation.md) | Content-similarity Decision consolidation (0.85 cosine + temporal proximity + distinct-formal-id guard) reusing the 3A MERGE_INTO mechanism; why it differs from entity resolution |
| [decisions/0018-query-result-provenance.md](decisions/0018-query-result-provenance.md) | `QueryResult[T]` with a structural (non-optional) `QueryProvenance` of source-event IDs; why grounding is a type, not a convention |
| [decisions/0019-contradiction-message-population.md](decisions/0019-contradiction-message-population.md) | Dedicated Phase-3B contradiction pass (Message ingestion + LLM-adjudicated CONTRADICTS) for KQ2; why not extend extraction or compare at query time |
| [decisions/0020-frontend-design-philosophy.md](decisions/0020-frontend-design-philosophy.md) | Software-tools aesthetic, custom primitives over shadcn, dark-mode default, anti-pattern list; why the modal AI-slop frontend undermines the backend work |
| [decisions/0021-embedding-dimension-migration.md](decisions/0021-embedding-dimension-migration.md) | Phase 3D migration of event_embeddings from vector(1536) to vector(384); why bge-small not OpenAI; defensive row-count guard pattern for re-embedding migrations |
| [decisions/0022-hybrid-search-blend-weights.md](decisions/0022-hybrid-search-blend-weights.md) | Linear blend 0.7/0.3 (vector + graph signal); why not LLM rerank for Phase 3D; graph_signal normalisation; tuning path and production upgrade to BM25 fusion |
| [decisions/0023-typed-tools-not-generated-cypher.md](decisions/0023-typed-tools-not-generated-cypher.md) | Phase 4A: the agent calls five typed Python functions, never LLM-generated Cypher; injection/parse/wrong-traversal surface eliminated; enumerable testable behaviour; the "yes I could, here's why I didn't" defense |
| [decisions/0024-route-then-execute-architecture.md](decisions/0024-route-then-execute-architecture.md) | Phase 4A: constrained route classifier then fixed branch then synthesis, vs an end-to-end tool-calling loop; per-stage testability, bounded cost/latency, route accuracy as one metric; tradeoff is no cross-tool chaining |
| [decisions/0025-provenance-verification-loop.md](decisions/0025-provenance-verification-loop.md) | Phase 4A: verify-then-retry (max 2) Python check that every cited event id is in the tool's provenance; self-heals stray citations, flags persistent failures, never lets a fabricated citation through |
| [decisions/0026-sse-not-websockets.md](decisions/0026-sse-not-websockets.md) | Phase 4B: SSE over fetch+reader chosen over WebSockets for the streaming ask endpoint; one-way push, POST body support, rollback via one constant flip |
| [decisions/0027-stream-synthesis-only.md](decisions/0027-stream-synthesis-only.md) | Phase 4B: only synthesis is token-streamed; route/tool/verify emit one event each; LangGraph astream not used (would leak internals through API) |
| [decisions/0028-structural-tools-scope.md](decisions/0028-structural-tools-scope.md) | Phase 4C: four structural tools not seven (recency/orphans/provenance fold into parameters); typed parameterised Cypher with `$type IN labels(n)` + `type(r)=$edge` (no label interpolation); heterogeneous case-insensitive identity; status normalisation; path-finding/generated-Cypher deferred |
| [decisions/0029-router-redesign-two-stage-conceptual.md](decisions/0029-router-redesign-two-stage-conceptual.md) | Phase 4C: router prompt restructured as two-stage conceptual routing (shape → route) in one LLM call with 20 few-shots and an explicit KQ-vs-structural priority rule, to disambiguate ten routes reliably |
| [decisions/0030-verification-skip-for-structural.md](decisions/0030-verification-skip-for-structural.md) | Phase 4C: verification skips the inline-citation check only when the route is structural AND no events were returned (e.g. an aggregate count); preserves the grounding contract via the deterministic typed query; strict check kept everywhere a citation is possible |
| [decisions/0031-incremental-reconciliation.md](decisions/0031-incremental-reconciliation.md) | Phase 5A: per-event incremental reconciliation (not full rebuild); hybrid scoping — reuse cheap idempotent batch stages, truly scope only the cost-bearing ones (extraction skip-guard, resolution to newly-created fragments, scoped contradiction); scope derived from the graph by provenance |
| [decisions/0032-idempotency-contract.md](decisions/0032-idempotency-contract.md) | Phase 5A: the layered idempotency contract — endpoint dedup, orchestration guard, extraction skip-guard, MERGE-everywhere; what "identical state" means given append-only audit logs; verified three ways by the load-bearing idempotency test |
| [decisions/0033-single-writer-lock.md](decisions/0033-single-writer-lock.md) | Phase 5A: one in-process `asyncio.Lock` serialises ingestions (read-modify-write across the graph isn't made atomic by MERGE alone); 503 backpressure on timeout; production path is per-canonical-node locking + Postgres advisory/Kafka partitioning |

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
| [design/entity-resolution.md](design/entity-resolution.md) | The tiered entity resolver: fragmentation problem, three-tier decision logic, candidate generation, local embedding strategy, Tier 1 rules, the LLM adjudicator prompt, the MERGE_INTO edge model, eval methodology, and honest limitations |
| [design/query-engine.md](design/query-engine.md) | The Phase-3B query engine: the four KQs restated with Cypher + unresolved-failure modes, the temporal model + `as_of`, Decision consolidation, the contradiction/Message pass, provenance shape, the edge-projection cleanup, performance, and the integration-eval methodology |
| [design/frontend-architecture.md](design/frontend-architecture.md) | Phase-3C frontend architecture: tech stack rationale (Vite+React+TanStack Query+react-force-graph-2d), four-page structure, data-fetching strategy, styling conventions (design tokens, anti-patterns), nginx proxy pattern, production delta |
| [design/semantic-search.md](design/semantic-search.md) | Phase-3D semantic search: bge-small-en-v1.5 + pgvector HNSW, 7-stage hybrid retrieval pipeline, linear blend rationale, module structure, eval methodology, production-scale changes |
| [design/agent-architecture.md](design/agent-architecture.md) | Phase-4A agent: LangGraph route-then-execute-then-verify state machine, node-by-node walkthrough, typed-tools rationale, provenance verification loop, cost/latency, single-model choice, out-of-scope cuts, and the production scale path (caching, streaming, multi-turn, access control) |
| [design/agent-streaming.md](design/agent-streaming.md) | Phase-4B streaming: SSE protocol spec, event sequence, callback-to-queue bridge, frontend integration, perceived vs actual latency, what is not changed |
| [design/structural-tools.md](design/structural-tools.md) | Phase-4C structural tools: the four graph-native tools (get_entity, neighbors, enumerate, aggregate), the question classes they close, parameter-design-over-route-proliferation, the heterogeneous identity + parameterised-label Cypher strategy, the verification skip, honest sparsity limits, and the deliberate path-finding gap |
| [design/incremental-reconciliation.md](design/incremental-reconciliation.md) | Phase-5A live ingestion: the per-event incremental pattern (8 scoped stages), hybrid scoped-vs-batch tradeoffs, the layered idempotency contract + its verification, MERGE-everywhere, the single-writer concurrency model + production path, conflict resolution (contradiction-as-evidence), the 10× scale story, and how the 4C structural tools verify reconciliation with exact counts |

---

## Eval

Generated quality reports. Numbers are honest and reproducible from the deterministic seed.

| File | Summary |
|------|---------|
| [eval/phase-2b-results.md](eval/phase-2b-results.md) | Three-model extraction eval (gpt-4o-mini, claude-3.5-haiku, gemini-2.5-flash-lite): per-type precision/recall/F1, failure-mode counts, worst-case examples, cost, and a hand-written Discussion |
| [eval/phase-3a-resolution-results.md](eval/phase-3a-resolution-results.md) | Entity-resolution eval vs `ALIAS_GROUPS` + `LOOK_ALIKE_PAIRS`: precision/recall/false-merge/missed-merge overall and per type, tier breakdown, correct/missed/false merge examples, cost, and a hand-written Discussion |
| [eval/phase-3b-query-results.md](eval/phase-3b-query-results.md) | Killer-query integration eval: all four KQs **pass** on the live LLM-extracted graph (111 events, provenance valid); expected answers per KQ from `narrative.py`; hand-written Discussion on the ordering bug the run caught, per-query reliability, and extraction sensitivity |
| [eval/phase-3d-search-results.md](eval/phase-3d-search-results.md) | Semantic search eval: 20 questions, Recall@10=0.942, MRR=0.910; warm latency ~149ms; 3 partial misses documented with failure-mode analysis |
| [eval/phase-4a-agent-results.md](eval/phase-4a-agent-results.md) | Agent eval: 30 questions across five routes + refusals; route accuracy 1.000, refusal 1.000, citation overlap 0.608, first-try verification 0.864, mean cost $0.003/q; latency missed the 4s target (two sequential LLM calls) with an honest failure-mode breakdown incl. the one retry-exhausted question |
| [eval/phase-4b-streaming-results.md](eval/phase-4b-streaming-results.md) | Streaming perceived-latency eval: 10 questions, measures time-to-first-synthesis-token; placeholder until live run fills in numbers |
| [eval/phase-4c-structural-results.md](eval/phase-4c-structural-results.md) | Structural-tools eval: 42 questions (30 prior + 12 new across get_entity/neighbors/enumerate/aggregate); route accuracy 1.000 overall and 1.000 on the structural routes, citation overlap 0.541, first-try verification 0.812, refusal 1.000, mean cost $0.0052/q; latency still misses the 4s target (two sequential LLM calls) with an honest Discussion incl. the q37 retry outlier; acceptance test (all 13 employees via `enumerate`) passes |
| [eval/phase-5a-ingestion-results.md](eval/phase-5a-ingestion-results.md) | Live-ingestion eval: 11 cases (new-doc/new-slack/resolution/idempotency/failure/structural-acceptance) ingested against the populated graph and reverted; 100% success and pass rate, mean latency 5.8s (≤8s target), mean cost $0.0031/event; structural acceptance (Person 13→14) verified; honest Discussion of the 15s resolution tail (sequential adjudication) and scope limits |

---

## Demo

Scripts and artefacts for the demo walkthrough.

| File | Summary |
|------|---------|
| [demo/3-minute-walkthrough.md](demo/3-minute-walkthrough.md) | Literal 3-minute demo script with beat-by-beat timing; setup instructions; fallback answers for KQ2/KQ3 if interviewer asks |

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
| [interview-prep/phase-3a-readiness.md](interview-prep/phase-3a-readiness.md) | 10 Q&A pairs + 5 whiteboard concepts: three tiers vs one threshold, @alice/Alice Chen walkthrough, MERGE_INTO vs deletion, local embeddings vs API, false/missed-merge rates, the adjudicator prompt, conservative LLM failure, Postgres vs Neo4j for the audit, scaling to 1M |
| [interview-prep/phase-3b-readiness.md](interview-prep/phase-3b-readiness.md) | 10 Q&A pairs + 5 whiteboard concepts: KQ1 walkthrough, the `status<>'merged'` filter + edge projection, `as_of` vs `datetime.now()`, Decision consolidation vs entity resolution, KQ3 complexity at scale, why the eval is end-to-end, tracing provenance to Postgres, KQ4 on the unresolved graph, missed-edge impact on KQ3 |
| [interview-prep/phase-3c-readiness.md](interview-prep/phase-3c-readiness.md) | 10 Q&A pairs + 5 whiteboard concepts: react-force-graph vs D3-scratch, resolved/fragmented toggle mechanics, why the audit page, full provenance flow, scaling the graph view past 1000 nodes, dark-mode default rationale, KQ1 click-through walkthrough, non-optional provenance, audit pagination approach, what's next |
| [interview-prep/phase-3d-readiness.md](interview-prep/phase-3d-readiness.md) | 10 Q&A pairs + 5 whiteboard concepts: local model choice, bge-small specifics, HNSW parameters, linear blend vs LLM rerank, graph signal value, filter/fanout interaction, placeholder table rationale, search vs KQs, production scale changes, ablation methodology |
| [interview-prep/phase-4a-readiness.md](interview-prep/phase-4a-readiness.md) | 12 Q&A pairs + 6 whiteboard concepts: LangGraph vs LangChain, typed tools vs generated Cypher, provenance verification, the five-route enum, misclassification handling, cost-per-question, scaling to 10×, agent vs vanilla RAG, what's missing for production, the read-only safety boundary, the verify-then-retry loop, how-do-you-know-it-works |
| [interview-prep/phase-4b-readiness.md](interview-prep/phase-4b-readiness.md) | 8 Q&A pairs: why streaming / perceived vs actual latency, SSE vs WebSockets, why stream synthesis only, verify-retry + streaming interaction, filter validation guard design, empty-result UX, rollback plan |
| [interview-prep/phase-4c-readiness.md](interview-prep/phase-4c-readiness.md) | 10 Q&A pairs: four tools not three/five, KQ1-vs-neighbors disambiguation, recency/orphans as enumerate parameters, the verification skip, the heterogeneous-identity surprise, why not generated Cypher, cost/latency impact, parameterised dynamic labels, production changes, the path-finding gap |
| [interview-prep/phase-5a-readiness.md](interview-prep/phase-5a-readiness.md) | 12 Q&A pairs: incremental vs batch, how scoping actually works, the idempotency contract + verification, MERGE-vs-CREATE, the demo moment, structural-tool verification, stage-failure handling, conflict resolution (contradiction-as-evidence), why one lock + the production concurrency path, cost per ingestion, and how 5A delivers the self-updating-graph claim |
