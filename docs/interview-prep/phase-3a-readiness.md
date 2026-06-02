# Phase 3A Interview Readiness — Entity Resolution

Q&A covering the tiered resolver, the `MERGE_INTO` edge model, the embedding choice, the
audit table, and the eval. Each answer is deliverable in under 90 seconds. Honest answers;
real numbers. Full rationale lives in
[`docs/design/entity-resolution.md`](../design/entity-resolution.md),
[ADR 0014](../decisions/0014-entity-resolution-tiered-confidence.md), and
[ADR 0015](../decisions/0015-merge-decisions-audit-table.md).

---

## Q&A

### 1. Why three tiers instead of one similarity threshold?

Because cosine similarity has no notion of *identity* — it measures string similarity, and
the two come apart in both directions on this data. Two genuinely different critical services,
`notifications-api` and `notification-worker`, embed above almost any threshold you'd pick, so
a single cutoff merges them and corrupts the KQ3 blast radius. Meanwhile a nickname like "Al"
embeds well below 0.75 against "Alice Chen", so the same cutoff misses a true alias. No single
number separates "same entity" from "similar text." The three tiers let each signal do what
it's good at: deterministic exact-identity rules (shared email, handle, a curated alias)
auto-merge the certain cases for free; an LLM adjudicates only the genuinely ambiguous band;
and everything below the floor is left alone. The payoff is that the false-merge rate is
governed by exact rules, not by a fragile threshold, which is what we most need to protect.

### 2. Walk me through how `@alice` and `Alice Chen` get merged.

The Phase 2B writer slugged each surface form into its own Person node: `@alice` → `alice`,
`Alice Chen` → `alice-chen`, the email → `alice-chen-northwind-io`, "Al" → `al`. The resolver
loads all non-merged Person nodes, embeds each, and generates all within-type pairs with cosine
similarity. For the pair (`alice`, `alice-chen`), it runs the Tier 1 rules: the `known_alias`
rule normalises each node's surface forms and looks them up in the curated alias dictionary
(built from the company definition plus `ALIAS_GROUPS`). Both resolve to canonical `alice-chen`,
so the rule fires and the pair auto-merges at Tier 1, confidence 0.99 — regardless of the
embedding score, because an exact identity match is definitional. The merger picks the winner
(more `source_event_ids`; ties broken by lexicographic id), writes
`(loser)-[:MERGE_INTO {confidence, tier, created_at}]->(winner)`, unions the loser's
`source_event_ids` onto the winner, sets `loser.status = "merged"`, and records a
`merge_decisions` row. All four Alice forms end up in one connected component with one active
canonical node.

### 3. Why merges as edges, not deletions?

Three reasons, all about safety. First, **reversibility**: a wrong merge is the worst outcome
here — it fabricates a connection and corrupts downstream traversals — so I never want a merge
to destroy data. Undoing a `MERGE_INTO` is deleting the edge and resetting `status`; no
information is lost. Second, **provenance**: the loser node and its edges stay in the graph,
and the winner accumulates the union of `source_event_ids`, so the full evidence trail
survives the merge — exactly what KQ4's approval-history reconstruction needs. Third, **the
demo**: queries see the resolved view by filtering `WHERE n.status <> "merged"`; drop that one
clause and you see the original fragmented graph. So I can toggle before/after in a single line
in front of an interviewer. Deletion would give none of these — it's irreversible, it throws
away provenance, and there's no fragmented view left to show.

### 4. Why sentence-transformers locally instead of an embedding API?

Cost, determinism, and honesty. Resolution embeds *every* node on *every* run, so a hosted
per-token embedding API would meter a recurring cost for something that should be free —
whereas a local `BAAI/bge-small-en-v1.5` on CPU costs nothing after the one-time model load.
Determinism: a pinned local model returns byte-stable 384-dim vectors, so the eval numbers
reproduce on any machine, consistent with the project's seeded-generator discipline; hosted
embedding models can change under you and silently move your metrics. And it's the
production-honest answer: "embed locally with a small, well-understood model, and only pay the
LLM for the genuinely hard pairs" is the architecture a cost-conscious team actually ships. The
one real cost is image size — sentence-transformers pulls PyTorch CPU, ~300 MB — which I accept
for free, reproducible embeddings. The only money the resolver spends is Tier 2 adjudication,
bounded to the ambiguous band.

