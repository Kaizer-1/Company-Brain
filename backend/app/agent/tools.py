"""The agent's tool nodes (Phase 4A).

Six terminal-of-routing nodes: one thin glue node per killer query, one for general
semantic search, and one ``unknown`` terminal. Each KQ node takes the classifier's
``tool_input``, validates the parameters it needs, calls the existing typed function in
``app.queries`` (no new query logic — ADR 0023), and writes the result plus its flat set
of citable event UUIDs into the state.

Behaviour on missing/invalid parameters: a KQ node falls back to ``general_search`` rather
than to ``unknown``. A question that routed to a KQ is, by construction, about the company
graph; refusing it would violate the "never refuse a company question" rule (CLAUDE.md).
This is a deliberate deviation from Decision 3's "fall through to unknown" — documented in
HANDOFF.md. The ``unknown`` terminal is reserved for genuinely out-of-scope questions the
router itself flagged.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import structlog

from app.queries import (
    compute_blast_radius,
    find_chain_owner,
    find_contradictions,
    track_changes,
)
from app.search.retriever import hybrid_search
from app.search.schemas import SearchFilters

if TYPE_CHECKING:
    from app.agent.deps import AgentDeps
    from app.agent.state import AgentState
    from app.queries.result_types import QueryResult

log = structlog.get_logger(__name__)

# The polite refusal returned by the unknown terminal. Stated as a capability boundary,
# not an apology — the agent answers questions about the company graph and nothing else.
_UNKNOWN_ANSWER = (
    "I can only answer questions about Northwind Payments' knowledge graph — its services, "
    "systems, decisions, teams, and the discussions around them. I can't answer that one "
    "with the data I have."
)


def _timed(state: AgentState, name: str, t0: float) -> dict[str, float]:
    """Merge this node's elapsed time into the running timings map."""
    elapsed = (time.monotonic() - t0) * 1000
    return {**state.get("timings_ms", {}), name: round(elapsed, 1)}


def _query_result_to_state(
    state: AgentState, result: QueryResult[Any], *, node_name: str, t0: float
) -> dict[str, object]:
    """Serialise a KQ ``QueryResult`` into the tool-output state slice."""
    return {
        "tool_output": result.model_dump(mode="json"),
        "available_event_ids": list(result.provenance.all_event_ids),
        "timings_ms": _timed(state, node_name, t0),
    }


def _str_param(tool_input: dict[str, Any], key: str) -> str | None:
    value = tool_input.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _int_param(tool_input: dict[str, Any], key: str, default: int) -> int:
    value = tool_input.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else default


# ---------------------------------------------------------------------------
# KQ tool nodes
# ---------------------------------------------------------------------------


async def kq1_owner(state: AgentState, *, deps: AgentDeps) -> dict[str, object]:
    """KQ1 — multi-hop ownership. Requires a decision id; falls back to search if absent."""
    t0 = time.monotonic()
    decision_id = _str_param(state.get("tool_input", {}), "decision_id")
    if decision_id is None:
        return await _fallback_search(state, deps, missing="decision_id (KQ1)")
    result = await find_chain_owner(deps.neo4j_driver, decision_id=decision_id)
    log.info("tool_kq1_done", decision_id=decision_id, chains=len(result.value.chains))
    return _query_result_to_state(state, result, node_name="kq1_owner", t0=t0)


async def kq2_contra(state: AgentState, *, deps: AgentDeps) -> dict[str, object]:
    """KQ2 — temporal contradiction. Window defaults to 30 days; never needs an entity."""
    t0 = time.monotonic()
    window_days = _int_param(state.get("tool_input", {}), "window_days", 30)
    result = await find_contradictions(deps.neo4j_driver, window=timedelta(days=window_days))
    log.info("tool_kq2_done", window_days=window_days, found=len(result.value))
    return _query_result_to_state(state, result, node_name="kq2_contra", t0=t0)


async def kq3_blast(state: AgentState, *, deps: AgentDeps) -> dict[str, object]:
    """KQ3 — blast radius. Requires a service name; falls back to search if absent."""
    t0 = time.monotonic()
    tool_input = state.get("tool_input", {})
    service = _str_param(tool_input, "service") or _str_param(tool_input, "service_id")
    if service is None:
        return await _fallback_search(state, deps, missing="service (KQ3)")
    max_depth = _int_param(tool_input, "max_depth", 5)
    result = await compute_blast_radius(
        deps.neo4j_driver, service_name=service, max_depth=max_depth
    )
    log.info("tool_kq3_done", service=service, affected=len(result.value.affected_services))
    return _query_result_to_state(state, result, node_name="kq3_blast", t0=t0)


