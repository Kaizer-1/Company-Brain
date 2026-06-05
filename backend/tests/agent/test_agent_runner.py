"""End-to-end runner: the full graph executes with a mocked LLM, state propagates, the
verification retry loop triggers, and citations are resolved into the AskResponse."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.agent import runner, tools
from app.agent.runner import run_agent

from .conftest import FakeClient


def _route(route: str, tool_input: dict | None = None) -> str:
    return json.dumps({"route": route, "reasoning": "x" * 12, "tool_input": tool_input or {}})


def _answer(answer: str, citations: list[str]) -> str:
    return json.dumps({"answer": answer, "citations": citations, "confidence": "high"})


class _FakeSessionCtx:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *a: object) -> bool:
        return False


def _session_factory() -> _FakeSessionCtx:
    return _FakeSessionCtx()


def _patch_citation_resolution(monkeypatch: pytest.MonkeyPatch, known: dict[str, str]) -> None:
    """Patch EventRepository so cited UUIDs resolve to fake events with given content."""

    class _FakeRepo:
        def __init__(self, _session: object) -> None: ...

        async def get_by_id(self, event_id: uuid.UUID) -> Any:
            content = known.get(str(event_id))
            if content is None:
                return None
            return SimpleNamespace(
                id=event_id,
                source_type=SimpleNamespace(value="doc"),
                source_external_id="doc-1",
                content=content,
            )

    monkeypatch.setattr(runner, "EventRepository", _FakeRepo)


async def test_unknown_path_end_to_end() -> None:
    client = FakeClient(content=_route("unknown"))
    resp = await run_agent(
        "what's the weather?",
        neo4j_driver=object(),
        session_factory=_session_factory,  # type: ignore[arg-type]
        debug=True,
        client=client,
    )
    assert resp.route == "unknown"
    assert resp.citations == []
    assert "knowledge graph" in resp.answer.lower()
    assert resp.debug is not None and resp.debug.verified is True
    assert "total" in resp.timings_ms


async def test_kq1_path_resolves_citations(monkeypatch: pytest.MonkeyPatch) -> None:
    eid = str(uuid.uuid4())

    async def fake_chain(driver, *, decision_id, as_of=None):  # type: ignore[no-untyped-def]
        from app.queries.kq1_multihop_ownership import ChainOwnerAnswer
        from app.queries.result_types import QueryProvenance, QueryResult

        prov = QueryProvenance()
        prov.add("node:Decision", [eid])
        return QueryResult(value=ChainOwnerAnswer(decision_id=decision_id), provenance=prov)

    monkeypatch.setattr(tools, "find_chain_owner", fake_chain)
    _patch_citation_resolution(monkeypatch, {eid: "Payments Team owns payments-api."})

    client = FakeClient(content=[_route("kq1", {"decision_id": "D-0006"}), _answer(f"Owned [evt:{eid}].", [eid])])
    resp = await run_agent(
        "who owns the deprecated service?",
        neo4j_driver=object(),
        session_factory=_session_factory,  # type: ignore[arg-type]
        client=client,
    )

    assert resp.route == "kq1"
    assert len(resp.citations) == 1
    assert resp.citations[0].event_id == eid
    assert resp.citations[0].snippet.startswith("Payments Team")
    assert resp.error is None


async def test_verification_retry_loop_then_success(monkeypatch: pytest.MonkeyPatch) -> None:
    eid = str(uuid.uuid4())

    async def fake_search(query, *, k, filters, session, neo4j_driver):  # type: ignore[no-untyped-def]
        from app.search.schemas import SearchHit, SearchResult

        hit = SearchHit(
            event_id=uuid.UUID(eid), snippet="snip", source_kind="doc", source_ref="d1",
            occurred_at=__import__("datetime").datetime.now(),
            similarity_score=0.9, final_score=0.9, related_entity_ids=[],
        )
        return SearchResult(
            query=query, hits=[hit], total_candidates=1,
            query_embedding_ms=0.0, vector_search_ms=0.0, rerank_ms=0.0, total_ms=0.0,
        )

    monkeypatch.setattr(tools, "hybrid_search", fake_search)
    _patch_citation_resolution(monkeypatch, {eid: "Relevant event text."})

    # Router -> search; first synthesis fabricates a citation (fails verify), retry succeeds.
    client = FakeClient(
        content=[
            _route("search"),
            _answer("Bad cite [evt:fabricated-id].", ["fabricated-id"]),
            _answer(f"Good answer [evt:{eid}].", [eid]),
        ]
    )
    resp = await run_agent(
        "tell me about the migration",
        neo4j_driver=object(),
        session_factory=_session_factory,  # type: ignore[arg-type]
        debug=True,
        client=client,
    )

    assert resp.route == "search"
    assert resp.error is None
    assert resp.debug is not None and resp.debug.retry_count == 1
    assert resp.citations[0].event_id == eid


async def test_empty_results_skip_synthesis(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search(query, *, k, filters, session, neo4j_driver):  # type: ignore[no-untyped-def]
        from app.search.schemas import SearchResult

        return SearchResult(
            query=query, hits=[], total_candidates=0,
            query_embedding_ms=0.0, vector_search_ms=0.0, rerank_ms=0.0, total_ms=0.0,
        )

    monkeypatch.setattr(tools, "hybrid_search", fake_search)
    client = FakeClient(content=_route("search"))  # only the router call should happen
    resp = await run_agent(
        "something with no hits",
        neo4j_driver=object(),
        session_factory=_session_factory,  # type: ignore[arg-type]
        client=client,
    )

    assert resp.citations == []
    assert "no matching records" in resp.answer
    assert len(client.calls) == 1  # synthesis never invoked
