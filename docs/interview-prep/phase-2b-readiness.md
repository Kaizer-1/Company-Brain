# Phase 2B Interview Readiness

Q&A covering the LLM extraction pipeline, the eval harness, and the three-model
comparison results. Each answer is deliverable in under 90 seconds. Honest answers;
real numbers. Full rationale lives in [`docs/design/extraction-pipeline.md`](../design/extraction-pipeline.md),
[ADR 0012](../decisions/0012-extraction-via-openrouter.md), and
[ADR 0013](../decisions/0013-eval-ground-truth-from-narrative.md).

---

## Q&A

### 1. Why OpenRouter instead of a single provider API?

Three concrete reasons. First, the project's central design question for Phase 2B is
"which model is best for this extraction task" — OpenRouter is a single API surface that
lets us run `gpt-4o-mini`, `claude-3.5-haiku`, and `gemini-2.5-flash-lite` through
identical code paths (same request shape, same JSON-mode flag, same retry logic in
`client.py`). Comparing models via three separate SDKs would have introduced per-SDK
variance that obscures the model difference. Second, OpenRouter returns a real dollar cost
in `usage.cost` on every call, which is how we logged $0.035, $0.347, and $0.038 per full
corpus run per model and reported total spend of $0.42 — a concrete cost story that a
single-provider API often buries or omits. Third, OpenRouter is vendor-neutral: when
`google/gemini-2.0-flash` was retired mid-project, we substituted
`google/gemini-2.5-flash-lite` in one config line without touching `client.py`. The
downside is adding an intermediary — OpenRouter can lag provider releases and adds a
hop to every call. For a batch eval pipeline where latency is not the constraint, that
trade-off is acceptable.

---

### 2. Walk me through the extraction pipeline from event to graph node.

The pipeline is a straight line across six modules in `backend/app/extraction/`. (1)
`pipeline.py` reads a raw `events` row from Postgres as an `EventDTO`. (2) `prompts.py`
builds a prompt: the system instruction, the curated schema description (two Markdown
tables, ~30 lines), two few-shot examples (one rich positive, one empty-answer negative),
and the event content — assembled to ~220 lines. (3) `client.py` (`OpenRouterClient`)
sends the prompt to the model via async httpx with JSON-mode enabled (`response_format=
{"type":"json_object"}`), logs `usage.cost`, and retries on 429/503 with exponential
backoff. (4) `parser.py` takes the raw response text, strips any ```` ```json ``` ```` fence
defensively, and validates the payload against `ExtractionResult` using Pydantic v2 strict
mode. On any failure it raises a typed `ExtractionParseError` carrying the raw response and
the failure stage. (5) `graph_writer.py` `MERGE`s the validated entities and relationships
into Neo4j in a single transaction: entity nodes keyed by canonical slug, edges with
`confidence`, `extracted_by` (`"{model}@{PROMPT_VERSION}"`), `source_event_id`, and
`evidence_quote`; `source_event_ids` on nodes extended by set-union so re-extraction
accumulates provenance. (6) `pipeline.py` closes the `extraction_runs` audit row — created
in the `failed` state before any LLM call, flipped to `success` only after a clean
parse-and-write. A failed extraction produces an audited row and an unchanged graph, never
a partial subgraph.

---

### 3. Why is `evidence_quote` a required field on every extracted entity and relationship?

Because it disciplines the model and gives the evaluator a diagnostic anchor, simultaneously.
On the model side: a model that must quote an exact verbatim substring to assert a fact
cannot assert facts the text does not contain. Requiring a non-empty quote functionally
raises precision — hallucinated edges typically cannot be quoted because the text never said
them. The few-shot positive example in the prompt demonstrates this: every entity and
relationship entry shows an exact span like `"legacy-auth is deprecated."` paired with the
extraction. On the eval side: when an extraction is wrong, the `evidence_quote` shows why
the model thought it was right. The worst-case examples in `docs/eval/phase-2b-results.md`
use the quote to tell the story — e.g. gemini extracted `D-0007 ABOUT user-store` because
the text said "Enforce mTLS between auth-service and user-store," which is evidence for a
`DEPENDS_ON`-adjacent relationship but not for an ABOUT edge from the decision. Without the
quote, we would see a false positive in the counts but not understand the confusion. The
`evidence_quote` is also stored on every Neo4j edge via `graph_writer.py`, so a query can
surface the grounding span alongside the answer — a provenance story that extends all the
way from Postgres event to graph traversal result.

---

### 4. Why a curated schema description in the prompt, not a `model_json_schema()` dump?

