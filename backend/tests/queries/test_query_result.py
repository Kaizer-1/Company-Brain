"""Unit tests for the QueryResult[T] / QueryProvenance envelope (Phase 3B; ADR 0018)."""

from __future__ import annotations

from pydantic import BaseModel

from app.queries.result_types import QueryProvenance, QueryResult


class _Answer(BaseModel):
    owner: str


def test_provenance_add_dedupes_and_keys() -> None:
    prov = QueryProvenance()
    prov.add("edge:DEPRECATES:D-0006->legacy-auth", ["e1", "e2"])
    prov.add("edge:DEPRECATES:D-0006->legacy-auth", ["e2", "e3"])  # e2 duplicate
    prov.add("node:Decision:D-0006", ["e4"])
    assert prov.by_element["edge:DEPRECATES:D-0006->legacy-auth"] == ["e1", "e2", "e3"]
    assert prov.all_event_ids == ["e1", "e2", "e3", "e4"]


def test_provenance_skips_empty_ids() -> None:
    prov = QueryProvenance()
    prov.add("k", ["", "e1", ""])
    assert prov.by_element["k"] == ["e1"]


def test_query_result_is_generic_and_serialises() -> None:
    prov = QueryProvenance()
    prov.add("node:Person:diego-ramirez", ["evt-1"])
    result: QueryResult[_Answer] = QueryResult(value=_Answer(owner="diego-ramirez"), provenance=prov)
    dumped = result.model_dump()
    assert dumped["value"] == {"owner": "diego-ramirez"}
    assert dumped["provenance"]["by_element"] == {"node:Person:diego-ramirez": ["evt-1"]}


def test_query_result_default_provenance_is_empty() -> None:
    result: QueryResult[_Answer] = QueryResult(value=_Answer(owner="x"))
    assert result.provenance.all_event_ids == []
