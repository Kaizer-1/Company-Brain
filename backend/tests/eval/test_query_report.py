"""Unit tests for the query-eval report renderer + result aggregation (Phase 3B)."""

from __future__ import annotations

import pytest

from app.eval.query_eval import (
    DISCUSSION_MARKER,
    KQOutcome,
    QueryEvalResult,
    render_query_report,
)


def _outcome(name: str, *, passed: bool) -> KQOutcome:
    return KQOutcome(
        name=name,
        question=f"{name} question?",
        passed=passed,
        expected="expected",
        actual="actual",
        provenance_valid=passed,
    )


def test_all_passed_property() -> None:
    r = QueryEvalResult(outcomes=[_outcome("KQ1", passed=True), _outcome("KQ2", passed=True)])
    assert r.all_passed
    r2 = QueryEvalResult(outcomes=[_outcome("KQ1", passed=True), _outcome("KQ2", passed=False)])
    assert not r2.all_passed
    assert not QueryEvalResult().all_passed  # empty is not "all passed"


def test_total_cost_sums_components() -> None:
    r = QueryEvalResult(resolution_cost_usd=0.01, contradiction_cost_usd=0.002)
    assert r.total_cost_usd == pytest.approx(0.012)


def test_render_report_contains_table_and_marker() -> None:
    r = QueryEvalResult(
        outcomes=[_outcome("KQ1", passed=True), _outcome("KQ2", passed=False)],
        event_count=120,
    )
    report = render_query_report(r, generated_at="2026-06-03")
    assert "Killer-Query Integration Eval" in report
    assert "❌ FAILURES" in report
    assert "KQ1" in report and "KQ2" in report
    assert DISCUSSION_MARKER in report
    assert "Failure notes" in report  # KQ2 failed
