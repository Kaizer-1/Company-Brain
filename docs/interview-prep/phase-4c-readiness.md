# Phase 4C — Interview Readiness

Ten Q&A pairs on the structural-tools subphase. Each answer is the version I'd give a senior
engineer probing the design.

---

### 1. Why four structural tools and not three or five?

Four is the minimum set that covers the structural question classes the existing tools failed,
with no overlap between tools. The classes are: read one entity's properties (`get_entity`),
walk one typed hop (`neighbors`), list a type (`enumerate`), and count a type (`aggregate`).
Three would force one tool to do two jobs — e.g. merging enumerate and aggregate means a
single tool returns either a list or a count depending on a flag, which muddies both the
router's decision and the result shape. Five would mean adding a tool that overlaps an
existing one; the candidates (recency, find-orphans, provenance) are all *parameters* on
tools I already have, not new question classes. The discipline is scope-coverage, not
accumulation: a tool earns its place only by covering something nothing else can.

### 2. How does the router disambiguate KQ1 (multi-hop ownership) from `neighbors`?

The priority rule in the router prompt is "prefer the more specific route", and the KQs are
the most specific patterns. The concrete boundary: route to `kq1` only when a *decision or a
deprecated system* is part of the ownership chain — that is KQ1's whole reason to exist
(decision → deprecated system → dependent service → owner). A bare "who owns auth-service?"
has no decision and no deprecation; it's a single `OWNED_BY` hop, so it's `neighbors`. I
encode this as an explicit example pair in the prompt and as the conceptual two-stage
structure: the model first decides the question is *structural* vs *analytical*, which already
separates most cases, then applies the priority rule on the genuine overlaps. The same logic
separates `kq3` (transitive blast radius) from `neighbors` (one direct hop).

### 3. How does `enumerate` handle "the most recent decision" and "services without owners"
without dedicated routes?

Both are parameters. Recency is `order_by="valid_from_desc", limit=1` — ordering plus a limit,
which `enumerate` already needs for general listing, so "most recent" is just a particular
parameterisation. Orphan-finding is `has_no_edge="OWNED_BY"`, a negative-existence filter
implemented as `NOT EXISTS { MATCH (n)-[r]->() WHERE type(r) = $has_no_edge }`. Folding these
in matters because each avoided route is one less thing the single-call router must
disambiguate; "most recent decision" vs "list decisions by date" would be two routes split on
a distinction that is really a parameter value. The cost is that `enumerate`'s parameter
surface is large and load-bearing, which is why I built it first, end-to-end, and tested every
parameter against a real Neo4j container before writing the other three tools.

### 4. Walk me through the verification exception for structural tools.

Normally every answer must carry an inline `[evt:UUID]` that exists in the tool's provenance,
and an uncited answer fails (ADR 0025). An aggregate count breaks the assumption: "there are 9
active decisions" is produced by `count(n)`, a deterministic query — there is no single event
to cite. So when the route is structural *and* the tool returned zero events, verification
skips the citation check and marks the answer verified with empty citations, and synthesis
uses a citation-free schema for that case. The grounding contract still holds because the LLM
isn't fabricating — it's phrasing a number the typed query computed, and the query is tested.
Crucially, the skip is narrow: a structural tool that *did* return events (most `enumerate`
and `get_entity` calls, since nodes carry `source_event_ids`) is held to the full check. The
predicate is `route ∈ STRUCTURAL_ROUTES and not available_event_ids`.

### 5. What was the biggest surprise implementing this, and how did you handle it?

The live graph's identity model was nothing like the spec's assumption. The spec drafted
`MATCH (n {canonical_id: $entity_id})`, but only Person nodes have `canonical_id` — services
use `canonical_name`, decisions use `id`, messages use `id`, and Person/Team have no `status`
property at all. A `canonical_id`-only match would have silently returned empty for every
non-person lookup. I caught it in the pre-implementation verification step by running
`db.schema.nodeTypeProperties()` against the running database before writing code. The fix was
a heterogeneous, case-insensitive identity predicate matching across all identity fields plus
`handle`, and a `coalesce`-based display name. This is the single most important reason the
tools work on the real graph rather than only on idealised test fixtures.

