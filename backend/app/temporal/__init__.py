"""Temporal enrichment for Decision nodes (Phase 3B).

Populates the schema-reserved ``valid_from``/``valid_to``/``status`` fields and derives
``SUPERSEDES`` edges so KQ2 (active decisions) and KQ4 (last-quarter changes) have temporal
data to filter on. See docs/design/query-engine.md and ADR 0016.
"""

from app.temporal.enricher import enrich_temporal
from app.temporal.models import TemporalEnrichmentResult

__all__ = ["TemporalEnrichmentResult", "enrich_temporal"]
