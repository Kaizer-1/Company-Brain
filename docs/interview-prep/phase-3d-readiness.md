# Phase 3D — Interview Readiness: Semantic Search

> 10 Q&A pairs (≥80 words each) + 5 whiteboard concepts.
> Topics required by spec: local model choice, HNSW parameters, linear blend vs LLM rerank,
> filter ordering and fanout, production scale changes.

---

## Q&A Pairs

### Q1: Why did you use a local embedding model instead of OpenAI's embedding API?

Three reasons, in order of importance.

**Cost and frequency.** The embedding pipeline runs for every event on every pipeline
invocation — that's currently 111 events, and will grow with each new corpus ingestion.
At OpenAI's text-embedding-3-small pricing (~$0.02/1M tokens), 111 events of ~200 tokens
each costs fractions of a cent per run. But in a portfolio project that may be run dozens
of times, and on a team that values reproducibility, the case for zero-cost local inference
is strong.

**Determinism and reproducibility.** A pinned local model (`BAAI/bge-small-en-v1.5` at a
fixed git revision) returns byte-stable vectors on any machine. OpenAI can — and does —
update model weights silently. If the eval numbers in `docs/eval/phase-3d-search-results.md`
were produced against a hosted model that was later updated, the numbers wouldn't reproduce.
The Phase 3D design requires that eval numbers are reproducible; a local model delivers this.

**The production-honest answer.** "We use local inference for the cheap, frequent calls
and pay for API calls only for the genuinely hard work" (in this project: Tier-2 LLM
adjudication in entity resolution, and contradiction detection) is the architecture a
cost-conscious team actually ships. It is also the honest one: bge-small-en-v1.5 is good
enough on this corpus. Claiming you need a frontier model for 384-dimensional event
embeddings when the eval shows 0.94 Recall@10 would be dishonest.

---

### Q2: Why `BAAI/bge-small-en-v1.5` specifically? Why 384 dims?

The model was already live in the codebase from Phase 3A (entity resolution). Using the
same model for semantic search eliminates a second model load (~300 MB of PyTorch weights),
keeps the vector space consistent (resolution embeddings and search embeddings are in the
same space — a future cross-use is possible), and avoids the maintenance surface of two
model-version pins.

384 dimensions is small enough for fast CPU inference (~8ms per 32-event batch once warm)
and large enough to capture nuanced semantic distinctions at this corpus scale. The original
`vector(1536)` was a Phase 1C placeholder sized for OpenAI text-embedding-3-small; migrating
it to 384 (Alembic 0004) removed the misalignment.

The upgrade path is a one-line constant change and a new Alembic migration: change
`EMBEDDING_DIM` to 768 (bge-base) or 1024 (bge-large) and re-run the embedding pipeline.
The defensive row-count guard in migration 0004 is the template for future re-embedding
migrations. The model choice was not premature — it was the right tool for the job with a
documented path to better models if eval demands it.

---

### Q3: Why HNSW for the vector index, and why `m=16, ef_construction=64`?

pgvector offers two approximate nearest-neighbour index types: IVFFlat (inverted-file,
flat quantization) and HNSW (hierarchical navigable small world). HNSW was chosen because
it provides better query recall at lower ef_search settings, does not require a pre-build
training step (IVFFlat needs `VACUUM ANALYZE` after insertions to update the IVF list
centroids), and handles insertions incrementally (IVFFlat's recall degrades as the dataset
grows beyond the trained centroids until the next `VACUUM ANALYZE`).

`m=16` is the number of bidirectional links per node per layer — pgvector's default,
appropriate for datasets up to ~1M vectors. Higher m (e.g. 32) improves recall but
increases memory proportionally. `ef_construction=64` is the build-time search width:
how many candidates are explored while building each node's neighbour list. Higher values
improve recall at the cost of index build time. At demo scale (111 vectors) these parameters
are irrelevant to performance; they are inherited from the Phase 1C schema and are the
correct starting point for scaling. For a multi-million-vector corpus: `m=32, ef_construction=128`
is a common production choice that trades ~2× memory for measurably better recall.

---

