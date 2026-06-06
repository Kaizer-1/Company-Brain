# Structural Tools (Phase 4C)

> Four typed Cypher tools that let the agent answer questions about the *graph itself* —
> single-entity lookups, typed one-hop traversals, enumeration, and counting — the class of
> question the four killer queries and semantic search cannot answer correctly.

## 1. The gap they close

Phase 4A gave the agent five routes: the four killer queries (analytical multi-hop patterns)
and `hybrid_search` (open-ended text retrieval). Real-user testing surfaced a third class of
question that fits neither:

| Question | What 4A did | Why it failed |
|----------|-------------|---------------|
| "List all employees" | search returned 7 of 13 people | only 7 appear in events that semantically match "list of employees" |
| "Who's on the payments team?" | search synthesised one or two names | retrieval ranks by similarity, not membership edges |
| "What's the status of D-0006?" | search returned events mentioning D-0006 | the *property* lives on the node, not in event text |
| "How many active decisions?" | search cannot count | retrieval has no aggregation |

These are **graph-native** questions: they require typed traversals and aggregations over the
graph's structure, not retrieval over event text. Phase 4C adds four tools that answer them,
completing the agent's read-only structural + retrieval coverage.

## 2. The four tools

Each is a typed parameterised Cypher function in `app/queries/`, returning a Pydantic
`QueryResult[T]` with provenance — structurally identical to the four KQs. The agent tool
node in `app/agent/tools.py` is thin glue: validate `tool_input` against the tool's `*Input`
schema, call the function, write `tool_output` + `available_event_ids`.

### `get_entity` — single-node property lookup
Input: `entity_id`, optional `node_type_hint`. Returns the matched node's type, properties,
and a count of its outgoing/incoming edge types. Answers "what's D-0006's status?",
"what's @alice's handle?". Returns `node_type="not_found"` when nothing matches.

### `neighbors_of_entity` — typed one-hop traversal
Input: `entity_id`, optional `edge_type`, `direction` (`out`/`in`/`both`), `limit`. Returns
the directly-connected nodes. Answers "who's on the payments team?" (`MEMBER_OF`, `in`),
"what does auth-service depend on?" (`DEPENDS_ON`, `out`).

### `enumerate_by_type` — filtered listing (the load-bearing one)
Input: `node_type`, `status`, `order_by`, `limit`, `has_no_edge`, `team_filter`. Returns all
nodes of a type with a pre-limit `total_count`. This tool **absorbs two would-be tools**:
- *recency* — "the most recent decision" is `order_by="valid_from_desc", limit=1`.
- *find-orphans* — "services with no owner" is `has_no_edge="OWNED_BY"`.

Folding these into parameters keeps the route space small (ADR 0028). `total_count` is
load-bearing: it lets synthesis say "all 13 people" vs "the first 100 of 1247 messages".

### `aggregate_by_type` — counting / grouping
Input: `node_type`, `status`, `group_by`, `order`, `limit`. Returns a `total` always, plus
`groups` when `group_by` is set. Answers "how many active decisions?" (total) and "which team
owns the most services?" (`group_by="OWNED_BY"`).

## 3. Parameter design over route proliferation

The design philosophy is **scope-coverage-not-accumulation**: a new tool earns its place only
by covering a question class the existing tools can't. Tools that would overlap are folded in
as parameters. This is why there are four tools, not seven — recency, orphan-finding, and
provenance-lookup are parameters, not routes. The router after 4C disambiguates ten routes
from a single LLM call; that is the practical ceiling, and parameter-richness (not more
routes) is what carries the variation (ADR 0029).

## 4. Cypher that survived contact with the real graph

The spec's first draft assumed every node has `canonical_id`/`canonical_name`. The live graph
disagrees (verified, not assumed): Person→`canonical_id`, Service/System/Team→`canonical_name`,
Decision→`id`+`title`, Message→`id`; Person/Team carry no `status` and one Service has a stray
`deployed` value. Three design choices follow:

1. **Identity matching is heterogeneous and case-insensitive.** `identity_predicate` matches
   `entity_id` against `canonical_id`, `canonical_name`, `id`, and `handle`, all via
   `toLower(...)` — team names are capitalised (`Payments`) while services/people are lower
   (`payments-api`, `diego-ramirez`), and neither the router nor the user can be trusted to
   match case. A uniform display name is `coalesce(canonical_name, canonical_id, title, id)`.

2. **Labels and edge types are parameters, never interpolated.** Instead of `MATCH (n:$Label)`
   the tools use `$node_type IN labels(n)`, `type(r) = $edge_type`, `startNode(r) = n` for
   direction, and `EXISTS { ... WHERE type(r) = $has_no_edge }` for negative-existence. This
   honours the "parameterised queries only" rule with zero Cypher-injection surface. The lone
   exception is `ORDER BY` (Cypher can't parameterise it), mapped from a closed `order_by`
   Literal to a fixed fragment — no free text reaches the query string.

3. **Status is normalised.** `active` = not merged/deprecated/superseded; `deprecated` = the
   ended-but-not-merged set; `all` = everything except resolution losers. Defined on
   `coalesce(status,'active')` to absorb the inconsistent real values. Every query also keeps
   the resolved-view discipline (`<> 'merged'`).

## 5. Verification for event-less answers

Most structural results carry events (nodes have `source_event_ids`), so the normal
provenance check (ADR 0025) applies. But an aggregate count has no event to cite — the fact
is produced by deterministic Cypher, not the LLM. For that case synthesis uses
`synthesis_structural.txt` + the citation-optional `StructuralAnswer` schema, and
`verify_provenance` skips the inline-citation check and marks the answer verified with empty
citations (ADR 0030). The grounding contract holds: the number is as trustworthy as the typed
query, which is tested.

## 6. Honest limitations

- **Graph sparsity.** Extraction found only 2 `MEMBER_OF` edges (both → Payments), so "who's
  on the Growth team?" returns nobody. The tool is correct; the *data* is sparse. This is a
  property of the extracted graph, not a tool bug.
- **No `role`/display name on Person.** A Person has `canonical_id`, `handle`, `email` (often
  null) — there is no "role" property, so `get_entity` answers "what's Alice's role?" with the
  properties it has and an honest "no role recorded".
- **Not covered: path-finding and generated Cypher.** "How is A connected to B?" needs
  variable-length traversal and a different result shape; arbitrary structural queries would
  need generated Cypher, which ADR 0023 rejected. Both are deferred (ADR 0028).

## 7. Where this leaves the agent

After 4C the agent covers: multi-hop analysis (KQ1–4), hybrid retrieval (search), property
lookup (`get_entity`), typed neighbours (`neighbors`), enumeration with filters (`enumerate`),
aggregation (`aggregate`), and out-of-scope refusal (`unknown`). That is complete coverage for
read-only structural and retrieval questions over the knowledge graph.

The four tools also share one operational property worth calling out: they add **no extra LLM
call**. Routing is still one classification and synthesis is still one generation — the tool
itself is millisecond Cypher, exactly like the KQs. So 4C widens the agent's capability
surface without moving its cost or latency profile, which is why the eval's per-question cost
and latency stay flat against the Phase 4A baseline. The only prompt-cost change is the larger
router prompt (twenty few-shots instead of a flat list), which adds a few hundred input tokens
to the routing call — quantified in `docs/eval/phase-4c-structural-results.md`.
