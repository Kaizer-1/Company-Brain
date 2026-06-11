"""Correctness + concurrency tests for the parallel scoped resolver (Phase 5B, ADR 0035).

These are hermetic: no Neo4j / Postgres / network. They drive ``_resolve_targets_against`` (the
parallelised inner loop) with a fake ``Merger`` + ``Adjudicator`` and patched embeddings, and
assert three things:

1. **Same final merge set as the sequential baseline.** The parallel pass and the batch
   resolver's ``_decide_and_apply`` loop, run over the same fixture, produce the *same* set of
   MERGE decisions (auto_merge / llm_merge). Parallelism changes *when* the LLM is called, not
   *what* is merged.
2. **Tier-1-first skips folded targets.** A target auto-merged in pass 1 has its remaining Tier-2
   pairs dropped — fewer LLM calls than the sequential baseline, identical merges.
3. **Tier-2 fan-out is bounded by the semaphore (5).** With more candidates than the bound, no
   more than 5 adjudications are ever in flight at once.

The real graph-state equivalence is also covered end-to-end by the ingestion eval (100% pass with
the parallel resolver) and the idempotency test; this file pins the unit-level invariants.
"""

from __future__ import annotations

import asyncio

import pytest

from app.ingestion.scoped_resolution import _resolve_targets_against
from app.models.enums import MergeDecisionType, NodeType
from app.observability import metrics
from app.resolution.models import CandidatePair, LLMVerdict, ResolvableNode
from app.resolution.resolver import _decide_and_apply
from app.resolution.rules import AliasDictionary

pytestmark = pytest.mark.asyncio

_MERGE_DECISIONS = {MergeDecisionType.auto_merge, MergeDecisionType.llm_merge}


def _person(node_id: str, *, handle: str) -> ResolvableNode:
    """A synthetic Person node (names chosen to never hit the curated alias dictionary)."""
    return ResolvableNode(
        node_type=NodeType.Person,
        node_id=node_id,
        properties={"handle": handle, "display_name": node_id},
        source_event_ids=(),
    )


class _FakeMerger:
    """Records apply_decision calls; performs no graph/DB writes."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, MergeDecisionType, int]] = []

    async def apply_decision(  # noqa: PLR0913 - mirrors Merger.apply_decision's keyword surface
        self,
        pair: CandidatePair,
        *,
        decision: MergeDecisionType,
        tier: int,
        confidence: float,
        rules_matched: list[str],
        llm_reasoning: str | None = None,
        llm_model: str | None = None,
    ) -> None:
        self.calls.append((pair.node_a.node_id, pair.node_b.node_id, decision, tier))

    def merge_set(self) -> set[tuple[str, str, MergeDecisionType]]:
        """The set of MERGE decisions (the 'final graph state' at this granularity)."""
        return {(a, b, d) for (a, b, d, _t) in self.calls if d in _MERGE_DECISIONS}


class _FakeAdjudicator:
    """Returns ``same=True`` only for configured pairs; tracks call count + max concurrency."""

    model = "fake-model"

    def __init__(self, same_pairs: set[tuple[str, str]] | None = None) -> None:
        self._same_pairs = same_pairs or set()
        self.calls: list[tuple[str, str]] = []
        self._in_flight = 0
        self.max_in_flight = 0

    async def adjudicate(
        self, pair: CandidatePair, *, snippets_a: list[str], snippets_b: list[str]
    ) -> LLMVerdict:
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        await asyncio.sleep(0.02)  # hold the slot so concurrent tasks pile up against the semaphore
        self._in_flight -= 1
        self.calls.append((pair.node_a.node_id, pair.node_b.node_id))
        same = (pair.node_a.node_id, pair.node_b.node_id) in self._same_pairs
        return LLMVerdict(same=same, confidence=0.9 if same else 0.1, reasoning="fake")


def _patch_embeddings(monkeypatch: pytest.MonkeyPatch, sim: float) -> None:
    """Stub the embedding model + similarity so tests are hermetic and tier is controllable."""
    import app.ingestion.scoped_resolution as mod

    monkeypatch.setattr(mod, "embed_texts", lambda inputs: [[1.0] for _ in inputs])
    monkeypatch.setattr(mod, "cosine_similarity", lambda _a, _b: sim)


async def _run_sequential(
    targets: list[ResolvableNode], others: list[ResolvableNode], *, sim: float, adj: _FakeAdjudicator
) -> _FakeMerger:
    """Reference: the batch resolver's per-pair loop (the pre-5B behaviour)."""
    merger = _FakeMerger()
    aliases = AliasDictionary()
    for t in targets:
        for o in others:
            pair = CandidatePair(node_a=t, node_b=o, similarity=sim)
            await _decide_and_apply(pair, merger, aliases, adj, events=object())  # type: ignore[arg-type]
    return merger


