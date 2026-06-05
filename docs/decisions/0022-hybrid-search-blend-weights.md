# ADR 0022 — Hybrid Search Blend Weights: 0.7 / 0.3 Linear Blend

## Status

Accepted

## Context

Phase 3D builds a hybrid retrieval layer: given a natural-language query, return the top-k
events that are most relevant. "Relevant" is a combination of two signals:

1. **Vector similarity** — cosine distance between the query embedding and each event's
   content embedding. Captures semantic meaning: "authentication migration" finds events
   that discuss auth changes even if they don't use those exact words.
2. **Graph signal** — how many canonical entities the event asserted in the knowledge graph.
   An event that mentions 8 distinct entities (a service, 3 people, 2 decisions, 2 systems)
   is structurally more connected than an event that mentions 1. This is a proxy for
   "informationally dense" in the graph-structured sense: densely connected events are likely
   to be important junction points in the company's knowledge.

The question is how to combine them into a `final_score`.

## Decision

**Linear blend**: `final_score = w_vec * cosine_similarity + w_graph * graph_signal`

where:
- `w_vec = 0.7` — vector similarity weight
- `w_graph = 0.3` — graph signal weight
- `cosine_similarity ∈ [0, 1]` — pgvector `1 - (embedding <=> query)`, i.e. 1 = identical
- `graph_signal = log(1 + entity_count) / log(10)` — saturates at ~10 entities; normalized
  to a 0–1 range where `entity_count = 9` gives 1.0

All constants live in `app/search/config.py` and can be changed without a code change.

### Why a linear blend, not a learned reranker

A learned reranker (cross-encoder, LambdaMART, BM25+vector fusion with learned weights)
requires labelled preference data that this project does not have, and would require a
separate training pipeline. More importantly: at portfolio-demo scale with a 20-question eval
set, the eval numbers cannot distinguish between a 0.7/0.3 blend and a 0.65/0.35 blend.
Introducing a learning component produces exactly one thing — the ability to claim "we used a
learned reranker" — without improving the honest numbers. The Phase 3D design explicitly
prohibits this: "Honest recall@10 of 0.6 is more valuable than fake 0.85."

A linear blend is the right answer for v1 because:
- The weights are interpretable. Telling an interviewer "we weight vector similarity 70% and
  graph density 30%" is a defensible claim with a clear upgrade path.
- The weights are tunable via config. If eval shows graph signal adds noise, set `w_graph=0`
  and it degrades cleanly to pure vector search.
- The graph signal is a genuine signal, not noise: an event that asserted 8 entities is more
  likely to be a useful anchor for a graph-traversal follow-up (Phase 4A) than one that
  asserted 1. The 30% weight is conservative enough not to boost low-similarity events that
  happen to be graph-dense.

### Why `log(1 + entity_count) / log(10)` for graph signal

The raw entity count is unbounded (an extraction pass could assert 15+ entities from a dense
ADR). Using it directly would allow high-entity events to dominate purely on graph density,
even when vector similarity is low. The log-normalisation:
- Saturates at 10 entities (log₁₀(10+1) ≈ 1.04 ≈ 1.0)
- Is smooth and monotone — more entities always helps, but with diminishing returns
- Keeps the graph signal in a [0, ~1] range compatible with the cosine similarity range

### Why 0.7 / 0.3

The dominant signal must be semantic relevance, not structural density. Setting `w_vec = 0.7`
ensures that a low-similarity, high-density event does not outscore a high-similarity,
low-density event:
- Max boost from graph signal at `entity_count=10`: `0.3 * 1.0 = 0.3`
- A vector-similar event (cosine=0.8) scores `0.7 * 0.8 = 0.56` before graph bonus
- A graph-dense event (cosine=0.3, entity=10) scores `0.7 * 0.3 + 0.3 * 1.0 = 0.51`
- The semantically-relevant event wins

The 0.7/0.3 split was chosen by inspection of this bounding case, not by training. It is
a deliberate prior, not a tuned result. If the eval shows the graph signal adds noise (e.g.,
Recall@10 improves when `w_graph → 0`), the config change is a one-liner and does not
require a code change.

## Alternatives Considered

### Option A — Pure vector search (w_graph = 0)

Always available as a fallback by setting `w_graph=0`. Not adopted by default because the
graph signal is cheap (one Neo4j query per result), interpretable, and consistent with the
project's thesis that structural graph information adds value over pure embedding similarity.
If eval proves otherwise, this is the fallback.

### Option B — BM25 + vector fusion (Reciprocal Rank Fusion)

BM25 requires a separate term-frequency index (Elasticsearch or a pgvector `tsvector`
column). Reciprocal rank fusion requires two ranked lists and a merging step. Both add
significant complexity (a second index to maintain, a second query, a merge algorithm) for
a marginal benefit at this corpus size. The event contents are short (~200 tokens average)
and the vocabulary is small (synthetic English). BM25 would help on exact-match recall; the
eval set is designed to test semantic retrieval, not keyword matching. Rejected for Phase 3D.

### Option C — LLM rerank (cross-encoder style)

Send the top-N candidates to `claude-3.5-haiku` with the query and ask it to score/rank
them. This is Phase 4A territory: it requires a prompt, a latency budget, a cost budget, and
a calibration eval. The Phase 3D latency target is ≤ 500ms; an LLM rerank adds 200–800ms.
Eval-driven justification belongs in Phase 4A, not Phase 3D. Explicitly rejected per design
philosophy. Deferred with a named re-entry path.

### Option D — Learned weights via a small ranking model

No training data. No infrastructure. Not justified at portfolio scale. Rejected.

## Tuning path

If the eval (Recall@10, MRR) shows the blend underperforms pure vector search:
1. Set `W_GRAPH = 0.0` in `app/search/config.py` — pure vector. If this improves numbers,
   the graph signal is noise at this corpus scale.
2. If pure vector already hits target, ship it. If not, the problem is retrieval quality,
   not blend weights — investigate the model or the eval questions.
3. For Phase 4A, if LLM rerank is added, set `w_graph = 0` there — the reranker subsumes
   the structural signal via the entity chips passed in context.

## Consequences

**Positive:**
- Simple, interpretable, tunable blend. No training pipeline. No second index.
- The graph signal connects the search layer to the graph layer, maintaining the project's
  thesis that the graph adds value.
- Weights exposed as config constants; changing them does not require code changes or
  redeployment (backend restarts pick up module-level constants).

**Negative / accepted:**
- Weights are set by inspection, not by training. Honest claim: "we set them by reasoning
  about the bounding case." A trained system would be more defensible numerically but
  unjustified here.
- The graph signal requires one Neo4j query per candidate result. At k=10 with 3× fanout,
  that is 30 Neo4j queries. At demo scale this is fast. At production scale, batch or cache.
