"""Shape contract for the generated corpus: counts, hashes, timestamps, IDs."""

import hashlib
from datetime import timedelta

from app.models.enums import SourceType
from app.schemas.postgres import EventCreate
from app.synthetic.company import REFERENCE_NOW


def _by_type(corpus: list[EventCreate], st: SourceType) -> list[EventCreate]:
    return [e for e in corpus if e.source_type == st]


def test_message_count_in_bounds(corpus: list[EventCreate]) -> None:
    messages = _by_type(corpus, SourceType.slack_message)
    assert 80 <= len(messages) <= 150


def test_doc_count_in_bounds(corpus: list[EventCreate]) -> None:
    docs = _by_type(corpus, SourceType.doc)
    assert 20 <= len(docs) <= 40


def test_every_event_is_event_create(corpus: list[EventCreate]) -> None:
    for e in corpus:
        assert isinstance(e, EventCreate)
        assert e.source_type in (SourceType.doc, SourceType.slack_message)
        assert e.content.strip()


def test_content_hash_matches_sha256_of_content(corpus: list[EventCreate]) -> None:
    for e in corpus:
        assert e.content_hash == hashlib.sha256(e.content.encode("utf-8")).hexdigest()


def test_content_hash_is_unique_per_content(corpus: list[EventCreate]) -> None:
    # Distinct content => distinct hash, and the generator never repeats content.
    contents = [e.content for e in corpus]
    hashes = [e.content_hash for e in corpus]
    assert len(set(contents)) == len(contents)
    assert len(set(hashes)) == len(hashes)


def test_source_external_id_unique_within_type(corpus: list[EventCreate]) -> None:
    for st in (SourceType.doc, SourceType.slack_message):
        ids = [e.source_external_id for e in _by_type(corpus, st)]
        assert len(set(ids)) == len(ids)


def test_timestamps_are_tz_aware_and_within_window(corpus: list[EventCreate]) -> None:
    oldest = REFERENCE_NOW - timedelta(days=366)
    # Window ends a comfortable buffer before "now" so the freshest events are still
    # clearly within "last month" for KQ2 without being suspiciously recent.
    newest = REFERENCE_NOW - timedelta(days=15)
    for e in corpus:
        assert e.created_at.tzinfo is not None
        assert oldest <= e.created_at <= newest


def test_recent_tail_exists_for_kq2(corpus: list[EventCreate]) -> None:
    # At least one event must fall inside the last ~month for the KQ2 contradiction.
    cutoff = REFERENCE_NOW - timedelta(days=30)
    assert any(e.created_at >= cutoff for e in corpus)


def test_metadata_is_json_scalar_friendly(corpus: list[EventCreate]) -> None:
    for e in corpus:
        for value in e.source_metadata.values():
            assert isinstance(value, (str, int, float, bool))