### 6. Why not just let the LLM write Cypher for these?

Same reasoning as ADR 0023 for the KQs. Generated Cypher reintroduces the entire
query-injection, runtime-parse-error, and silent-wrong-traversal surface. With typed functions
the behaviour set is small, enumerable, and testable: an interviewer can probe all ten routes
and I can write a deterministic test for each. The honest trade-off is capability —
generated Cypher would unlock arbitrary structural queries including path-finding. I judged
that the four typed tools cover the observed question distribution, and that a flaky generator
is a weaker portfolio position than a small, reliable, defensible tool set with a documented
gap. If the typed set saturated, constrained-Cypher generation (with a validator and a
read-only role) would be the next step, not free-form generation.

### 7. What's the cost and latency impact of Phase 4C?

Effectively flat. The structural tools add no LLM call — routing is still one classification,
synthesis is still one generation, and the tool itself is millisecond Cypher exactly like the
KQs. So per-question cost and latency track the Phase 4A baseline. The one measurable change is
the router prompt: it grew from a flat six-route list to a two-stage prompt with twenty
few-shots, adding a few hundred input tokens to the routing call. At the router model's pricing
that's a fraction of a cent per question, quantified in the eval report. There's no extra
round-trip to a database beyond the single typed query, and `enumerate`/`aggregate` run a
small count query plus a fetch — two cheap reads in one session.

### 8. How is the parameterised-Cypher rule upheld when labels and edge types are dynamic?

Cypher can't parameterise a label in `MATCH (n:$Label)`, so instead of string-interpolating
the label I use `$node_type IN labels(n)` — the label is a bound parameter checked against the
node's label list. Edge types use `type(r) = $edge_type`; direction uses `startNode(r) = n`
and `endNode(r) = n`; negative-existence uses `EXISTS { ... WHERE type(r) = $has_no_edge }`.
All fully parameterised, zero injection surface. The one place I interpolate is `ORDER BY`,
which Cypher genuinely cannot parameterise — and there the value comes from a closed `order_by`
Literal mapped through a fixed dictionary to a hardcoded fragment, so no user or LLM free text
ever reaches the query string. This keeps the CLAUDE.md "parameterised queries only" rule
intact while still allowing dynamic structural queries.

### 9. What would change for production?

Three things. First, `$type IN labels(n)` scans by label instead of using a label index — fine
at this corpus (tens of nodes) but at 10× I'd switch enumerate/aggregate to a small per-label
query registry (validated label → indexed `MATCH (n:Label)`) to regain index use, keeping the
no-injection guarantee. Second, the router saturates around ten to twelve routes; production
would move to genuine multi-stage routing — a cheap shape classifier gating per-shape route
classifiers, or a retrieval-based router selecting few-shots by question similarity. Third, I'd
add lightweight provenance even to aggregates (the set of node events behind the count) so the
verification skip could be removed and every answer cited uniformly. None of these change the
tool interfaces — they're behind-the-tool optimisations the architecture already isolates.

### 10. There's a path-finding gap. How would you fill it, and why defer it?

"How is A connected to B?" needs variable-length traversal (`shortestPath`/`allShortestPaths`
or bounded variable-length patterns) and a *path* result shape — an ordered list of nodes and
edges — that none of the four fixed tools produce. Filling it means a fifth tool,
`find_path(source, target, max_hops)`, returning a typed path with per-edge provenance, plus a
new route and a frontend renderer that draws the chain. I deferred it because it isn't in the
observed question distribution that motivated 4C (lookups, traversals, lists, counts), and
adding a tenth-then-eleventh route pushes the single-call router past its reliable ceiling —
which would be the moment to introduce multi-stage routing anyway. So path-finding is bundled
with the routing-scale upgrade as a coherent future phase, documented as deliberate scope, not
forgotten work.
