"""LLM extraction pipeline (Phase 2B).

Reads raw ``events`` from Postgres, prompts an LLM (via OpenRouter) for structured
entities and relationships, validates the JSON against Pydantic models, writes the
result to Neo4j with provenance, and audits every attempt in ``extraction_runs``.

The package is deliberately ignorant of the eval harness (``app.eval``): the
extractor produces output; the eval judges it. This separation is what lets a model
be swapped without touching the eval and vice versa. See
``docs/design/extraction-pipeline.md`` and ADR 0012.
"""