The contrast is stark when you look at the numbers: the curated description is two
Markdown tables and one example object — roughly 30 lines and ~400 tokens. A
`model_json_schema()` dump of `ExtractionResult` is 120+ lines of nested `$defs`, `anyOf`,
`allOf`, and `enum` arrays — roughly 1,500 tokens. That difference is repeated on every
one of 111 × 3 = 333 model calls, so the dump would cost ~3.5× more in input tokens alone.
But the token cost is the smaller problem. The deeper problem is that smaller models
(haiku, flash) follow a clean English table more reliably than nested JSON-Schema
indirection. `$ref: "#/$defs/RelationshipType"` requires the model to cross-reference; the
table says `DEPRECATES | Decision → System | "Decision deprecates/retires/sunsets S"` in
one row. The `anyOf` union for `Service | System` targets invites the model to emit the
schema's own union syntax in its response instead of a concrete value. We measured this
directly: all three models produced lower `wrong_relationship_type` counts with the curated
description than they did with an earlier prompt version that included the full Pydantic
schema. The Pydantic model (`ExtractionResult`) is kept for *validating* the response, not
*describing* it — and the two are kept in sync in the same file (`prompts.py`) with a
`prompt_fingerprint()` hash that makes drift auditable in `extraction_runs`.

---

### 5. How does the eval harness derive ground truth, and why isn't it a hand-labeled JSON file?

Ground truth is built by `backend/app/eval/ground_truth.py` calling `build_ground_truth()`
which reads `company.py` (the entity registry) and `narrative.py` (the planted cases) and
programmatically constructs the gold set: 45 entities and 70 relationships
(19 DEPENDS_ON, 13 ABOUT, 13 OWNED_BY, 12 APPROVED_BY, 12 MEMBER_OF, 1 DEPRECATES).
The reason it is not a hand-labelled JSON file is drift: if we maintain a separate
`ground_truth.json`, every time `company.py` or `narrative.py` changes we must remember to
update that file. Since `company.py` and `narrative.py` are the canonical definition of
what exists in the company, deriving ground truth from them programmatically means it is
always in sync — you cannot add a new planted case in `narrative.py` without it
automatically appearing in the eval's gold set. ADR 0013 names the explicit inclusion rule:
every entity defined in `company.py` is a ground-truth entity; every relationship that
`narrative.py` declares a planted case for is a ground-truth relationship. The limitation
is also named: Message-anchored relationships (`CONTRADICTS`, `AUTHORED`, `MENTIONS`) are
out of scope for this eval because Messages are not derived from `company.py` — they are
procedurally generated and do not have stable ground-truth endpoint pairs. Extending the
eval to cover those types is a documented future step.

---

### 6. Explain the alias-tolerant matcher and why it's needed despite Phase 3B doing real entity resolution later.

The matcher in `backend/app/eval/matcher.py` builds a `SurfaceIndex` from `company.py` and
`narrative.py`'s `ALIAS_GROUPS`: for each canonical entity (`ben-smith`), it registers every
known surface form (`Ben Smith`, `@bsmith`, `@ben`, `ben.smith@northwind.io`) as aliases.
When the eval checks whether an extracted entity matches a ground-truth entity, it
canonicalises both through the index before comparing. Without this, every `alias_not_merged`
case would also be a false positive + false negative in the F1 calculation, making the
eval conflate two separate problems: (a) did the model extract the right fact? (b) did the
model normalise the name? Phase 3B resolves aliases at the graph level; the eval should not
penalise Phase 2B for the problem Phase 3B is designed to fix. So the matcher makes F1 an
honest measure of extraction quality — not a mixture of extraction quality and the
entity-resolution debt Phase 3B holds. Crucially, the matcher still *counts* the
`alias_not_merged` cases separately (10–13 per model) and reports them in the failure modes
table, so the limitation is visible and tracked, just not double-penalised. When Phase 3B
lands, the matcher becomes redundant and the ground-truth eval can switch to an exact-match
strategy.

---

### 7. Walk me through your three-model comparison results. Which model would you pick for production and why?

Full results from `docs/eval/phase-2b-results.md` (seed 42, prompt `2b-v1`, 111 events):

| Model | Entity F1 | Relation F1 | Cost (full corpus) |
|---|---|---|---|
| `openai/gpt-4o-mini` | 0.87 | 0.62 | $0.035 |
| `anthropic/claude-3.5-haiku` | 0.91 | 0.78 | $0.347 |
| `google/gemini-2.5-flash-lite` | 0.87 | 0.57 | $0.038 |

