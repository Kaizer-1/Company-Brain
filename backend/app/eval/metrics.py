"""Precision / recall / F1 over canonical extraction sets.

Deliberately boring set arithmetic. Entities and relationships are reduced to hashable
keys upstream (``matcher.py``), so a "match" is exact set membership in canonical-key
space, and the metrics here never need to know about aliases or types — they operate on
whatever hashable items they are handed. Per-type breakdowns are computed by filtering the
sets by a key function and recomputing.

All formulas guard division by zero: precision/recall/F1 of an empty prediction or empty
gold set is 0.0, not a crash. (Recall of an empty gold set is conventionally 1.0, but in
this harness an empty gold set for a type means that type is absent from ground truth and
is simply not reported, so 0.0 is never surfaced misleadingly.)
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Metrics:
    """Counts and the three derived scores for one comparison."""

    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float

    @property
    def support(self) -> int:
        """Number of gold items (TP + FN) — the denominator of recall."""
        return self.true_positives + self.false_negatives


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def compute_metrics[T: Hashable](extracted: set[T], expected: set[T]) -> Metrics:
    """Compute precision/recall/F1 of ``extracted`` against ``expected``."""
    tp = len(extracted & expected)
    fp = len(extracted - expected)
    fn = len(expected - extracted)
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return Metrics(
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1=f1,
    )


def compute_metrics_by_type[T: Hashable](
    extracted: Iterable[T],
    expected: Iterable[T],
    *,
    key: Callable[[T], str],
) -> dict[str, Metrics]:
    """Per-group metrics, where ``key`` maps each item to its group label (e.g. type).

    Groups are the union of types seen in either set, so a type that the model invented
    but ground truth lacks (all false positives) still appears with precision 0.0.
    """
    extracted_set = set(extracted)
    expected_set = set(expected)
    groups = {key(item) for item in extracted_set} | {key(item) for item in expected_set}
    out: dict[str, Metrics] = {}
    for group in sorted(groups):
        e = {item for item in extracted_set if key(item) == group}
        g = {item for item in expected_set if key(item) == group}
        out[group] = compute_metrics(e, g)
    return out