### 5. What's your false-merge rate, and what would push it down further?

On the `ALIAS_GROUPS` + `LOOK_ALIKE_PAIRS` eval the false-merge rate is **0.0** — no pair was
merged that ground truth says is distinct, including the deliberately-confusing
`notifications-api` / `notification-worker` look-alike, which has no alias-dictionary entry, so
no Tier 1 rule fires and it routes to Tier 2 where the LLM (or, with no key, the conservative
no-merge default) keeps them apart. That zero is the metric I care about most, because a wrong
merge is hard to detect and corrupts queries. What protects it is anchoring auto-merge on exact
rules rather than raw cosine. To push it down *in a harder setting* — real data, a noisier
alias dictionary — I'd add a similarity sanity-check that demotes a rule match to Tier 2 when
the embeddings are near-orthogonal, require two corroborating signals for auto-merge, and route
a sample of auto-merges through human review via the `merge_decisions` queue.

### 6. What's your missed-merge rate, and what would push it down?

On this eval the missed-merge rate is **0.0**: every true alias pair was recovered, because the
`known_alias` Tier 1 rule covers exactly the `ALIAS_GROUPS` surface forms and the metric is
pair-based over the seeded fragmented graph. I'm deliberately honest that this number is
flattered by the alias dictionary being sourced from the same narrative that defines ground
truth — so the recall I'm really demonstrating is of the *machinery*, not of open-world alias
discovery. The recall that would generalise comes from Tiers 2 and 3: pairs with no dictionary
entry but close embeddings. To push *that* recall down where it matters — aliases the
dictionary doesn't know — I'd lower the 0.75 adjudication floor (trading LLM spend for recall),
improve the per-type embedding input with more node properties, and add blocking on phonetic or
n-gram keys so near-miss spellings still become candidates.

### 7. How does the LLM adjudicator decide? Show me the prompt.

Tier 2 fires when no exact rule decides a pair but the embeddings are close (≥ 0.75). I send
`anthropic/claude-3.5-haiku` both nodes' stored properties and 2–3 short source-event snippets
each — the snippets are what let it reason about meaning, e.g. that one service "accepts
notification requests" and the other "delivers notifications off event-bus." The prompt names
the node type, lists each node's properties and snippets, states the embedding similarity, and
asks for JSON: `{"same": bool, "confidence": 0.0-1.0, "reasoning": "..."}`. I validate the
response against a Pydantic `LLMVerdict` with `extra="forbid"`; on any parse or schema failure
the adjudicator falls back to **no-merge**, because the safe default is to leave two nodes
unmerged. The reasoning string is stored in the `merge_decisions` row, so every LLM merge is
explainable after the fact.

### 8. What happens if Tier 2's LLM says "different" when they're actually the same?

That's a missed merge — the conservative failure, and the one I'd rather have. The two nodes
stay separate, each correct but partial, and the graph is merely fragmented at that point, not
*wrong*: no fabricated edge, no corrupted traversal. It's also fully recoverable, because the
`merge_decisions` table recorded an `llm_no_merge` row with the embedding similarity and the
model's reasoning — so a human reviewer (Phase 6) can page through low-confidence no-merges and
override them, and a future re-run with a better model or a lowered threshold can catch it. I
designed the asymmetry on purpose: a wrong *merge* is hard to detect and corrupts downstream
queries, so when Tier 2 is uncertain I bias toward leaving nodes apart and surfacing the
decision for review rather than guessing "same."

### 9. Why is `merge_decisions` a Postgres table, not a Neo4j relationship?