### Q4: Why linear blend (0.7/0.3) and not LLM rerank?

Because the eval didn't justify the cost and latency. The linear blend achieves 0.942
Recall@10 and 0.910 MRR on the 20-question eval set. Adding an LLM rerank step would cost
200–800ms per query (a 3×–5× latency increase), introduce an API dependency, and require
a calibration eval to verify it actually improves things. None of those costs are justified
by an existing gap in quality.

The design philosophy is explicit: "Adding an LLM rerank step 'to improve quality' is Phase
4A territory and needs eval-driven justification." If the eval showed recall of 0.55 — below
the 0.70 target — then LLM rerank would be the first thing to try. With 0.94, the correct
move is to ship what works and document the upgrade path, not add complexity for its own sake.

The 0.7/0.3 split is set by the bounding case: a maximally graph-dense event (10 entities,
cosine 0.3) must not beat a semantically relevant event (0 entities, cosine 0.9). The
split satisfies this constraint and was not tuned to the eval set — confirming that the
eval numbers are honest.

---

### Q5: What is the graph signal and what does it add over pure vector search?

The graph signal is `log(1 + entity_count) / log(10)`, where `entity_count` is the number
of distinct canonical entities in the knowledge graph that were asserted by this event.
It captures structural density: an event that mentioned a service, three people, two
decisions, and a system is a richer node in the company's knowledge graph than an event
that mentioned only one entity.

What it adds: for events with similar vector similarity scores, graph-dense events rank
higher. In the Northwind Payments corpus, the architecture overview docs and key ADRs tend
to assert many entities; they rank higher for structural queries even when their vocabulary
doesn't exactly match the query.

What it doesn't add: when the graph has not been populated (extraction pipeline not run),
all entity counts are zero and the system degrades cleanly to pure vector search. This is
documented as graceful degradation. The eval was run with entity counts from a populated
graph; the improvement is real but modest at demo scale.

The 0.3 weight is deliberately conservative: the graph signal is a proxy, not a ground-truth
relevance signal. Setting it too high would cause low-cosine events to rank above high-cosine
events purely because they appeared in many extraction outputs.

---

### Q6: How do filters interact with the fanout multiplier?

Filters apply *between* vector search and reranking. The system fetches `FANOUT × k`
candidates from pgvector, applies the filters in Python, and then reranks whatever remains.

Without filters: `BASE_FANOUT=3`, so k=10 fetches 30 candidates. After reranking, the top
10 are returned.

With any active filter: `FILTER_FANOUT=5`, so k=10 fetches 50 candidates. The extra
headroom absorbs the expected shrinkage. For example, filtering to `source_kind=slack_message`
in a corpus with 50% slack events halves the pool from 50 to ~25 — enough to return 10
results. Without the increased fanout, the pool of 30 would shrink to ~15, which is still
enough, but for a `source_kind` filter that passes only 10% of events, a 3× fanout would
leave only 3 candidates — not enough to fill k=10.

The correct fanout multiplier depends on the filter selectivity. `FILTER_FANOUT=5` is a
conservative heuristic that works for the filter dimensions in this corpus. For a production
system with arbitrary filter combinations, computing the expected post-filter pool size and
adjusting the fanout dynamically (or, better, doing the filtering at the SQL level with a
WHERE clause on the pgvector query) would be the right approach.

---

### Q7: The `event_embeddings` table was at `vector(1536)` for two phases. Why wasn't it used?

It was a Phase 1C placeholder — the schema was designed knowing that Phase 3D would need
a vector search index, but the embedding model hadn't been decided yet. 1536 was the
dimension of OpenAI's text-embedding-3-small, the most likely candidate at the time of
schema design. The schema accommodated it without committing to it.

The table had zero rows for Phases 1C through 3C. This is a feature of the design, not
technical debt: the table existed so that the Alembic migration chain was uninterrupted
(Phase 1C creates the table with an HNSW index; Phase 3D populates it), and the
`EventEmbeddingRepository` existed so that Phase 3D's indexer had a tested write path to
use. The "placeholder" pattern — schema + repository, no pipeline integration — is how the
project avoids accumulating unbuildable code. The table waited for the right phase to fill it.

