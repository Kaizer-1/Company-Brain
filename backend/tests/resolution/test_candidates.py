"""Candidate-pair generation — the O(n²) all-pairs count and similarity wiring (no model)."""

from __future__ import annotations

import numpy as np

from app.models.enums import NodeType
from app.resolution.candidates import generate_candidate_pairs
from app.resolution.models import ResolvableNode


def _nodes(n: int) -> list[ResolvableNode]:
    return [ResolvableNode(node_type=NodeType.Person, node_id=f"p{i}") for i in range(n)]


def test_pair_count_is_n_choose_2() -> None:
    nodes = _nodes(5)
    vectors = np.eye(5, dtype=np.float32)  # orthogonal unit vectors
    pairs = generate_candidate_pairs(nodes, vectors=vectors)
    assert len(pairs) == 10  # C(5,2)


def test_fewer_than_two_nodes_yields_no_pairs() -> None:
    assert generate_candidate_pairs(_nodes(0)) == []
    assert generate_candidate_pairs(_nodes(1)) == []


def test_similarity_is_attached_from_vectors() -> None:
    nodes = _nodes(3)
    # node0 == node1 (identical), node2 orthogonal to both.
    vectors = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    pairs = {(p.node_a.node_id, p.node_b.node_id): p.similarity for p in generate_candidate_pairs(nodes, vectors=vectors)}
    assert pairs[("p0", "p1")] == 1.0
    assert pairs[("p0", "p2")] == 0.0
    assert pairs[("p1", "p2")] == 0.0
