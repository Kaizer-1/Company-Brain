"""Unit tests for the in-memory metrics registry (Phase 5B).

Pure Python — no DB, no network. Asserts that counters increment, histograms accumulate, the
percentile reduction matches the hand-computed (numpy-default) values, and the snapshot has the
shape the ``/api/metrics`` endpoint returns.
"""

from __future__ import annotations

import pytest

from app.observability.metrics import Metrics, _percentile


def test_percentile_linear_interpolation() -> None:
    """Matches numpy.percentile's default (linear) method on a known sample."""
    values = [1.0, 2.0, 3.0, 4.0]
    assert _percentile(values, 50) == pytest.approx(2.5)
    assert _percentile(values, 95) == pytest.approx(3.85)
    # Edge cases
    assert _percentile([], 50) == 0.0
    assert _percentile([7.0], 95) == 7.0
    assert _percentile([10.0, 20.0], 0) == 10.0
    assert _percentile([10.0, 20.0], 100) == 20.0


def test_record_ingestion_increments_counters() -> None:
    m = Metrics()
    m.record_ingestion("reconciled", 5000.0, 0.003)
    m.record_ingestion("reconciled", 7000.0, 0.004)
    m.record_ingestion("partial", 1000.0, 0.0)

    assert m.ingestion_total == 3
    assert m.ingestion_by_status == {"reconciled": 2, "partial": 1}
    assert m.ingestion_duration_ms == [5000.0, 7000.0, 1000.0]
    assert m.ingestion_cost_usd == [0.003, 0.004, 0.0]


def test_record_stage_accumulates_per_stage_histograms() -> None:
    m = Metrics()
    m.record_stage("extract", "ok", 800.0)
    m.record_stage("extract", "ok", 1200.0)
    m.record_stage("resolve", "ok", 9000.0)
    m.record_stage("resolve", "skipped", 0.0)

    assert m.stage_duration_ms["extract"] == [800.0, 1200.0]
    assert m.stage_duration_ms["resolve"] == [9000.0, 0.0]


def test_record_resolution_and_contradiction_counters() -> None:
    m = Metrics()
    for tier in (1, 2, 2, 2, 3):
        m.record_resolution(tier)
    m.record_contradiction()
    m.record_contradiction()

    assert m.resolution_adjudications_total == 5
    assert m.resolution_adjudications_by_tier == {"1": 1, "2": 3, "3": 1}
    assert m.contradiction_adjudications_total == 2


def test_snapshot_shape_and_values() -> None:
    m = Metrics()
    for status, dur, cost in [
        ("reconciled", 5000.0, 0.003),
        ("reconciled", 7000.0, 0.005),
        ("partial", 1000.0, 0.001),
    ]:
        m.record_ingestion(status, dur, cost)
    m.record_stage("resolve", "ok", 9000.0)
    m.record_stage("resolve", "skipped", 0.0)
    m.record_resolution(2)

    snap = m.snapshot()

    assert snap.ingestion.total == 3
    assert snap.ingestion.by_status == {"reconciled": 2, "partial": 1}
    # p50 of [5000, 7000, 1000] sorted [1000,5000,7000] -> middle = 5000
    assert snap.ingestion.duration_ms.p50 == 5000.0
    assert snap.ingestion.duration_ms.max == 7000.0
    # cost mean of [0.003,0.005,0.001] = 0.003
    assert snap.ingestion.cost_usd.mean == 0.003
    assert snap.ingestion.cost_usd.total == 0.009
    # stage count = number of times the stage ran (incl. skipped)
    assert snap.stages["resolve"].count == 2
    assert snap.adjudications.resolution_total == 1
    assert snap.adjudications.resolution_by_tier == {"2": 1}


def test_reset_clears_all_state() -> None:
    m = Metrics()
    m.record_ingestion("reconciled", 5000.0, 0.003)
    m.record_stage("extract", "ok", 800.0)
    m.record_resolution(2)
    m.record_contradiction()

    m.reset()

    assert m.ingestion_total == 0
    assert m.ingestion_by_status == {}
    assert m.stage_duration_ms == {}
    assert m.ingestion_duration_ms == []
    assert m.ingestion_cost_usd == []
    assert m.resolution_adjudications_total == 0
    assert m.resolution_adjudications_by_tier == {}
    assert m.contradiction_adjudications_total == 0
    # Snapshot after reset is the zero-state shape.
    snap = m.snapshot()
    assert snap.ingestion.total == 0
    assert snap.stages == {}
