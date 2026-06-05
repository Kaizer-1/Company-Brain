# ADR 0024 — Route-Then-Execute, Not End-to-End Tool-Calling

## Status

Accepted

## Context

The agent has six possible actions (four KQs, semantic search, refuse). Two architectures can
pick among them: (a) a single LLM "tool-calling" agent that sees all tool schemas and decides,
possibly over multiple turns, which to call; or (b) a fixed pipeline that first *classifies*
the question to exactly one route with a constrained LLM call, then executes that route. The
project values legibility, testability, and a small enumerable behaviour set, and the agent is
single-step by design (no multi-tool plans needed for these questions).

## Decision

A **route-then-execute** LangGraph state machine: one constrained classification call
(`classify_route`) selects exactly one of six branches, the branch executes, then a separate
synthesis step writes the answer. Routing and answering are distinct nodes with distinct
prompts and distinct schemas.

## Alternatives Considered

### Option A — End-to-end tool-calling agent

**What it is**: give one LLM all five tool schemas and a system prompt; it emits tool calls,
sees results, and decides when to answer (the classic ReAct / function-calling loop).

**Pros**:
- Can chain tools (call KQ3 then KQ1) without extra design.
- Fewer moving parts on paper — one prompt, one loop.

**Cons**:
- The control flow lives inside the model; you cannot unit-test "does this question pick KQ3"
  in isolation, only the whole loop.
- Looping and multi-call behaviour is hard to bound for cost and latency.
- Misclassification and answer generation are entangled in one call, so a routing bug and a
  grounding bug look the same in the logs.

### Option B — Route-then-execute (chosen)

**What it is**: a constrained classifier node, then a fixed branch, then a synthesis node, then
a verification node.

**Pros**:
- Each stage is independently testable: router tests, tool tests, synthesis tests,
  verification tests (see `backend/tests/agent/`).
- Bounded cost and latency: at most two LLM calls plus retries.
- A misroute and a grounding failure are separate, observable events.
- The route enum is a clean contract for the UI ("KQ3 — Blast radius" badge) and the eval
  (route accuracy is a single number).

**Cons**:
- No native multi-tool chaining — a question needing two KQs is not expressible (none of the
  demo questions need it).
- A routing mistake sends the question down one wrong branch (mitigated: the answer is still
  grounded, and the fallback is always `search`, never a refusal).

## Consequences

**Enables**: a per-stage test matrix; a single route-accuracy metric; a legible trace the UI
renders directly; cost/latency bounds.

**Constrains**: single-tool answers only; multi-hop *across tools* is out of scope.

**Locked into**: the classifier is load-bearing. If it picks wrong, the answer is suboptimal
(though still grounded). We accept that and measure it (route accuracy = 1.000 on the eval set).

**At larger scale / in production**: if questions genuinely needed multi-tool plans, the right
evolution is a planner node that emits a *typed sequence* of routes (still constrained, still
testable) — not an open ReAct loop.

## Interview Defense

> "I split routing from answering. A single tool-calling agent would chain tools for free, but
> then the control flow lives inside the model and I can't test 'does this question pick the
> blast-radius query' on its own. With route-then-execute, routing is one constrained call I
> can score (route accuracy), answering is a separate call I can verify, and cost is bounded to
> two calls. The trade-off is no cross-tool chaining — none of the demo questions need it, and
> the fix would be a typed planner, not an open loop."
