"""Candidate-pair generation for entity resolution (Phase 3A).

Two responsibilities:

- ``load_nodes`` — read the un-merged nodes of one type out of Neo4j into ``ResolvableNode``s.
  Nodes already tombstoned (``status = "merged"``) are excluded so re-running resolution is
  idempotent (it never re-merges an already-absorbed node).
- ``generate_candidate_pairs`` — the **O(n²) all-pairs within a type** comparison, attaching
  each pair's cosine similarity. At the Phase 2B sample scale this is at most a few hundred
  comparisons. This does not scale to a million nodes and the design says so plainly; the
  documented path is blocking + an ANN index (see docs/design/entity-resolution.md). That is
  named future work, not built here.
"""

from __future__ import annotations

from itertools import combinations
from typing import TYPE_CHECKING

import structlog

from app.resolution.embeddings import cosine_similarity, embed_texts, node_embedding_input
from app.resolution.models import KEY_FIELD, CandidatePair, ResolvableNode

if TYPE_CHECKING:
    import numpy as np
    from neo4j import AsyncDriver

    from app.models.enums import NodeType

log = structlog.get_logger(__name__)


async def load_nodes(driver: AsyncDriver, node_type: NodeType) -> list[ResolvableNode]:
    """Load every non-merged node of ``node_type`` from Neo4j.

    The label comes from the closed ``NodeType`` vocabulary (never user text), so
    interpolating it into the Cypher — which forbids parameterised labels — is safe.
    """
    label = node_type.value
    key_field = KEY_FIELD[node_type]
    query = (
        f"MATCH (n:{label}) "
        "WHERE coalesce(n.status, 'active') <> 'merged' "
        "RETURN properties(n) AS props"
    )
    nodes: list[ResolvableNode] = []
    async with driver.session() as session:
        result = await session.run(query)
        records = [record async for record in result]

    for record in records:
        props = dict(record["props"])
        node_id = props.get(key_field) or props.get("id")
        if not isinstance(node_id, str):
            log.warning("resolvable_node_missing_key", label=label, key_field=key_field)
            continue
        raw_event_ids = props.get("source_event_ids") or []
        source_event_ids = tuple(str(e) for e in raw_event_ids)
        status = props.get("status")
        nodes.append(
            ResolvableNode(
                node_type=node_type,
                node_id=node_id,
                properties=props,
                source_event_ids=source_event_ids,
                status=status if isinstance(status, str) else "active",
            )
        )
    log.info("loaded_nodes", label=label, count=len(nodes))
    return nodes


def generate_candidate_pairs(
    nodes: list[ResolvableNode],
    *,
    vectors: np.ndarray | None = None,
) -> list[CandidatePair]:
    """All within-type pairs, each annotated with cosine similarity.

    If ``vectors`` (a row-per-node embedding matrix aligned with ``nodes``) is not supplied,
    embeddings are computed here. Passing pre-computed vectors lets the orchestrator embed
    once off the event loop (via ``asyncio.to_thread``) and lets tests inject fake vectors.
    """
    if len(nodes) < 2:
        return []
    if vectors is None:
        vectors = embed_texts([node_embedding_input(n) for n in nodes])

    pairs: list[CandidatePair] = []
    for i, j in combinations(range(len(nodes)), 2):
        sim = cosine_similarity(vectors[i], vectors[j])
        pairs.append(CandidatePair(node_a=nodes[i], node_b=nodes[j], similarity=sim))
    return pairs
