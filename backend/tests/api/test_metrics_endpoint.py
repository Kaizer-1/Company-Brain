"""Integration test for GET /api/metrics (Phase 5B).

The endpoint reads the in-memory ``metrics`` singleton, so the test resets it, records a few
samples, and asserts the JSON snapshot. No DB or network involved.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.metrics import router
from app.observability import metrics


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_metrics_endpoint_zero_state() -> None:
    metrics.reset()
    try:
        resp = _client().get("/api/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ingestion"]["total"] == 0
        assert data["ingestion"]["by_status"] == {}
        assert data["stages"] == {}
        assert data["adjudications"]["resolution_total"] == 0
    finally:
        metrics.reset()


def test_metrics_endpoint_reports_recorded_samples() -> None:
    metrics.reset()
    try:
        metrics.record_stage("extract", "ok", 800.0)
        metrics.record_stage("resolve", "ok", 9000.0)
        metrics.record_resolution(2)
        metrics.record_resolution(1)
        metrics.record_contradiction()
        metrics.record_ingestion("reconciled", 5800.0, 0.0031)

        resp = _client().get("/api/metrics")
        assert resp.status_code == 200
        data = resp.json()

        assert data["ingestion"]["total"] == 1
        assert data["ingestion"]["by_status"] == {"reconciled": 1}
        assert data["ingestion"]["duration_ms"]["p50"] == 5800.0
        assert data["ingestion"]["cost_usd"]["total"] == 0.0031
        assert set(data["stages"].keys()) == {"extract", "resolve"}
        assert data["stages"]["resolve"]["count"] == 1
        assert data["adjudications"]["resolution_total"] == 2
        assert data["adjudications"]["resolution_by_tier"] == {"1": 1, "2": 1}
        assert data["adjudications"]["contradiction_total"] == 1
    finally:
        metrics.reset()