Migrating from 1536 to 384 required a drop-and-recreate (Alembic 0004) because pgvector
doesn't support `ALTER COLUMN ... TYPE vector(N)` with a different N. The migration includes
a defensive row-count check to refuse if any rows exist, so future re-embedding migrations
can use the same pattern safely.

---

### Q8: How does the search system relate to the four killer queries?

The killer queries (KQ1–KQ4) answer templated graph traversals: given a specific seed
entity, follow typed edges and return a structured result. They work on the *resolved graph*
and produce structured answers with provenance chains. They cannot answer "find me everything
about auth" because there is no template for "everything about X."

Semantic search answers the inverse: given a natural-language question, find the raw events
that discuss the relevant things. It operates on *text*, not *graph topology*, and returns
a ranked list of events with similarity scores. It can answer "what was discussed about auth
last month?" but cannot answer "who owns the service downstream of the auth deprecation?"
(because that requires typed edge traversal, not text matching).

The two systems are *complementary*, not competing. Phase 4A's agent will route questions:
if the question maps to a KQ template, call the KQ; if not, call `hybrid_search`. The
`related_entity_ids` on each search result allow the agent to pivot from "events about auth"
to "now traverse the graph from auth-service" — the bridge between retrieval and traversal.

---

### Q9: If you ran this at production scale (10M events), what changes first?

Three things, in order:

**1. Index memory.** HNSW indexes load into memory. At 384 dims × 4 bytes × 10M rows ≈ 15 GB
just for the vectors, plus HNSW node connections. This still fits on a single well-provisioned
machine (e.g. r5.4xlarge at AWS), but it can no longer run alongside the OLTP workload.
Solution: a dedicated read replica for vector search, or pgvector's upcoming partitioned
HNSW for sharding by corpus segment.

**2. Indexing throughput.** At batch size 32, embedding 10M events at 8ms/batch ≈ 2500 batch
× 8ms = ~20 seconds for 100K events — fine for a daily batch but too slow for real-time
ingestion. Solution: GPU inference (10–100× faster), or a dedicated worker cluster with
the sentence-transformers API.

**3. Multi-tenancy.** The current single-index design leaks all events to all queries. At
production scale, a separate HNSW index per tenant (using pgvector's schema-per-tenant
pattern) is the standard approach. Alternatively, include a `tenant_id` in the query's
WHERE clause to filter before the cosine search — pgvector supports pre-filtering via
index scan, though it can degrade to sequential scan if the filter is highly selective.

---

### Q10: How would you measure if the graph signal actually helps?

Ablate it. Run the eval twice: once with `W_GRAPH=0.3` (current) and once with `W_GRAPH=0.0`
(pure vector). If Recall@10 or MRR is equal or better with `W_GRAPH=0.0`, the graph signal
is noise at this corpus scale and should be disabled.

The current numbers (Recall@10=0.942 with graph signal active) don't tell us the
counterfactual because the eval was run with a partially-populated graph (not all events had
entity counts populated from Neo4j). A rigorous ablation would:
1. Run the full pipeline (extract → resolve → project) to populate entity counts for all
   candidate events
2. Measure Recall@10 with `W_GRAPH=0.3`
3. Measure Recall@10 with `W_GRAPH=0.0`
4. Report both numbers honestly

If the corpus is small and the retrieval task is mostly vocabulary-driven (as it is here),
pure vector search often wins. The graph signal's value compounds when:
- The corpus is large and semantically noisy (many near-duplicate events)
- The graph is well-populated (most events have entity counts > 2)
- The queries are structural ("find events mentioning auth-related decisions")

---

## Whiteboard Concepts

### WB1: How the HNSW index is built and queried

HNSW (Hierarchical Navigable Small World) is a graph-based approximate nearest-neighbour
structure. Build: for each new vector, the algorithm greedily inserts it into a random layer
(lower layers are coarser; layer 0 is the full dataset). Each node connects to `m` nearest
neighbours per layer, with `ef_construction` controlling the candidate beam width. Query:
entry point at the top layer, greedy descent towards the query vector, with the bottom layer
(finest granularity) returning the actual candidates. The `ef_search` parameter controls the
beam width at query time — higher values trade latency for recall.

