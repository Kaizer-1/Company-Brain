# ADR 0029 — Router Prompt Redesign: Two-Stage Conceptual Routing at Ten Routes

## Status

Accepted

## Context

Phase 4A's router prompt is a flat list of six routes with 3–6 few-shot examples. Phase 4C
takes the route space to ten (`kq1–4`, `search`, `get_entity`, `neighbors`, `enumerate`,
`aggregate`, `unknown`). A flat list at ten routes raises ambiguity: "who owns auth-service?"
could be `kq1` or `neighbors`; "what depends on payments-api?" could be `kq3` or `neighbors`.
The router is a single LLM call (ADR 0024) — we cannot afford a sprawling, ambiguous prompt.

## Decision

**Restructure the router prompt as two-stage *conceptual* routing inside one LLM call:**
first decide the question SHAPE (analytical / structural / retrieval / out-of-scope), then
pick the route within that shape. Add a explicit "prefer the more specific route" priority
rule with the KQ-vs-structural boundary spelled out, and two few-shot examples per route
(20 total) grouped by shape.

It remains **one** LLM call producing one `RouteDecision`; "two-stage" is a reasoning
scaffold in the prompt, not a second request.

## Alternatives Considered

### Option A — Two-stage conceptual routing, one call (chosen)

**Pros**: groups the ten routes into four conceptual buckets, so the model first makes an
easy 4-way decision then an easy within-bucket choice; the priority rule resolves the genuine
KQ-vs-structural overlaps; no added latency or cost (still one call).

**Cons**: longer prompt (~20 few-shots) → marginally higher router token cost.

### Option B — Keep the flat list, add more few-shots

**Pros**: minimal change.

**Cons**: ten flat routes with overlapping shapes is exactly the ambiguity that drops
accuracy; more examples bloat the prompt without giving the model a decision structure.

### Option C — Two actual LLM calls (shape classifier → route classifier)

**Pros**: each call is simpler.

**Cons**: doubles router latency and cost for a classification that fits comfortably in one
call; contradicts ADR 0024's single-classification design.

## The disambiguation rules (the substance)

- **Prefer the more specific route.** The KQs are the most specific patterns.
- **kq1 vs neighbors**: use `kq1` only when a *decision or deprecated system* is part of the
  ownership chain; a plain "who owns X" is `neighbors` (OWNED_BY).
- **kq3 vs neighbors**: use `kq3` for the *transitive* blast radius / "what breaks if it
  fails"; a single "what depends on X directly" is `neighbors` (DEPENDS_ON, in).

## Consequences

**Enables**: reliable routing at ten routes from a single call; the prompt doubles as
human-readable documentation of the agent's capability surface.

**Constrains**: the prompt grows with each route; the conceptual buckets are the organising
principle, so a new tool must fit one of the four shapes.

**Locked into**: the shape taxonomy. A route that fits no shape (e.g. a side-effecting action
tool) would force a taxonomy revision.

**At larger scale / in production**: beyond ~10–12 routes the single call saturates; the next
step is genuine multi-stage routing (a cheap shape classifier gating per-shape route
classifiers) or a retrieval-based router that selects few-shots by question similarity.

## Interview Defense

> "At ten routes a flat prompt gets ambiguous, so I gave the model a decision structure:
> first pick the question shape — analytical, structural, retrieval, out-of-scope — then the
> route within it. It's still one LLM call; the two stages are a reasoning scaffold, not a
> second request. The real work is the priority rule that resolves KQ-vs-structural overlaps,
> e.g. 'what depends on X' is a single hop (neighbors) unless the question asks for the
> transitive blast radius (kq3). Measured route accuracy held at the target after the change."