All three clear the honest targets (~0.80 entity, ~0.65 relation) on entities but split on
relationships. Entities are easy — every model achieves F1 ≥ 1.0 on Person and Decision
types. Relationships are where the models separate. For production I would pick
**`gpt-4o-mini` as the default** (0.87/0.62, $0.035 per corpus, no catastrophic
failure class, 1 parse failure vs 4–6 for the others) and **`claude-3.5-haiku` when
relation fidelity is worth the 10× cost** (0.91/0.78, uniquely strong `OWNED_BY` recall
of 1.00 and 96% F1). Avoid `gemini-2.5-flash-lite` for relationships without a
confidence filter: it achieves comparable entity F1 (0.87) but produces 42 spurious
relationships — `OWNED_BY` precision 0.14, `ABOUT` precision 0.45 — far worse than the
other two. High recall, low precision is a bad trade for a graph that traverses edges in
the killer queries: hallucinated edges corrupt every downstream traversal.

---

### 8. What is relation F1 = 0.78 (Haiku) actually telling you? What's in the missing 22%?

F1 = 0.78 on relations means the harmonic mean of precision (0.77) and recall (0.80) is
0.78 across 70 ground-truth relationships. With 12 missed relationships and 15 spurious
ones (from `docs/eval/phase-2b-results.md`), the failure breaks down like this. The 12
missed relationships are concentrated in `MEMBER_OF` (recall 0.08 — only 1 of 12 extracted
correctly) because team membership lives almost entirely in the org-chart document, which
truncates at the `max_tokens=2000` cap; haiku produced 4 parse failures on large documents
for the same reason. The 15 spurious relationships are dominated by `ABOUT` over-extraction
(e.g. `D-0007 ABOUT user-store` because the text mentions user-store in the context of
auth-service mTLS) and `DEPRECATES` confusion (`D-0003 DEPRECATES core-monolith` when the
text is "no new feature work in core-monolith" — an ABOUT, not a deprecation). The 22%
gap is not uniformly distributed: haiku is near-perfect on `APPROVED_BY` (F1 0.96),
`DEPENDS_ON` (0.95), and `OWNED_BY` (0.96) — the relationship types concentrated in
structured decision records and service catalogs that fit inside the token window. The
problem is precisely the types concentrated in the one large document that truncates. This
is the strongest argument for chunking as the highest-ROI next change.

---

### 9. The `max_tokens=2000` truncation hurt `MEMBER_OF`/`OWNED_BY` recall. Why does chunking fix this, and what's the trade-off chunking introduces?

The truncation problem is that the org-chart document (which contains nearly all `MEMBER_OF`
relationships) and the service-catalog document (which contains most `OWNED_BY` edges) each
exceed 2,000 output tokens when combined with the ~220-line prompt. The model hits the cap
and silently drops everything after it — the tail of a long document simply never reaches
the extractor. Chunking fixes this by splitting a large event into overlapping windows (e.g.
1,500-token chunks with 200-token overlap) and running extraction independently on each
window. The graph writer already supports this because `MERGE` + `source_event_ids`
set-union is idempotent: if `auth-service` appears in chunk 1 and chunk 3 of the same
document, both extractions `MERGE` onto the same node and the second just adds another
`source_event_id`. No changes to the write path are needed. The trade-off is cost and a
stitching problem. Cost: the ~220-line prompt is re-sent with each chunk, so a 3-chunk
document costs 3× the prompt tokens. Stitching: an entity mentioned only by name in chunk
1 and depended on only in chunk 3 requires the extractor in each chunk to be context-aware;
if chunk 3 names `it depends on that system` without enough context, extraction fails.
Overlap mitigates this but does not eliminate it. For the current corpus (only a handful of
mega-documents), chunking is the documented highest-ROI improvement.

---

### 10. If extraction is wrong, how does the system stay honest about it?

