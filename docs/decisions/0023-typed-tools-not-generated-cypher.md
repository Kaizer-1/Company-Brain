# ADR 0023 — Typed Tools, Not LLM-Generated Cypher

## Status

Accepted

## Context

The Phase 4A agent must turn a natural-language question into a graph query. Two affordances
are available: (a) give the LLM the graph schema and let it author Cypher, or (b) expose a
fixed set of Python functions the LLM chooses between. The graph is the project's spine and
the demo's thesis is *grounded, defensible* answers; an unsafe or unpredictable query layer
undermines exactly the property the project is selling. The agent runs read-only against a
synthetic corpus, but the design must still tell a credible production-safety story.

## Decision

The agent's entire toolbox is five **typed Python functions** — the four killer queries plus
`hybrid_search` — called with validated parameters. No LLM ever authors Cypher; the LLM only
*chooses a route* and *extracts parameters*, both constrained by Pydantic.

## Alternatives Considered

### Option A — LLM-generated Cypher with a safety validator

**What it is**: prompt the model with the schema; it emits Cypher; a validator rejects writes
and dangerous patterns before execution.

**Pros**:
- Maximally flexible — can answer questions outside the four KQ shapes.
- Impressive in a demo when it works.

**Cons**:
- Adds a query-injection and runtime-parse-error surface that a validator can only partially
  close (a read-only `MATCH` can still be wrong, slow, or subtly misleading).
- Non-enumerable behaviour: you cannot tell an interviewer the complete set of things the
  agent can do.
- The failure mode is a confidently wrong grounded-looking answer — the worst outcome for a
  provenance-first project.

### Option B — Typed tools (chosen)

**What it is**: the LLM picks one of six routes and extracts parameters; Python executes the
corresponding typed function.

**Pros**:
- Zero generated-query surface: no injection, no parse errors, no surprise traversals.
- Small, enumerable behaviour set that is fully testable and probeable.
- Reuses the proven, provenance-returning KQ functions verbatim.

**Cons**:
- Cannot answer questions outside the four KQ shapes with a *typed* traversal — those fall to
  `hybrid_search`, which is less precise than a bespoke query would be.

## Consequences

**Enables**: a complete unit-test matrix over the agent's capabilities; a clean safety story;
reuse of the 3B provenance shapes with no new query code.

**Constrains**: novel structural questions (e.g. "shortest path between two people") have no
typed tool and degrade to semantic search.

**Locked into**: the five-tool toolbox. Adding capability means adding a typed tool (and an
eval), not loosening the query layer.

**At larger scale / in production**: if real users needed open-ended structural queries, the
right move is to add more *typed, parameterised, tested* query templates — or a sandboxed,
read-only, cost-bounded query service — not to hand the LLM a Cypher console.

## Interview Defense

> "The agent calls Python functions, not generated Cypher. I chose that because the project's
> whole value is grounded, defensible answers, and a generated-query layer adds an
> injection-and-hallucination surface for marginal capability — the four typed queries cover
> the demo questions and semantic search covers the rest. The trade-off is I can't answer
> arbitrary structural questions; the fix is more typed tools, not a Cypher console. Yes, I
> could generate Cypher — I chose not to, and that's the stronger position."
