"""Determinism is the contract: same seed => byte-identical events (ADR 0011).

If this breaks, no downstream extraction/resolution eval is reproducible.
"""

from app.schemas.postgres import EventCreate
from app.synthetic.generator import SyntheticDataGenerator


def _dump(events: list[EventCreate]) -> list[dict[str, object]]:
    return [e.model_dump() for e in events]


def test_two_fresh_instances_same_seed_are_identical() -> None:
    a = SyntheticDataGenerator(seed=42).generate()
    b = SyntheticDataGenerator(seed=42).generate()
    assert _dump(a) == _dump(b)


def test_same_instance_called_twice_is_identical() -> None:
    gen = SyntheticDataGenerator(seed=42)
    first = gen.generate()
    second = gen.generate()
    assert _dump(first) == _dump(second)


def test_content_is_byte_identical_including_timestamps() -> None:
    a = SyntheticDataGenerator(seed=42).generate()
    b = SyntheticDataGenerator(seed=42).generate()
    assert [e.content for e in a] == [e.content for e in b]
    assert [e.created_at for e in a] == [e.created_at for e in b]
    assert [e.source_external_id for e in a] == [e.source_external_id for e in b]


def test_different_seed_changes_output() -> None:
    a = SyntheticDataGenerator(seed=42).generate()
    b = SyntheticDataGenerator(seed=7).generate()
    # Same structure (deterministic planted cases) but the random choices differ,
    # so the rendered content should not be identical.
    assert [e.content for e in a] != [e.content for e in b]