Three interlocking mechanisms make failure legible rather than hidden. First, the
`extraction_runs` table in Postgres is an audit log of every pipeline invocation —
created in `failed` status before any LLM call, flipped to `success` only after a clean
parse-and-write. A failed extraction produces a row with `status="failed"` and an
`error_message` carrying the `ExtractionParseError`'s raw response and stage. At any
point, `SELECT status, COUNT(*) FROM extraction_runs GROUP BY status` tells you exactly
how many events failed and why. Second, every edge in Neo4j carries `confidence` (the
model's per-assertion score, 0–1), `extracted_by` (e.g. `openai/gpt-4o-mini@2b-v1`), and
`source_event_id`. Confidence is well-calibrated (mean 0.92 on correct, 0.82–0.90 on
incorrect across all three models), so a query-time `WHERE r.confidence > 0.7` filter
trades recall for precision on the traversals the killer queries actually run. `extracted_by`
means edges from a model version later found unreliable can be queried and purged without
touching edges from a better model. Third, the eval harness in `backend/app/eval/` scores
the extractor's `ExtractionResult` against ground truth from `narrative.py` and emits a
Markdown report with per-type precision/recall/F1, failure-mode counts, and three
worst-case examples per category — each showing the model's own `evidence_quote` alongside
what was expected. The honest 0.78 relation F1 with a named failure taxonomy is what goes
in the interview; claiming 0.95 without failure analysis would be worse than useless.

---

## Key Concepts to Whiteboard

These are the 5 concepts from Phase 2B you should be able to sketch or explain from memory
in under 5 minutes each.

1. **The extraction pipeline data flow with the 6 modules.** Draw a horizontal flow:
   `Postgres events` → `prompts.py` (prompt builder) → `client.py` (OpenRouter, JSON-mode,
   retry) → `parser.py` (Pydantic strict validation) → `graph_writer.py` (Neo4j MERGE,
   provenance) → `extraction_runs` audit (Postgres). Below the flow, draw the eval harness
   branch: the eval runs the extractor (`runner.py`) and compares its `ExtractionResult`
   output to ground truth from `ground_truth.py` — it judges the extractor's output, not
   the Neo4j graph. Label the separation point and explain why independence matters (swap
   models without touching eval, rewrite eval without touching extractor).

2. **Precision/recall/F1 applied to one concrete entity-extraction example.** Take the
   `MEMBER_OF` type for gpt-4o-mini (from the eval report): ground truth = 12 relationships,
   extracted TP = 0, FP = 5, FN = 12. Precision = 0/(0+5) = 0.00. Recall = 0/(0+12) = 0.00.
   F1 = 2×(0×0)/(0+0) = 0.00. Contrast with `APPROVED_BY` for gpt-4o-mini: TP=12, FP=0,
   FN=0 → P=1.00, R=1.00, F1=1.00. Explain why F1 is the right summary metric when
   precision and recall trade off (low-precision gemini vs low-recall gpt-4o-mini both hurt
   downstream traversal quality, just differently).

3. **The failure-mode taxonomy with 1 example per category.** Write the 7 categories:
   missed_entity, spurious_entity, wrong_entity_type, missed_relationship,
   spurious_relationship, wrong_relationship_type, alias_not_merged. For each, give the
   canonical example from the eval report: e.g. wrong_entity_type → `event-bus` extracted
   as Service when it is a System; spurious_relationship → `D-0007 ABOUT user-store` because
   the text mentions user-store in the mTLS context; alias_not_merged → `ben-smith` surfaces
   as `['Ben Smith', 'ben', 'bsmith', 'ben.smith@northwind.io']`. Explain which are bugs
   (wrong_entity_type, spurious), which are Phase-3B debt (alias_not_merged), and which are
   ground-truth-strictness questions (some ABOUT over-extraction is defensible).

4. **How `source_event_ids` carries provenance from Postgres → Neo4j.** Draw a Postgres
   `events` row: UUID `e1a2b3c4...`, content `"legacy-auth is deprecated."`. Show the
   extraction pipeline extracting `legacy-auth` (System) and writing it to Neo4j with
   `source_event_ids = ["e1a2b3c4..."]`. Draw a second extraction from a different event
   (UUID `f5d6e7f8...`) that also mentions `legacy-auth`: the MERGE statement does a
   set-union, giving the node `source_event_ids = ["e1a2b3c4...", "f5d6e7f8..."]`. Explain
   that this is the provenance contract: every graph node can trace itself back to one or
   more `events` rows, and those rows are immutable — you can always re-read the original
   text that justified the node.

5. **The three-model cost/quality table from memory.**

   | Model | Entity F1 | Relation F1 | Cost |
   |---|---|---|---|
   | gpt-4o-mini | 0.87 | 0.62 | $0.035 |
   | claude-3.5-haiku | 0.91 | 0.78 | $0.347 |
   | gemini-2.5-flash-lite | 0.87 | 0.57 | $0.038 |

   Explain the axes of differentiation: entities are nearly uniform across models
   (person/decision ≈ 1.0 for all); relations are where models diverge. haiku is uniquely
   strong on `OWNED_BY` (F1 0.96) and costs 10×. gemini over-generates edges (42 spurious
   relationships, `OWNED_BY` precision 0.14). Total three-model run: $0.42. Verdict:
   gpt-4o-mini as default; haiku when relation fidelity matters; avoid gemini for edges
   without a confidence filter.
