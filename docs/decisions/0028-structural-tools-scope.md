# ADR 0028 — Four Structural Tools, Not Seven; Scope and Cypher Strategy

## Status

Accepted

## Context

Phase 4A's five-route agent (KQ1–4 + search) answers analytical and open-ended questions
but fails a whole class of *structural* questions about the graph itself: "list all
employees" (search returns 7 of 13 because only 7 appear in semantically-matching events),
"who's on the payments team?" (search synthesises one or two names), "how many decisions are
active?" (search cannot count). These are graph-native traversals, not text retrieval. We
need typed Cypher tools — but we must add the *minimum* set that closes the gap without
destabilising the router (each new route is one more thing the classifier must disambiguate).

## Decision

**Add exactly four structural tools — `get_entity`, `neighbors_of_entity`,
`enumerate_by_type`, `aggregate_by_type` — each a typed parameterised Cypher function in
`app/queries/`, mirroring the four KQs.** Recency, orphan-finding, and provenance lookups are
folded into these four as *parameters*, not added as separate routes. All Cypher is
parameterised (no LLM-generated Cypher, no string-interpolated labels), reusing ADR 0023's
reasoning.

## Alternatives Considered

### Option A — Four tools with rich parameters (chosen)

**What it is**: `enumerate_by_type` carries `order_by` (absorbing "most recent decision"),
`has_no_edge` (absorbing "services without an owner"), `status`, `team_filter`, `limit`;
`get_entity` returns `source_event_ids` (absorbing "where did we learn X"). Nine routes total
after 4C.

**Pros**:
- Covers every observed structural question class.
- Nine routes is at the upper bound the single-call router can disambiguate reliably.
- Parameter design, not route proliferation, carries the variation.

**Cons**:
- `enumerate_by_type`'s parameter surface is large and load-bearing — it must be tested hard.

### Option B — Seven tools (separate recency, orphans, provenance routes)

**Pros**: each tool is tiny and single-purpose.

**Cons**: twelve routes overwhelms single-call classification; "most recent decision" vs "list
decisions ordered by date" become two routes the LLM must split on a distinction that is
really just a parameter. Router accuracy drops; the marginal capability is zero.

### Option C — One generic `graph_query` tool taking LLM-generated Cypher

**Pros**: covers everything, including path-finding, with no new routes.

**Cons**: reintroduces the entire injection / parse-error / silent-wrong-traversal surface
ADR 0023 rejected. Unbounded, unenumerable behaviour; not testable end-to-end.

## Cypher strategy (the load-bearing implementation decision)

The live graph's identity model is **heterogeneous** (verified against the running DB, not
assumed): Person→`canonical_id`, Service/System/Team→`canonical_name`, Decision→`id`+`title`,
Message→`id`; Person/Team carry no `status` property and one Service has a stray `deployed`
value. So:

- **Identity** is matched case-insensitively across every identity field plus `handle`
  (`structural_common.identity_predicate`) — a `canonical_id`-only match would only ever hit
  Person nodes.
- **Labels and edge types are parameters, not interpolated**: `$node_type IN labels(n)`,
  `type(r) = $edge_type`, `startNode(r) = n` for direction, and
  `EXISTS { ... WHERE type(r) = $has_no_edge }` for negative-existence. This honours the
  CLAUDE.md "parameterised queries only" rule with zero Cypher-injection surface. The single
  exception is `ORDER BY`, which Cypher cannot parameterise; it is mapped from a closed
  `order_by` Literal to a fixed fragment, so no free text reaches the query string.
- **Status is normalised**: `active` excludes merged + deprecated + superseded; `deprecated`
  is the ended-but-not-merged set; `all` is everything except resolution losers. Defined on
  `coalesce(status,'active')` because the real status values are inconsistent.

## Deliberately NOT covered

- **Path-finding** ("how is A connected to B?") — needs variable-length traversal and a
  result shape the four fixed tools don't have. Deferred to a possible future phase.
- **Constrained-Cypher generation** — would unlock arbitrary structural queries but at the
  cost ADR 0023 already rejected.

## Consequences

**Enables**: the agent now answers single-entity lookups, typed traversals, enumeration, and
counting — completing read-only structural + retrieval coverage. The original failing
question "name all the employees" now routes to `enumerate` and returns all 13 people.

**Constrains**: nine routes is the ceiling for single-stage routing; a tenth structural tool
should trigger multi-stage routing instead.

**Locked into**: the four tool shapes and their Pydantic result types; changing them ripples
to the router prompt, the eval, and the frontend renderers.

**At larger scale / in production**: `$type IN labels(n)` scans by label rather than using a
label index; at 10× corpus the enumerate/aggregate tools would switch to interpolated-but-
validated labels (or a small per-label query registry) to regain index use. Path-finding and
constrained Cypher become worth their cost once the typed set is saturated.

## Interview Defense

> "We added four structural tools, not seven, because the router is a single LLM call and
> every extra route costs disambiguation accuracy. Recency and orphan-finding are parameters
> on `enumerate`, not their own routes — folding variation into parameters keeps the route
> space small. All Cypher stays typed and parameterised, including labels and edge types via
> `$type IN labels(n)` and `type(r) = $edge`, so there's no injection surface. The honest gap
> is path-finding, which needs a different result shape and is deferred."
