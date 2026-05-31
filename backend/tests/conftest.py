"""Shared pytest fixtures for the backend test suite."""

from collections.abc import Generator
from unittest.mock import AsyncMock

import pytest

from app.main import app


@pytest.fixture
def healthy_state() -> Generator[None, None, None]:
    """Inject mocks reporting both Neo4j and Postgres as connected."""
    neo4j_mock = AsyncMock()
    neo4j_mock.verify_connectivity.return_value = True
    postgres_mock = AsyncMock()
    postgres_mock.verify_connectivity.return_value = True
    app.state.neo4j = neo4j_mock
    app.state.postgres = postgres_mock
    yield
    del app.state.neo4j
    del app.state.postgres


@pytest.fixture
def neo4j_down_state() -> Generator[None, None, None]:
    """Inject mocks with Neo4j reporting as disconnected."""
    neo4j_mock = AsyncMock()
    neo4j_mock.verify_connectivity.return_value = False
    postgres_mock = AsyncMock()
    postgres_mock.verify_connectivity.return_value = True
    app.state.neo4j = neo4j_mock
    app.state.postgres = postgres_mock
    yield
    del app.state.neo4j
    del app.state.postgres


@pytest.fixture
def postgres_down_state() -> Generator[None, None, None]:
    """Inject mocks with Postgres reporting as disconnected."""
    neo4j_mock = AsyncMock()
    neo4j_mock.verify_connectivity.return_value = True
    postgres_mock = AsyncMock()
    postgres_mock.verify_connectivity.return_value = False
    app.state.neo4j = neo4j_mock
    app.state.postgres = postgres_mock
    yield
    del app.state.neo4j
    del app.state.postgres