async def kq4_change(state: AgentState, *, deps: AgentDeps) -> dict[str, object]:
    """KQ4 — change tracking. Requires a target name; falls back to search if absent."""
    t0 = time.monotonic()
    tool_input = state.get("tool_input", {})
    target = _str_param(tool_input, "target") or _str_param(tool_input, "target_name")
    if target is None:
        return await _fallback_search(state, deps, missing="target (KQ4)")
    window_days = _int_param(tool_input, "window_days", 90)
    result = await track_changes(
        deps.neo4j_driver, target_name=target, window=timedelta(days=window_days)
    )
    log.info("tool_kq4_done", target=target, changes=len(result.value.changes))
    return _query_result_to_state(state, result, node_name="kq4_change", t0=t0)


# ---------------------------------------------------------------------------
# General search + unknown
# ---------------------------------------------------------------------------


def _build_filters(tool_input: dict[str, Any]) -> SearchFilters | None:
    """Build SearchFilters from any filter hints the classifier extracted."""
    source_kind = tool_input.get("source_kind")
    entity_type = tool_input.get("entity_type")
    sk = source_kind if isinstance(source_kind, list) and source_kind else None
    et = entity_type if isinstance(entity_type, list) and entity_type else None
    if sk is None and et is None:
        return None
    return SearchFilters(source_kind=sk, entity_type=et, after=None, before=None)


async def general_search(state: AgentState, *, deps: AgentDeps) -> dict[str, object]:
    """General retrieval via hybrid_search. The agent's untyped tool for open-ended Qs."""
    t0 = time.monotonic()
    filters = _build_filters(state.get("tool_input", {}))
    async with deps.session_factory() as session:
        result = await hybrid_search(
            state["question"],
            k=deps.config.search_k,
            filters=filters,
            session=session,
            neo4j_driver=deps.neo4j_driver,
        )
    event_ids = [str(h.event_id) for h in result.hits]
    log.info("tool_search_done", hits=len(event_ids))
    return {
        "tool_output": result.model_dump(mode="json"),
        "available_event_ids": event_ids,
        "timings_ms": _timed(state, "general_search", t0),
    }


async def _fallback_search(
    state: AgentState, deps: AgentDeps, *, missing: str
) -> dict[str, object]:
    """Run general_search when a KQ node lacks a required parameter, annotating the trace."""
    log.info("tool_fallback_to_search", missing=missing)
    out = await general_search(state, deps=deps)
    prior = state.get("route_reasoning", "")
    out["route_reasoning"] = f"{prior} (fell back to search: missing {missing})".strip()
    return out


async def empty_answer(state: AgentState, *, deps: AgentDeps) -> dict[str, object]:
    """Terminal for a tool that ran successfully but found nothing citable.

    A KQ or search can legitimately return zero results (e.g. no contradictions in the
    window). With no event ids there is nothing to cite, so synthesis is skipped and we
    state the absence honestly. ``verified=True`` — an empty result is a correct answer,
    not a provenance failure.
    """
    t0 = time.monotonic()
    log.info("tool_empty_result", route=state.get("route"))
    return {
        "answer": (
            "I queried the graph but found no matching records for that question. "
            "There may be no relevant data in the corpus, or the entity named may not exist."
        ),
        "citations": [],
        "confidence": "low",
        "verified": True,
        "error": None,
        "timings_ms": _timed(state, "empty_answer", t0),
    }


async def unknown(state: AgentState, *, deps: AgentDeps) -> dict[str, object]:
    """Terminal node for out-of-scope questions. Sets a polite refusal, skips synthesis."""
    t0 = time.monotonic()
    log.info("tool_unknown", question_len=len(state.get("question", "")))
    return {
        "tool_output": None,
        "available_event_ids": [],
        "answer": _UNKNOWN_ANSWER,
        "citations": [],
        "confidence": "low",
        "verified": True,  # nothing to verify; the refusal is intentional, not a failure
        "timings_ms": _timed(state, "unknown", t0),
    }