async def test_parallel_matches_sequential_merge_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parallel and sequential produce the same MERGE set; parallel makes fewer LLM calls."""
    metrics.reset()
    _patch_embeddings(monkeypatch, sim=0.9)

    x, y = _person("ztest-x", handle="@zzdup"), _person("ztest-y", handle="@ytest")
    a = _person("ztest-a", handle="@zzdup")  # shares X's handle → Tier-1 auto-merge
    b, c = _person("ztest-b", handle="@btest"), _person("ztest-c", handle="@ctest")
    targets, others = [x, y], [a, b, c]
    same_pairs = {("ztest-y", "ztest-b")}  # the one genuine LLM merge

    par_merger = _FakeMerger()
    adj_par = _FakeAdjudicator(same_pairs)
    await _resolve_targets_against(
        targets, others, merger=par_merger,  # type: ignore[arg-type]
        aliases=AliasDictionary(), adjudicator=adj_par, events=object(),  # type: ignore[arg-type]
    )

    adj_seq = _FakeAdjudicator(same_pairs)
    seq_merger = await _run_sequential(targets, others, sim=0.9, adj=adj_seq)

    # Same final merges: {X→A auto, Y→B llm}.
    assert par_merger.merge_set() == seq_merger.merge_set()
    assert (("ztest-x", "ztest-a", MergeDecisionType.auto_merge)) in par_merger.merge_set()
    assert (("ztest-y", "ztest-b", MergeDecisionType.llm_merge)) in par_merger.merge_set()

    # Parallel skipped X's Tier-2 pairs (X folded in Tier-1): fewer LLM calls, same result.
    assert len(adj_par.calls) == 3  # only Y's three pairs
    assert len(adj_seq.calls) == 5  # X's two + Y's three
    # Metrics counted Tier-1 once and Tier-2 three times (the skipped pairs are not adjudicated).
    assert metrics.resolution_adjudications_by_tier == {"1": 1, "2": 3}


async def test_tier1_first_skips_folded_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """A target auto-merged in pass 1 has all its Tier-2 pairs dropped (no LLM calls)."""
    metrics.reset()
    _patch_embeddings(monkeypatch, sim=0.9)

    x = _person("ztest-x", handle="@zzdup")
    a = _person("ztest-a", handle="@zzdup")  # Tier-1 match
    b, c = _person("ztest-b", handle="@b"), _person("ztest-c", handle="@c")

    merger = _FakeMerger()
    adj = _FakeAdjudicator()
    await _resolve_targets_against(
        [x], [a, b, c], merger=merger,  # type: ignore[arg-type]
        aliases=AliasDictionary(), adjudicator=adj, events=object(),  # type: ignore[arg-type]
    )

    assert adj.calls == []  # X folded into A; X-B and X-C never adjudicated
    assert merger.merge_set() == {("ztest-x", "ztest-a", MergeDecisionType.auto_merge)}
    assert metrics.resolution_adjudications_by_tier == {"1": 1}


async def test_tier2_concurrency_bounded_by_semaphore(monkeypatch: pytest.MonkeyPatch) -> None:
    """With more Tier-2 candidates than the bound, at most 5 adjudications run concurrently."""
    metrics.reset()
    _patch_embeddings(monkeypatch, sim=0.9)

    x = _person("ztest-x", handle="@x")
    others = [_person(f"ztest-o{i}", handle=f"@o{i}") for i in range(8)]  # 8 Tier-2 pairs

    merger = _FakeMerger()
    adj = _FakeAdjudicator()
    await _resolve_targets_against(
        [x], others, merger=merger,  # type: ignore[arg-type]
        aliases=AliasDictionary(), adjudicator=adj, events=object(),  # type: ignore[arg-type]
    )

    assert len(adj.calls) == 8           # all adjudicated
    assert adj.max_in_flight == 5        # bounded by Semaphore(5)
    assert metrics.resolution_adjudications_by_tier == {"2": 8}


async def test_below_threshold_pairs_skip_adjudication(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pairs below the similarity floor are Tier-3 (no LLM call), recorded as such."""
    metrics.reset()
    _patch_embeddings(monkeypatch, sim=0.5)  # < SIM_FLOOR (0.75)

    x = _person("ztest-x", handle="@x")
    others = [_person("ztest-a", handle="@a"), _person("ztest-b", handle="@b")]

    merger = _FakeMerger()
    adj = _FakeAdjudicator()
    await _resolve_targets_against(
        [x], others, merger=merger,  # type: ignore[arg-type]
        aliases=AliasDictionary(), adjudicator=adj, events=object(),  # type: ignore[arg-type]
    )

    assert adj.calls == []
    assert merger.merge_set() == set()
    assert metrics.resolution_adjudications_by_tier == {"3": 2}
