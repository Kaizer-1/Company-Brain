"""Multi-source Decision consolidation (Phase 3B; ADR 0017).

Runs after entity resolution. Decisions are content-bearing, not identity-bearing: a doc and the
Slack thread that originated it can produce two Decision nodes for one real decision when a
source paraphrases without naming the id. This pass merges such pairs using the **same
``MERGE_INTO`` + ``status='merged'`` + provenance-union mechanism** as 3A, so the audit trail and
the resolved view are identical across entities and decisions.

Detection differs from entity resolution: there is no stable key, so the signal is the
``title + body`` content embedding (cosine ≥ ``CONTENT_SIM_THRESHOLD``, higher than the 0.75
entity floor) gated by temporal proximity. A strong guard protects KQ4: two decisions that each
carry a *distinct formal* ``D-####`` id are authoritatively different and are never consolidated,
no matter how similar their text — only a paraphrase (one side lacking a formal id) can merge.
"""

from __future__ import annotations

import asyncio
import re
from datetime import timedelta
from itertools import combinations
from typing import TYPE_CHECKING

import structlog

from app.db.repositories.resolution import MergeDecisionRepository
from app.models.enums import MergeDecisionType, NodeType
from app.resolution.candidates import load_nodes
from app.resolution.embeddings import cosine_similarity, embed_texts
from app.resolution.merger import Merger, pick_winner
from app.resolution.models import CandidatePair, ResolvableNode

if TYPE_CHECKING:
    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# Higher than the 0.75 entity floor: the signal is content, not identity, and a false content
# merge silently corrupts KQ2/KQ4, so we demand stronger agreement (ADR 0017).
CONTENT_SIM_THRESHOLD = 0.85
# Two real decisions about the same subject can read alike; require they also be close in time.
PROXIMITY = timedelta(days=30)
_FORMAL_ID_RE = re.compile(r"^D-\d{3,4}$")


def _is_formal_id(node_id: str) -> bool:
    return bool(_FORMAL_ID_RE.match(node_id))


def decision_embedding_input(node: ResolvableNode) -> str:
    """The text we embed for a decision: title + body, falling back to the node id."""
    parts = [node.prop_str("title") or "", node.prop_str("body") or ""]
    text = " ".join(p for p in parts if p).strip()
    return text or node.node_id


def _created_at_str(node: ResolvableNode) -> str | None:
    """The node's created_at as a string, if present (Neo4j DateTime stringifies to ISO)."""
    value = node.properties.get("created_at")
    return str(value) if value is not None else None


def _within_proximity(a: ResolvableNode, b: ResolvableNode) -> bool:
    """True if the two decisions' created_at timestamps are within ``PROXIMITY`` (or unknown).

    If either timestamp is missing we do not block on proximity — content similarity plus the
    distinct-formal-id guard still apply.
    """
    from datetime import datetime

    sa, sb = _created_at_str(a), _created_at_str(b)
    if sa is None or sb is None:
        return True
    try:
        ta = datetime.fromisoformat(sa)
        tb = datetime.fromisoformat(sb)
    except ValueError:
        return True
    return abs(ta - tb) <= PROXIMITY


def should_consolidate(a: ResolvableNode, b: ResolvableNode, similarity: float) -> bool:
    """Decide whether two Decision nodes are the same real decision."""
    # Authority guard: two distinct formally-identified decisions are never the same.
    if _is_formal_id(a.node_id) and _is_formal_id(b.node_id) and a.node_id != b.node_id:
        return False
    return similarity >= CONTENT_SIM_THRESHOLD and _within_proximity(a, b)


async def consolidate_decisions(
    driver: AsyncDriver,
    session: AsyncSession,
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """Consolidate duplicate Decision nodes; return counts.

    Returns ``{"decisions", "candidate_pairs", "merges"}``. Idempotent: already-merged
    (``status='merged'``) decisions are excluded from ``load_nodes``, so re-running never
    re-merges an absorbed node.
    """
    nodes = await load_nodes(driver, NodeType.Decision)
    repo = MergeDecisionRepository(session)
    merger = Merger(driver, repo, dry_run=dry_run)

    if len(nodes) < 2:
        return {"decisions": len(nodes), "candidate_pairs": 0, "merges": 0}

    inputs = [decision_embedding_input(n) for n in nodes]
    vectors = await asyncio.to_thread(embed_texts, inputs)

    candidate_pairs = 0
    merges = 0
    # Track which nodes were absorbed so we do not re-evaluate a tombstoned loser in-run.
    absorbed: set[str] = set()
    for i, j in combinations(range(len(nodes)), 2):
        a, b = nodes[i], nodes[j]
        if a.node_id in absorbed or b.node_id in absorbed:
            continue
        sim = cosine_similarity(vectors[i], vectors[j])
        candidate_pairs += 1
        if not should_consolidate(a, b, sim):
            continue
        pair = CandidatePair(node_a=a, node_b=b, similarity=sim)
        await merger.apply_decision(
            pair,
            decision=MergeDecisionType.content_merge,
            tier=2,
            confidence=sim,
            rules_matched=["content_similarity"],
        )
        merges += 1
        # The loser the Merger tombstoned must not be re-evaluated against later candidates.
        _, loser = pick_winner(a, b)
        absorbed.add(loser.node_id)

    log.info(
        "decision_consolidation_complete",
        decisions=len(nodes),
        candidate_pairs=candidate_pairs,
        merges=merges,
        dry_run=dry_run,
    )
    return {"decisions": len(nodes), "candidate_pairs": candidate_pairs, "merges": merges}
