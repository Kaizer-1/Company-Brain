"""Fixtures for synthetic-generator tests."""

import pytest

from app.schemas.postgres import EventCreate
from app.synthetic.generator import SyntheticDataGenerator


@pytest.fixture(scope="module")
def corpus() -> list[EventCreate]:
    """The canonical seed=42 corpus, generated once per test module."""
    return SyntheticDataGenerator(seed=42).generate()


@pytest.fixture(scope="module")
def blob(corpus: list[EventCreate]) -> str:
    """All event content joined — convenient for substring-presence assertions."""
    return "\n".join(e.content for e in corpus)