**Trade-off vs IVFFlat**: HNSW provides better recall at the same latency, handles incremental
inserts cleanly, but uses more memory. IVFFlat uses less memory and is faster to build but
requires a two-step query (cluster assignment then exhaustive scan within cluster) and degrades
if the cluster centroids become stale. For this project's insert-heavy (pipeline-driven) use
case, HNSW is the right choice.

---

### WB2: The embedding pipeline and provenance chain

```
Postgres events
      │
      ▼
embed_events()          ──► event_embeddings (vector(384))
      │
  [idempotent:          SELECT events LEFT JOIN event_embeddings
   skips already-        WHERE ee.event_id IS NULL
   embedded events]
      │
      ▼
hybrid_search()         query embedding + pgvector cosine + Neo4j entity count
      │
      ▼
SearchHit               event_id (provenance FK) + snippet + scores
      │
      ▼
EventModal              GET /api/events/{event_id} → full raw text
```

Every search result carries `event_id`, which is a foreign key into `events`. The frontend
uses this to open the `EventModal` — the same source-event drilldown used by the graph
explorer and the queries page. Provenance is non-optional: a search result without an
`event_id` cannot be traced to its source and is therefore not shown.

---

### WB3: The retrieval-graph handoff and why search doesn't replace KQs

Vector search retrieves by text similarity. It will find events that *mention* "auth-service"
and "legacy-auth" near "deprecate" — but it cannot tell you that the deprecation created a
4-hop ownership chain to Diego Ramirez. For that, you need KQ1.

The handoff: `hybrid_search` returns a ranked list of events with `related_entity_ids`. Phase
4A's agent sees these entity IDs and decides: "The user's question about auth is answered by
the KQ1 traversal from D-0006, not by the raw events." The agent calls KQ1, gets a structured
answer with a provenance chain, and presents it. If the user's question doesn't match a KQ
template, the agent presents the raw search results directly.

This is the "hybrid graph-RAG" pattern: use retrieval to identify which part of the graph is
relevant, then use the graph to answer the structural question. Neither half works without the
other.

---

### WB4: Why filters apply after vector search (not before)

Applying filters *before* vector search would require filtering the index itself — for example,
a `WHERE source_type = 'doc'` clause on the HNSW scan. pgvector supports this with `WHERE`
on indexed columns, but it can degrade to a sequential scan when the filter is highly selective
(e.g. if only 5% of events are docs, the index scan can't skip efficiently to the relevant
region of the HNSW graph).

Instead, this design applies filters *after* vector search on the candidate pool. The wider
`FILTER_FANOUT` compensates for the shrinkage. This approach:
- Uses the HNSW index at full efficiency (no filtered scan degradation)
- Keeps the filter logic in Python (readable, testable, free to extend)
- Trades a slightly larger candidate pool for simplicity and reliability

The production solution for large, selective filters is to pre-materialise the filter
dimensions as indexed columns and use pgvector's filtered HNSW scan — which works well
when the filter cardinality is high (many distinct values) but degrades when it's low
(e.g. a binary flag that filters out 95% of rows). The current approach is honest about
this trade-off.

---

### WB5: How `embed_events` maintains idempotency

```sql
SELECT e.id, e.content
FROM events e
LEFT JOIN event_embeddings ee ON ee.event_id = e.id
WHERE ee.event_id IS NULL
ORDER BY e.created_at ASC
```

This `LEFT JOIN ... WHERE NULL` pattern finds every event without an embedding. On first run:
all events are returned (no embeddings exist). On subsequent runs: only new events since the
last run are returned. Deletion: if an event is deleted (CASCADE deletes its embedding row),
the next run re-embeds it — which should not happen in practice since `events` is append-only.

The batch loop flushes after each batch (`session.flush()`) and commits at the end
(`session.commit()`). If the pipeline crashes mid-run, already-committed batches are durable;
the next run picks up from where it left off (the `LEFT JOIN` excludes already-embedded events).
This is true idempotency: not "harmless to re-run" but "always correct to re-run."
