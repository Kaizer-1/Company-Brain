"""Tests for the strict JSON -> ExtractionResult parser."""

import pytest

from app.extraction.parser import ExtractionParseError, parse_extraction

_GOOD = """
{
  "entities": [
    {"type": "Service", "canonical_name": "auth-service", "properties": {},
     "evidence_quote": "auth-service", "confidence": 0.9}
  ],
  "relationships": [
    {"type": "DEPENDS_ON", "source_canonical_name": "payments-api",
     "target_canonical_name": "auth-service",
     "evidence_quote": "payments-api depends on auth-service", "confidence": 0.85}
  ]
}
"""


def test_clean_json_parses() -> None:
    result = parse_extraction(_GOOD)
    assert result.entities[0].canonical_name == "auth-service"
    assert result.relationships[0].source_canonical_name == "payments-api"


def test_fenced_json_is_stripped_and_parses() -> None:
    fenced = "```json\n" + _GOOD.strip() + "\n```"
    result = parse_extraction(fenced)
    assert len(result.entities) == 1


def test_empty_lists_are_valid() -> None:
    result = parse_extraction('{"entities": [], "relationships": []}')
    assert result.entities == []
    assert result.relationships == []


def test_malformed_json_raises_with_raw_and_stage() -> None:
    with pytest.raises(ExtractionParseError) as exc:
        parse_extraction("{not valid json")
    assert exc.value.stage == "json"
    assert "{not valid json" in exc.value.raw


def test_empty_string_raises() -> None:
    with pytest.raises(ExtractionParseError) as exc:
        parse_extraction("   ")
    assert exc.value.stage == "json"


def test_non_object_toplevel_raises() -> None:
    with pytest.raises(ExtractionParseError) as exc:
        parse_extraction("[1, 2, 3]")
    assert exc.value.stage == "schema"


def test_missing_entities_key_raises_clearly() -> None:
    with pytest.raises(ExtractionParseError) as exc:
        parse_extraction('{"relationships": []}')
    assert exc.value.stage == "schema"
    assert "entities" in str(exc.value)


def test_schema_mismatch_raises_schema_stage() -> None:
    # confidence as a string violates strict-mode validation.
    bad = (
        '{"entities": [{"type": "Service", "canonical_name": "x", '
        '"evidence_quote": "x", "confidence": "high"}], "relationships": []}'
    )
    with pytest.raises(ExtractionParseError) as exc:
        parse_extraction(bad)
    assert exc.value.stage == "schema"
