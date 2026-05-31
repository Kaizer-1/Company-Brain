"""Tests for RequestIDMiddleware."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_request_id_header_present_and_unique(healthy_state: None) -> None:
    """Every response carries a unique X-Request-Id header."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.get("/health")
        r2 = await client.get("/health")

    assert "x-request-id" in r1.headers
    assert "x-request-id" in r2.headers
    assert r1.headers["x-request-id"] != r2.headers["x-request-id"]
