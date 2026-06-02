"""Resolution eval harness: ground truth from ALIAS_GROUPS + metric correctness (no DB).

The "build the eval correct first" discipline (mirrors Phase 2B): a mock-perfect resolver —
predicted pairs == expected pairs — must score precision/recall/F1 = 1.0, and a false merge
must drop precision. We assert that here before any real resolver output is judged.
"""

from __future__ import annotations

from app.eval.metrics import compute_metrics
from app.eval.resolution_eval import (
    Pair,
    ResolutionEvalResult,
    TierStat,
    build_resolution_ground_truth,
    render_resolution_report,
)
from app.models.enums import NodeType


def test_ground_truth_has_six_groups_one_negative() -> None:
    gt = build_resolution_ground_truth()
    assert len(gt.groups) == 6
    assert len(gt.negatives) == 1
    persons = {g.canonical for g in gt.groups_for(NodeType.Person)}
    services = {g.canonical for g in gt.groups_for(NodeType.Service)}
    assert persons == {"alice-chen", "diego-ramirez", "ben-smith"}
    assert services == {"auth-service", "payments-api", "billing-v2"}


def test_alice_group_node_ids_are_normalised_surface_forms() -> None:
    gt = build_resolution_ground_truth()
    alice = next(g for g in gt.groups if g.canonical == "alice-chen")
    assert alice.node_ids == frozenset({"alice-chen", "alice-chen-northwind-io", "alice", "al"})


def test_total_true_pairs_count() -> None:
    gt = build_resolution_ground_truth()
    total = sum(len(g.true_pairs()) for g in gt.groups)
    # person: 6+6+6, service: 6+6+3
    assert total == 33


def test_perfect_prediction_scores_one() -> None:
    gt = build_resolution_ground_truth()
    expected: set[Pair] = set()
    for g in gt.groups:
        expected |= g.true_pairs()
    metrics = compute_metrics(set(expected), expected)
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.f1 == 1.0


def test_false_merge_drops_precision() -> None:
    gt = build_resolution_ground_truth()
    expected: set[Pair] = set()
    for g in gt.groups:
        expected |= g.true_pairs()
    # Predict everything correct PLUS one forbidden look-alike merge.
    predicted = set(expected) | {next(iter(gt.negatives))}
    metrics = compute_metrics(predicted, expected)
    assert metrics.recall == 1.0
    assert metrics.precision < 1.0


def test_report_renders_zero_false_merges_message() -> None:
    result = ResolutionEvalResult(
        overall=compute_metrics({frozenset({"a", "b"})}, {frozenset({"a", "b"})}),
        by_type={"Person": compute_metrics({frozenset({"a", "b"})}, {frozenset({"a", "b"})})},
        tier_stats=[TierStat(tier=1, merges=1, mean_confidence=0.99)],
        decision_counts={"auto_merge": 1, "llm_merge": 0, "llm_no_merge": 0, "below_threshold": 0},
        correct_examples=[("a", "b")],
        node_count=2,
    )
    report = render_resolution_report(result, generated_at="2026-06-02")
    assert "Headline metrics" in report
    assert "Zero false merges" in report
    assert "Discussion" in report