Because most of what I want to audit has no edge to attach to. A rejected pair —
`llm_no_merge` or `below_threshold` — produced no merge, so there's nothing in the graph to
carry the record; modelling rejections as edges would pollute the graph with non-structural
bookkeeping and distort traversals. And the data is exactly what relational stores are for:
append-only, time-series audit rows with heterogeneous nullable columns (LLM reasoning and
model only for Tier 2), queried by `(node_type, created_at)`. Postgres already plays this
provenance role in the project, alongside `events` and `extraction_runs`. The `MERGE_INTO`
edge stays in Neo4j for the *structural* fact of a merge; the *reasoning and the rejections*
live in Postgres. They're complementary — the edge says a merge happened, the row says why,
and the row is also the seed for a Phase 6 human-review queue.

### 10. How would you scale this from 35 entities to 1 million?

The bottleneck is candidate generation: all-pairs within a type is O(n²), fine at 35 nodes (a
few hundred comparisons) but quadratic and impossible at a million. The fix is **blocking**:
only compare nodes that share a cheap key. I already block on entity type; at scale I'd add a
coarse block (first character of a normalised name, or an LSH bucket over the embedding) and
then use an approximate-nearest-neighbour index — the same pgvector HNSW index the project
already runs for events, or a Neo4j vector index — to fetch each node's top-k neighbours instead
of scanning all pairs. That turns O(n²) into roughly O(n·k). Tier 1 rules stay O(1) per pair
and the LLM tier is already bounded to the ambiguous few, so cost stays controlled. I'd also
move resolution into the write path (Phase 4) so it runs incrementally as nodes arrive, rather
than re-resolving the whole graph each batch, and partition `merge_decisions` by time with a
retention policy since it grows by candidate-pairs per run.

---

## Whiteboard concepts

### 1. The three-tier flow

```
candidate pair (A, B), same type
        │
   apply Tier 1 rules ──► any rule fired? ──yes──► AUTO_MERGE (tier 1, conf 0.99)
        │ no
   cosine(A, B) ≥ 0.75? ──no──► BELOW_THRESHOLD (tier 3, no merge)
        │ yes
   claude-3.5-haiku adjudicates ──► same? ──yes──► LLM_MERGE (tier 2, conf = verdict)
                                      │ no
                                      └────────► LLM_NO_MERGE (tier 2, no merge)
```
Every leaf writes a `merge_decisions` row; the two MERGE leaves also write a `MERGE_INTO` edge.

### 2. The MERGE_INTO edge model (one example)

```
Before:  (:Person {canonical_id:"alice"})        (:Person {canonical_id:"alice-chen", events:[e1,e2]})
After:   (:Person {canonical_id:"alice", status:"merged", events:[e3]})
              │
              └─[:MERGE_INTO {tier:1, confidence:0.99, created_at}]─►
         (:Person {canonical_id:"alice-chen", events:[e1,e2,e3]})   ← winner, still active

Resolved view:  MATCH (p:Person) WHERE p.status <> "merged"   -- sees only alice-chen
Fragmented view: drop the WHERE clause                         -- sees both
```

### 3. Cosine similarity for an alias pair

```
v_A = embed("Alice Chen | |")            (384-dim, L2-normalised)
v_B = embed("alice | @alice |")
cos(A,B) = v_A · v_B            (dot product, since both are unit vectors)
```
Note: this is *recorded* for the Alice pair but does **not** gate the merge — the `known_alias`
rule is authoritative. Cosine only routes the *no-rule* pairs (look-alikes, novel aliases).

### 4. Resolution eval metrics

```
predicted_pairs = all within-component pairs from MERGE_INTO edges (union-find)
true_pairs      = all within-group pairs from ALIAS_GROUPS

precision        = |predicted ∩ true| / |predicted|
recall           = |predicted ∩ true| / |true|
false_merge_rate = 1 − precision        (the headline safety metric)
missed_merge_rate= 1 − recall
```
A mock-perfect resolver (predicted == true) scores 1.0/1.0 — asserted in `test_resolution_eval`
before any real output is judged.

### 5. Candidate-generation complexity

```
within one type:   pairs = C(n, 2) = n(n-1)/2   →  O(n²)
   n = 35  →  ~595 pairs        (this phase: trivially fast)
   n = 10⁶ →  ~5·10¹¹ pairs     (impossible)

scaling path: block by (type, cheap key) then ANN top-k per node
   →  O(n · k),  k ≈ 10–50 neighbours
```
