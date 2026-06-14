# Company Brain — Semantic Search (Phase 3D)

> **Status**: Implemented in Phase 3D. Retrieval layer built on `BAAI/bge-small-en-v1.5`
> + pgvector HNSW + linear graph-signal blend. ADR 0021 (dimension migration),
> ADR 0022 (blend weights). Eval results: `docs/eval/phase-3d-search-results.md`.

---

## Why this phase exists

The four killer queries (Phases 1B–3B) answer questions whose *shape* you know in advance:
"who owns the service downstream of decision X?" is a typed graph traversal. But the demo
and Phase 4A's agent need to handle questions that *don't fit a named template* — "what's
the deal with auth?" or "who was talking about billing last month?" These need a retrieval
layer that finds relevant events by meaning, not by a pre-declared traversal.

Semantic search is that bridge: given any natural-language question, find the events that
*mention* the right things. It is deliberately scoped as the infrastructure layer — not the
answer generation (that's Phase 4A), not the template routing (also Phase 4A). Phase 3D
produces the `hybrid_search` function that Phase 4A's agent will call as one of its tools.

---

## Architecture

```
query string
    │
    ▼
[1] embed_query()                    bge-small-en-v1.5, same singleton as resolution
    │  ← query_embedding_ms
    ▼
[2] pgvector HNSW cosine search      top N = 3k (or 5k if filter active)
    │  ← vector_search_ms
    ▼
[3] fetch event metadata             Postgres: content, source_kind, occurred_at
    │
    ▼
[4] apply filters                    source_kind / after / before (Python, cheap)
    │
    ▼
[5] Neo4j entity lookup              batch Cypher: which canonical entities did each
    │  (one Cypher call for N events) event assert?
    │
    ▼
[6] entity_type filter               keep only events with matching entity labels
    │
    ▼
[7] linear-blend rerank              final_score = 0.7*cosine + 0.3*graph_signal
    │  ← rerank_ms
    ▼
top-k SearchHit objects              with per-stage timing
```

---

## Module structure

`app/search/` mirrors `app/resolution/` intentionally — same pattern:

| File | Role |
|------|------|
| `config.py` | All tunable constants: blend weights, batch sizes, fanout multipliers |
| `embedder.py` | Async wrappers for `embed_query` and `embed_batch`; imports the shared `embed_texts` from `resolution/embeddings.py` — no second model |
| `indexer.py` | `embed_events()` pipeline step: reads un-embedded events, batches through bge-small, writes to `event_embeddings` |
| `retriever.py` | `hybrid_search()`: the full 7-stage pipeline above |
| `schemas.py` | `SearchRequest`, `SearchFilters`, `SearchHit`, `SearchResult` — all explicit fields, no computed properties |
| `router.py` | `POST /api/search` FastAPI endpoint |

---

## Embedding model

`BAAI/bge-small-en-v1.5`, 384 dimensions, local CPU inference via `sentence-transformers`.
The decision to use this model is documented in ADR 0021 and captured in the entity-resolution
design doc (where it first appears in Phase 3A). Key properties:

- **Same model instance as resolution**. `resolution/embeddings.py` holds the module-level
  singleton; `search/embedder.py` imports and wraps it. Only one instance is loaded per
  process. There is no second model.
- **Local, free, deterministic**. Vectors are byte-stable across runs on the same machine.
  The eval numbers reproduce exactly if you re-run with the same corpus.
- **384 dimensions**. The Phase 1C `vector(1536)` placeholder (sized for OpenAI
  text-embedding-3-small) was migrated to `vector(384)` in Alembic migration 0004.
  See ADR 0021 for rationale and the production upgrade path (bge-large, then hosted API).

### Indexer (`embed_events`)

Called as a pipeline step: after extraction, before entity resolution. Reads events with no
row in `event_embeddings`, embeds in batches of 32 (matching resolution's batch size), and
upserts via `EventEmbeddingRepository`. Idempotent: re-running skips already-embedded events.
`session.commit()` is called explicitly inside `embed_events()` so the embeddings are visible
to subsequent sessions in the same pipeline invocation.

---

## Retrieval algorithm

### Stage 2 — vector search

pgvector's `<=>` cosine distance operator over the HNSW index on `event_embeddings.embedding`.
The HNSW index was recreated (in migration 0004) with the same parameters as the original:
`m=16, ef_construction=64`. These are pgvector's defaults, appropriate for recall-latency
balance up to ~1M vectors. The cosine similarity for each candidate is `1 - distance`.

**Fanout**: the candidate pool is `BASE_FANOUT=3` × k (default) or `FILTER_FANOUT=5` × k
when any filter is active. The wider pool provides headroom so that filtering doesn't
deplete the result set below k. This is the only structural difference between the filtered
and unfiltered code paths — no separate index per filter dimension.

### Stage 3–4 — filters

Filters apply *after* vector search, *before* reranking, because:
- They are cheap (O(N) Python, N ≤ 150 at demo scale)
- Filtering before vector search would require per-filter sub-indexes; not justified here
- The wider fanout absorbs the post-filter shrinkage at demo scale

Filter dimensions: `source_kind` (SourceType enum), `after`/`before` (datetime bounds),
`entity_type` (Neo4j node label). The first three are pure Postgres filters; `entity_type`
requires the Neo4j entity lookup (stage 5).

### Stage 5 — graph signal

A single batched Cypher query (`UNWIND $event_ids`) finds all canonical (non-merged) graph
nodes whose `source_event_ids` array contains each candidate event id. The count of distinct
entities per event becomes the graph signal input.

`graph_signal = log(1 + entity_count) / log(10)` — normalised to ~[0, 1], saturates near
1.0 at 9–10 entities. See ADR 0022 for the normalisation rationale.

### Stage 7 — rerank

`final_score = 0.7 * cosine_similarity + 0.3 * graph_signal`

The 0.7/0.3 split is set by inspection of the bounding case (a high-cosine, zero-entity
event must beat a low-cosine, high-entity event). With `W_VEC=0.7, W_GRAPH=0.3`:
- A fully-relevant event (cosine=1.0, no entities) scores 0.70 before graph bonus
- A maximally-dense event (cosine=0.3, 10 entities) scores 0.51
- The semantically-relevant event wins

Weights live in `app/search/config.py` and can be changed without a code edit.

---

## Eval methodology and results

20 hand-curated questions based on the actual Northwind Payments corpus content. Each
question names 2–5 expected event UUIDs that *should* appear in top-10 results. Questions
span: ADR retrieval, Slack message retrieval, person attribution, architecture references,
contradiction-adjacent queries. Stored in `backend/data/search_eval_questions.json`.

| Metric | Value | Target | Pass? |
|--------|-------|--------|-------|
| Recall@10 | 0.942 | ≥ 0.70 | ✓ |
| MRR | 0.910 | ≥ 0.50 | ✓ |
| Mean latency (warm) | ~149ms | ≤ 500ms | ✓ |

The eval runner reports 902ms mean latency due to the first query's model-load cost (≈15s).
Warm per-query latency is consistently 20–380ms (median ~50ms). The deployed Docker backend
has the model warm from startup; all requests hit the warm cache.

Three questions had partial misses — documented in `docs/eval/phase-3d-search-results.md`.
The dominant failure mode is vocabulary mismatch: the query uses language that doesn't
closely match the target document's surface form (e.g. querying "stale" for a document that
doesn't self-describe as stale).

---

## Production-scale changes

This implementation is honest portfolio-demo scale. What changes for production:

### Model

bge-small-en-v1.5 is competitive but not state-of-the-art. Upgrade path:
1. `bge-base-en-v1.5` (768 dims, same API, ~2× quality) — one-line constant change +
   Alembic migration for the vector dimension. The defensive row-count guard in 0004 is
   the template.
2. `bge-large-en-v1.5` (1024 dims) — further quality improvement at ~4× inference cost.
3. Hosted API (OpenAI `text-embedding-3-large`) — if reproducibility is less important
   than quality and you have an API budget.

### Index

HNSW `m=16, ef_construction=64` is appropriate for ~1M vectors. For larger corpora:
- Increase `ef_construction` to 128–200 for better recall at build time
- Set `ef_search` (query-time) to tune the recall-latency tradeoff at query time
- Consider IVFFlat for memory-constrained deployments (lower recall, smaller index)

For multi-tenant deployments, separate HNSW indexes per tenant namespace prevent
cross-tenant leakage and allow per-tenant dimension/model choices.

### Retrieval pipeline

- **BM25 fusion**: add a `tsvector` index on `events.content` and fuse the BM25 rank
  with the vector rank via Reciprocal Rank Fusion. Helps on exact-keyword queries ("D-0006")
  where semantic similarity is diffuse.
- **Query expansion**: before embedding, expand the query with synonyms or related terms
  using a cheap LLM call. Helps with vocabulary mismatch (the main failure mode above).
- **LLM rerank**: Phase 4A territory. Pass the top-20 candidates + query to
  `claude-3.5-haiku` for a verbatim judgment of relevance. High latency cost (~200-800ms
  for 20 candidates) but high precision improvement. Justified by eval-driven evidence.
- **Precomputed entity counts**: rather than querying Neo4j per-request, precompute
  entity counts into a Postgres column on `events` (updated by the extraction pipeline).
  Removes the Neo4j round-trip from the hot path.

### Chunking

Events in this corpus average ~200 tokens (well under bge-small's 512-token limit). No
chunking is needed. For longer documents (meeting notes, full ADRs), chunk at paragraph
boundaries and embed each chunk separately. Phase 3D's design explicitly rejected chunking
as premature — the first evidence of truncation in search quality would trigger this.

---

## What Phase 4A builds on top

Phase 4A's agent will call `hybrid_search` as one of its tools, with the query generated
from the agent's understanding of the user's intent. The per-stage timing in `SearchResult`
is the latency breakdown the agent will report. The `related_entity_ids` field on each hit
enables the agent to cross-reference search results against the graph (e.g., "find events
mentioning auth-service, then retrieve the blast radius of auth-service").

---

## Related ADRs

- [ADR 0021](../decisions/0021-pgvector-dimension-migration.md) — Migrating `event_embeddings` from 1536-dim (placeholder) to 384-dim (bge-small-en-v1.5)
- [ADR 0022](../decisions/0022-hybrid-search-blend-weights.md) — 0.7 vector + 0.3 graph-density blend: rationale and sensitivity analysis
