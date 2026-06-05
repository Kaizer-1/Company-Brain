"""Tool nodes: each KQ node calls the right query with the right params; search applies
filters; missing params fall back to search; unknown/empty terminals behave."""

from __future__ import annotations

from typing import Any

import pytest

from app.agent import tools
from app.agent.state import AgentState
from app.queries.kq1_multihop_ownership import ChainOwnerAnswer
from app.queries.kq2_temporal_contradiction import Contradiction
from app.queries.kq3_blast_radius import BlastRadius
from app.queries.kq4_change_tracking import ChangeTimeline
from app.queries.result_types import QueryProvenance, QueryResult

from .conftest import make_deps


def _result(value: Any, event_ids: list[str]) -> QueryResult[Any]:
    prov = QueryProvenance()
    if event_ids:
        prov.add("node:test", event_ids)
    return QueryResult(value=value, provenance=prov)


# --------------------------------------------------------------------------- KQ nodes


async def test_kq1_calls_find_chain_owner_with_decision_id(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake(driver, *, decision_id, as_of=None):  # type: ignore[no-untyped-def]
        captured["decision_id"] = decision_id
        return _result(ChainOwnerAnswer(decision_id=decision_id), ["e1", "e2"])

    monkeypatch.setattr(tools, "find_chain_owner", fake)
    deps = make_deps(client=None, neo4j_driver=object())
    state: AgentState = {"question": "q", "tool_input": {"decision_id": "D-0006"}}

    out = await tools.kq1_owner(state, deps=deps)

    assert captured["decision_id"] == "D-0006"
    assert out["available_event_ids"] == ["e1", "e2"]
    assert out["tool_output"]["value"]["decision_id"] == "D-0006"
    assert "kq1_owner" in out["timings_ms"]


async def test_kq3_calls_blast_radius_with_service_and_depth(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake(driver, *, service_name, max_depth=5, as_of=None):  # type: ignore[no-untyped-def]
        captured.update(service_name=service_name, max_depth=max_depth)
        return _result(BlastRadius(seed_service=service_name), ["e9"])

    monkeypatch.setattr(tools, "compute_blast_radius", fake)
    deps = make_deps(client=None, neo4j_driver=object())
    state: AgentState = {"question": "q", "tool_input": {"service": "payments-api", "max_depth": 3}}

    out = await tools.kq3_blast(state, deps=deps)

    assert captured == {"service_name": "payments-api", "max_depth": 3}
    assert out["available_event_ids"] == ["e9"]


async def test_kq2_defaults_window_to_30(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake(driver, *, window, as_of=None):  # type: ignore[no-untyped-def]
        captured["days"] = window.days
        return _result([Contradiction(decision_id="D-1")], ["e1"])

    monkeypatch.setattr(tools, "find_contradictions", fake)
    deps = make_deps(client=None, neo4j_driver=object())
    out = await tools.kq2_contra({"question": "q", "tool_input": {}}, deps=deps)

    assert captured["days"] == 30
    assert out["available_event_ids"] == ["e1"]


async def test_kq4_uses_target_and_window(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake(driver, *, target_name, window, as_of=None):  # type: ignore[no-untyped-def]
        captured.update(target=target_name, days=window.days)
        return _result(ChangeTimeline(target=target_name), ["e1"])

    monkeypatch.setattr(tools, "track_changes", fake)
    deps = make_deps(client=None, neo4j_driver=object())
    state: AgentState = {"question": "q", "tool_input": {"target": "auth-service", "window_days": 45}}
    out = await tools.kq4_change(state, deps=deps)

    assert captured == {"target": "auth-service", "days": 45}


# --------------------------------------------------------------------------- fallback


async def test_kq1_missing_decision_id_falls_back_to_search(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"search": False}

    async def fake_search(state, *, deps):  # type: ignore[no-untyped-def]
        called["search"] = True
        return {"tool_output": {}, "available_event_ids": ["s1"], "timings_ms": {}}

    monkeypatch.setattr(tools, "general_search", fake_search)
    deps = make_deps(client=None)
    out = await tools.kq1_owner({"question": "q", "tool_input": {}, "route_reasoning": "r"}, deps=deps)

    assert called["search"] is True
    assert "fell back to search" in out["route_reasoning"]


# --------------------------------------------------------------------------- search node


async def test_general_search_builds_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_hybrid(query, *, k, filters, session, neo4j_driver):  # type: ignore[no-untyped-def]
        captured.update(query=query, k=k, filters=filters)
        from app.search.schemas import SearchResult

        return SearchResult(
            query=query, hits=[], total_candidates=0,
            query_embedding_ms=0.0, vector_search_ms=0.0, rerank_ms=0.0, total_ms=0.0,
        )

    class _CtxSession:
        async def __aenter__(self): return object()
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(tools, "hybrid_search", fake_hybrid)
    deps = make_deps(client=None, neo4j_driver=object(), session_factory=lambda: _CtxSession())
    state: AgentState = {"question": "what about auth", "tool_input": {"source_kind": ["doc"]}}

    out = await tools.general_search(state, deps=deps)

    assert captured["k"] == deps.config.search_k
    assert captured["filters"].source_kind == ["doc"]
    assert out["available_event_ids"] == []


# --------------------------------------------------------------------------- terminals


async def test_unknown_terminal() -> None:
    deps = make_deps(client=None)
    out = await tools.unknown({"question": "weather?"}, deps=deps)
    assert out["citations"] == []
    assert out["verified"] is True
    assert out["tool_output"] is None
    assert "knowledge graph" in out["answer"].lower()


async def test_empty_answer_terminal() -> None:
    deps = make_deps(client=None)
    out = await tools.empty_answer({"question": "q", "route": "kq2"}, deps=deps)
    assert out["citations"] == []
    assert out["verified"] is True
    assert "no matching records" in out["answer"]
