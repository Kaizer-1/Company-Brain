# Entity Resolution (Phase 3A)

> **Status:** locked in Phase 3A. Decisions captured in [ADR 0014](../decisions/0014-entity-resolution-tiered-confidence.md)
> and [ADR 0015](../decisions/0015-merge-decisions-audit-table.md). This document is the
> ground truth for the resolver's behaviour; the code in `backend/app/resolution/`
> implements exactly what is described here.

## Problem statement

The Phase 2B extraction pipeline is, by design, *best-effort on identity*. It keys a
Person node on a slug of whatever surface form the LLM emitted, and keys a Service/System
on the verbatim name. The graph schema (locked in Phase 1B) explicitly defers entity
resolution to Phase 3: "the v1 write path is best-effort and may create duplicate nodes the
schema is designed to later merge."

The consequence is a **fragmented graph**. One real-world entity becomes several nodes, and
the four killer queries break because traversal lands on a fragment that holds only part of
the truth (some of the edges, some of the `source_event_ids`). Three concrete examples,
drawn straight from the `ALIAS_GROUPS` ground truth in
`backend/app/synthetic/narrative.py` and the slugging logic in
`backend/app/extraction/graph_writer.py`:

1. **`alice-chen` (Person, KQ4 approver).** The narrative mentions Alice as
   `"Alice Chen"`, `"alice.chen@northwind.io"`, `"@alice"`, and the nickname `"Al"`. The
   writer slugs each surface form independently, producing up to four Person nodes:
   `alice-chen`, `alice-chen-northwind-io`, `alice`, and `al`. KQ4 ("who approved each
   change to the auth system?") needs Alice's `APPROVED_BY` edges from D-0004, D-0006,
   D-0010 to all hang off **one** node. Fragmented, the approval history is split four ways.

2. **`ben-smith` (Person, KQ4 approver).** Ben's handle changed mid-history from `@bsmith`
   to `@ben` (modelled by `HANDLE_CHANGE_AGE_DAYS` in `company.py`). Older decisions
   reference `@bsmith`; newer ones `@ben`. Without resolution, his pre- and post-rename
   approvals live on two different nodes and KQ4's timeline has a hole.

3. **`auth-service` (Service, KQ4 subject).** Referenced as `auth-service`, `AuthSvc`,
   `the auth service`, and `the auth system`. KQ4 ("what changed about the auth system?")
   and KQ3 (blast radius) both traverse `auth-service`; if `AuthSvc` is a separate node, the
   `DEPENDS_ON`/`ABOUT` edges attached to it are invisible to a query that started at
   `auth-service`.

The mirror-image hazard is the **look-alike pair**: `notifications-api` (a request-accepting
API) and `notification-worker` (a delivery worker) are genuinely different services with
confusingly similar names (`LOOK_ALIKE_PAIRS` in `narrative.py`). A resolver that is too
eager will merge them and corrupt KQ3's blast radius. The whole design is balanced against
this: **a wrong merge is far more damaging than a missed one**, because a missed merge
leaves two correct-but-partial nodes while a wrong merge fabricates a connection that never
existed and is hard to detect downstream.

## Resolution approach: three tiers

Resolution is a decision, per candidate pair, routed through three tiers of increasing cost
and decreasing certainty. The orchestrator (`resolver.py`) runs this per entity type:

```
resolve_graph(driver, session, node_types):
    for node_type in node_types:
        nodes = load_nodes(driver, node_type)          # candidates.py
        pairs = all_pairs_with_similarity(nodes)        # candidates.py + embeddings.py
        for pair in pairs:
            rules = apply_tier1_rules(pair)             # rules.py  -> list[str]
            sim   = pair.similarity
            if rules:                                   # Tier 1: an exact-identity rule fired
                record(auto_merge, tier=1, conf=0.99); merge(pair)
            elif sim >= 0.75:                           # Tier 2: close but no rule -> ask the LLM
                verdict = adjudicate(pair)              # adjudicator.py
                if verdict.same:
                    record(llm_merge, tier=2, conf=verdict.confidence); merge(pair)
                else:
                    record(llm_no_merge, tier=2)
            else:                                       # Tier 3: not even worth asking
                record(below_threshold, tier=3)
```

- **Tier 1 — auto-merge.** A deterministic identity rule matched: shared email, shared
  handle, a curated known-alias, an equal canonical name, or a recorded former name. These
  are *exact-identity* signals — a match is definitional — so we auto-merge at confidence
  0.99 and do **not** let a 384-dimensional sentence embedding veto them. (A nickname like
  "Al" can embed well below 0.75 against "Alice Chen"; gating the rule on similarity would
  wrongly demote a definitional match into the costly, fallible LLM tier.) The pair's
  similarity is still recorded on the audit row. Auto-merges are logged and recorded in
  `merge_decisions`, but not human-reviewed.
- **Tier 2 — LLM adjudicator.** No exact rule fired but the embeddings are close
  (`sim ≥ 0.75`). This is the genuinely uncertain band — including the look-alike trap, where
  names are similar but the entities differ. `anthropic/claude-3.5-haiku` decides, given both
  nodes' properties and a few source-event snippets each, and returns a structured verdict
  with reasoning.
- **Tier 3 — no merge.** No rule and `sim < 0.75`. The pair is recorded as
  `below_threshold` and never sent to the LLM — there is no signal worth paying for.

The auto-merge tier is anchored on a *deterministic rule*, never on raw cosine, because
cosine has no notion of identity — two distinct critical services can sit above 0.95, and a
nickname ("Al") can sit below it. The 0.75 floor only governs the no-rule pairs: above it we
pay an LLM call to adjudicate; below it we leave the pair alone. Requiring a corroborating
rule for every auto-merge is what keeps the false-merge rate near zero.

## Candidate generation

We compare **all pairs within each entity type** (`candidates.py`). Cross-type pairs are not
generated: a Person never merges with a Service, so the only candidates worth scoring share
a label. At the Phase 2B sample scale (~35 nodes, with the largest single type well under
20) this is at most a few hundred comparisons — `C(n,2)`, trivially fast, and we embed each
node once and reuse the vector across its pairs.

This is **O(n²) by construction and we say so plainly.** It does not scale to a million
nodes, and the design does not pretend otherwise. The documented scaling path is **blocking**:
generate candidates only within blocks that share a cheap key (entity type — already done —
plus, at scale, the first character of a normalised name, or a coarse LSH bucket over the
embedding), then fall back to an approximate-nearest-neighbour index (the same pgvector HNSW
index the project already runs for events, or a Neo4j vector index) to fetch the top-k
neighbours of each node instead of scanning all pairs. Blocking turns O(n²) into
O(n·k). None of that is needed at 35 nodes, and adding it now would be unjustified
complexity — it is named as future work, not built.

## Embedding strategy

Embeddings come from **`BAAI/bge-small-en-v1.5`** via `sentence-transformers`, run locally on
CPU (`embeddings.py`). The model is loaded once into a module-level singleton and reused for
every call; the `embed()` function is synchronous (sentence-transformers is sync) and the
orchestrator invokes it through `asyncio.to_thread` so it never blocks the event loop.

Why a local model over a hosted embedding API (OpenAI `text-embedding-3-*`, Cohere, etc.):

- **Cost.** Resolution embeds every node on every run; a local model makes that free. Tier 2
  LLM calls are the only spend, and they are bounded to the genuinely ambiguous pairs.
- **Determinism and reproducibility.** A pinned local model returns byte-stable vectors, so
  the eval numbers reproduce on any machine — consistent with the project's reproducibility
  value and the seeded-generator discipline. Hosted embedding APIs can change underneath you.
- **The production-honest answer.** "We embed locally with a small, well-understood model and
  only pay for the hard cases" is the architecture a cost-conscious team actually ships. It
  is also the honest one: 384-dimensional `bge-small` is good enough for short identity
  strings and we are not pretending we need a frontier embedding model for this.

The cost is image size: sentence-transformers pulls in PyTorch (CPU), adding ~300 MB to the
backend image. That is an accepted trade for free, deterministic, reproducible embeddings.

**Per-entity-type input format.** We embed a single delimited string per node, built from the
identity-bearing fields available on it (falling back to the node key when a field is
absent, since extracted nodes are sparse):

| Type | Embedded string |
|------|-----------------|
| Person | `{display_name}\|{handle}\|{email}` |
| Service | `{canonical_name}\|{aliases joined by space}` |
| System | `{canonical_name}\|{aliases joined by space}` |
| Team | `{canonical_name}\|{display_name}` |
| Decision | `{id}\|{title}` |

The delimiter keeps the fields distinct without inventing prose the model would have to parse
around. For Person we lead with the name forms because those are what vary across aliases
(`Alice Chen` / `@alice` / `Al`); for Service/System we include aliases because that is where
`AuthSvc`-style abbreviations live; for Decision we use `id|title` because two decision
records are the same iff they are the same decision id (resolution there is essentially a
deduplication safety net, not a hard problem).

## Tier 1 rules

Each rule is a pure function in `rules.py` returning a match or `None`, and each docstring
names its false-positive risk. The rules, by type:

**Person**
- `exact_email` — both nodes carry the same non-empty, normalised email. *FP risk:*
  essentially zero; a corporate email address is a unique identifier. The only failure mode
  is a shared role mailbox, which Northwind does not model.
- `exact_handle` — both nodes carry the same non-empty handle (`@alice`). *FP risk:* very
  low within one org; handles are unique. Cross-org reuse is out of scope (single tenant).
- `known_alias` — both nodes' identifying surface forms map, via the curated alias
  dictionary, to the same canonical entity. *FP risk:* only as good as the dictionary; a
  wrong dictionary entry is a wrong merge. See "honest limitations."

**Service / System**
- `exact_canonical_name` — both nodes' canonical names are equal after normalisation
  (case/punctuation-folded). *FP risk:* near zero — but note that post-MERGE the graph rarely
  holds two nodes with byte-identical names, so this rule mostly catches case/whitespace
  variants.
- `known_alias` — as above, over the service alias groups (`auth-service` ⇄ `AuthSvc`).
- `former_name` — one node's canonical name equals the other's recorded former name
  (`legacy-billing` → `billing-v2`). *FP risk:* low; former names are explicit in the
  company definition. The hazard is a name genuinely reused for a different service, which
  the look-alike test guards against.

The **known-alias dictionary** is built from `narrative.ALIAS_GROUPS` (and the company's own
recorded handles/emails/aliases/former names), normalised with the same `normalize()` used by
the Phase 2B matcher, so `@alice`, `Alice Chen`, `Al`, and `alice.chen@northwind.io` all map
to canonical `alice-chen`. In production this dictionary is exactly the kind of mapping you
source from an SSO/HR directory or a service catalog; here it is sourced from the synthetic
narrative that is our single source of truth. This is named, not hidden — see limitations.

## Tier 2 LLM adjudication

When no exact rule decides and the embeddings are merely close, `adjudicator.py` asks
`anthropic/claude-3.5-haiku` (chosen for being cheap, fast, and — per the Phase 2B eval — the
strongest of the three candidate models on this corpus's relational judgement). The prompt:

```
You are deciding whether two graph nodes refer to the same real-world {node_type}.

Node A:
- Properties: {a_props}
- Mentioned in these events: {a_snippets}

Node B:
- Properties: {b_props}
- Mentioned in these events: {b_snippets}

Embedding similarity: {sim:.3f}

Are A and B the same {node_type}? Respond with JSON:
{
  "same": true | false,
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation grounded in evidence from the snippets"
}
```

Context passed: each node's stored properties and **2–3 short snippets** of the source events
that mention it (looked up from Postgres by the node's `source_event_ids`). Snippets are what
let the model reason about *meaning* — that `notifications-api` "accepts notification
requests" while `notification-worker` "delivers notifications off event-bus" — rather than
just surface similarity. Output is validated against a Pydantic model (`LLMVerdict`:
`same: bool`, `confidence: float in [0,1]`, `reasoning: str`); on any parse or validation
failure the adjudicator **falls back to "no merge"**, because the safe default is to leave two
nodes unmerged. Cost is ~$0.001–0.002 per adjudicated pair at haiku pricing; only ambiguous
pairs reach this tier, so a full run costs cents at most (and $0 when Tier 1 resolves
everything and nothing lands in the ambiguous band).

## The `MERGE_INTO` edge model

Merges are **edges, not deletions** — the single most important structural decision here.
When the resolver decides node A (loser) is the same entity as node B (canonical winner):

1. **Pick the winner.** More `source_event_ids` wins (it is the better-attested node); ties
   are broken by lexicographic node id, so the choice is deterministic.
2. **Accumulate provenance.** The loser's `source_event_ids` are unioned onto the winner, so
   the winner ends up carrying the full provenance of the merged entity — exactly what KQ4
   needs to reconstruct a complete approval history.
3. **Write the edge.** `(loser)-[:MERGE_INTO {confidence, tier, created_at}]->(winner)`.
4. **Tombstone the loser.** Set `loser.status = "merged"`. The loser node and its edges stay
   in the graph, untouched.

Queries see the **resolved view** by filtering `WHERE n.status <> "merged"` (and, where
needed, by following `MERGE_INTO` to the canonical node). The same graph, without that
filter, shows the original fragmented view. This gives three properties we care about:

- **Reversible.** Undoing a merge is `DELETE` the `MERGE_INTO` edge and reset
  `loser.status`; no information was destroyed.
- **Provenance-preserving.** Every merge edge records *which tier and confidence* produced it,
  and the `merge_decisions` audit row records *why*.
- **Demo-friendly.** A one-line query toggle flips between the fragmented and resolved graph —
  ideal for showing an interviewer the before/after.

## Eval methodology

Ground truth is `narrative.ALIAS_GROUPS` — the same single-source-of-truth discipline as
Phase 2B (ADR 0013): each `AliasGroup` is a set of surface forms that must collapse to one
canonical entity, and `LOOK_ALIKE_PAIRS` is the negative case that must **not** merge. The
eval (`resolution_eval.py`) seeds a deterministic fragmented graph from those surface forms
(one node per normalised form), runs `resolve_graph`, reads back the `MERGE_INTO` edges, and
computes — overall and per entity type:

- **Precision** = correct merges / all merges. (A "merge" is an unordered pair the resolver
  put in the same group; "correct" means ground truth agrees they are the same entity.)
- **Recall** = correct merges / all true merges (all within-group pairs in ground truth).
- **False-merge rate** = wrong merges / all merges (`1 − precision`); the headline safety
  metric.
- **Missed-merge rate** = missed true merges / all true merges (`1 − recall`).
- **Tier breakdown** — how many merges happened at each tier, and the mean confidence per
  tier — so the report shows *how* recall was achieved, not just that it was.

A mock resolver that reproduces ground truth exactly must score 1.0/1.0; the eval harness is
built and tested against that fixture *before* any real model output is judged, so we know the
metric is measuring the resolver and not itself.

## What's out of scope

- **At-write-time resolution.** This phase runs **post-merge** (walk the existing graph and
  merge). Integrating the resolver into the extraction write path is Phase 4.
- **Human-review UI.** The `merge_decisions` table is the seed for a review queue; the UI is
  Phase 6.
- **Transitive merge logic beyond two hops.** If A→B and B→C are both merged, we record both
  edges but do not collapse to a single canonical chain-walk in this phase; deferred to v2.
- **Cross-type resolution.** Service↔System fuzziness (is `legacy-auth` a System or a
  Service?) is a real ambiguity the schema names; we do not attempt to resolve across types
  here.

## Honest limitations

- **Closed entity-type set.** Person, Service, System, Team, Decision only, over the
  controlled vocabulary of `synthetic-company.md`. This is **not** general open-world entity
  resolution and we do not claim it is.
- **The ground truth is synthetic data we wrote.** `ALIAS_GROUPS` is both the alias
  dictionary feeding the Tier 1 `known_alias` rule *and* the eval ground truth. That makes the
  `known_alias` rule partly circular: it will resolve exactly the aliases we told it about.
  The honest reading is that `known_alias` models a **curated identity directory** (in
  production: SSO/HR/service-catalog), and the eval's job is to confirm the *machinery* —
  candidate generation, the merge writer, provenance accumulation, the audit trail, and the
  embedding/LLM tiers for everything the dictionary does *not* cover — works end to end. The
  embedding and LLM tiers are what generalise beyond the dictionary; the look-alike negative
  case is what proves the resolver does not merge indiscriminately.
- **English only.**
- **No incremental resolution as the graph grows.** Each run resolves the current graph from
  scratch; there is no streaming/at-write-time resolution and no re-resolution trigger when
  new events arrive. That is Phase 4.
