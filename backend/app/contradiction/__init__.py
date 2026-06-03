"""Contradiction + Message population pass for KQ2 (Phase 3B).

Creates Message nodes from Slack events and detects CONTRADICTS edges to active decisions.
Resolves graph-schema open question #1. See docs/design/query-engine.md and ADR 0019.
"""

from app.contradiction.detector import detect_contradictions
from app.contradiction.message_ingest import ingest_messages
from app.contradiction.models import ContradictionResult, ContradictionVerdict

__all__ = [
    "ContradictionResult",
    "ContradictionVerdict",
    "detect_contradictions",
    "ingest_messages",
]
