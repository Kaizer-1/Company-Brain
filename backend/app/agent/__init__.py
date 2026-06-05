"""The agent layer (Phase 4A).

A LangGraph state machine that turns a natural-language question into a grounded answer:
it classifies the question to one of the four killer queries or general semantic search,
executes the matching typed tool, synthesises an answer that cites Postgres event UUIDs,
and verifies every citation against the tool's own provenance before returning.

Read-only by design. The agent calls Python functions (the four KQs + ``hybrid_search``),
never LLM-generated Cypher. See docs/design/agent-architecture.md and ADRs 0023–0025.

``run_agent`` is the public entry point (see runner.py); it is imported lazily by callers
rather than re-exported here to keep ``import app.agent`` side-effect-free.
"""
