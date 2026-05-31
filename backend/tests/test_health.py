"""Tests for the /health endpoint.

Fixtures live in conftest.py. These tests cover the fully-healthy case
and both degraded cases (Neo4j down, Postgres down).
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_both_connected(healthy_state: None) -> None:
    """Returns status=ok when both databases respond."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["neo4j"] == "connected"
    assert body["postgres"] == "connected"


@pytest.mark.asyncio
async def test_health_neo4j_down(neo4j_down_state: None) -> None:
    """Returns status=degraded when Neo4j is unreachable."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["neo4j"] == "disconnected"
    assert body["postgres"] == "connected"


@pytest.mark.asyncio
async def test_health_postgres_down(postgres_down_state: None) -> None:
    """Returns status=degraded when Postgres is unreachable."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["neo4j"] == "connected"
    assert body["postgres"] == "disconnected"
