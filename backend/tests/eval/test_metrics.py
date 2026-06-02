"""Tests for precision/recall/F1 computation."""

import pytest

from app.eval.metrics import compute_metrics, compute_metrics_by_type


def test_perfect_match() -> None:
    m = compute_metrics({"a", "b", "c"}, {"a", "b", "c"})
    assert (m.precision, m.recall, m.f1) == (1.0, 1.0, 1.0)
    assert (m.true_positives, m.false_positives, m.false_negatives) == (3, 0, 0)


def test_known_precision_recall() -> None:
    # extracted 4, expected 5, overlap 3 -> P=3/4, R=3/5
    m = compute_metrics({"a", "b", "c", "x"}, {"a", "b", "c", "d", "e"})
    assert m.true_positives == 3
    assert m.false_positives == 1
    assert m.false_negatives == 2
    assert m.precision == pytest.approx(0.75)
    assert m.recall == pytest.approx(0.6)
    assert m.f1 == pytest.approx(2 * 0.75 * 0.6 / (0.75 + 0.6))


def test_empty_extraction_is_zero_not_crash() -> None:
    m = compute_metrics(set(), {"a", "b"})
    assert (m.precision, m.recall, m.f1) == (0.0, 0.0, 0.0)


def test_empty_expected_is_zero_not_crash() -> None:
    m = compute_metrics({"a"}, set())
    assert (m.precision, m.recall, m.f1) == (0.0, 0.0, 0.0)


def test_both_empty() -> None:
    m = compute_metrics(set(), set())
    assert m.f1 == 0.0
    assert m.support == 0


def test_by_type_groups_and_includes_fp_only_groups() -> None:
    extracted = {("Service", "a"), ("System", "ghost")}
    expected = {("Service", "a"), ("Person", "p")}
    by_type = compute_metrics_by_type(extracted, expected, key=lambda x: x[0])
    assert set(by_type) == {"Service", "System", "Person"}
    assert by_type["Service"].f1 == 1.0
    assert by_type["System"].precision == 0.0  # all FP
    assert by_type["Person"].recall == 0.0  # all FN
