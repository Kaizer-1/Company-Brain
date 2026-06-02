"""Extraction eval harness (Phase 2B).

Derives ground truth from the synthetic company (``app.synthetic``) — the single source
of truth, no separate hand-labelled file (ADR 0013) — runs an extraction model over the
corpus, and scores precision/recall/F1 per entity and relationship type with a named
failure-mode taxonomy.

The harness *runs* the extractor (``app.extraction``) and *judges* its output; it never
reaches inside it. That separation is what lets a model be swapped without touching the
eval. See ``docs/design/extraction-pipeline.md``.
"""
