"""Search quality eval for Phase 3D.

Reads the 20 hand-curated NL questions from ``backend/data/search_eval_questions.json``,
runs each through ``hybrid_search``, and computes:
  - Recall@10 per question and mean across all questions
  - Mean Reciprocal Rank (MRR)
  - Mean latency (total_ms)

All expected-ID sets are defined in the JSON file; this module does not tune them —
the numbers reported are whatever the system produces.

Honest targets (from the Phase 3D spec):
  Recall@10 ≥ 0.70
  MRR       ≥ 0.50
  Latency   ≤ 500ms (per query, warm)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from app.search.retriever import hybrid_search

if TYPE_CHECKING:
    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

EVAL_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "search_eval_questions.json"


@dataclass
class QuestionResult:
    """Eval result for a single question."""

    question_id: str
    question: str
    expected_ids: list[str]
    returned_ids: list[str]
    recall_at_10: float
    reciprocal_rank: float
    total_ms: float
    hits_found: list[str] = field(default_factory=list)
    misses: list[str] = field(default_factory=list)


@dataclass
class SearchEvalResult:
    """Aggregated eval result across all questions."""

    questions: list[QuestionResult] = field(default_factory=list)
    mean_recall_at_10: float = 0.0
    mean_mrr: float = 0.0
    mean_latency_ms: float = 0.0
    passed: bool = False


def _recall_at_k(expected: list[str], returned: list[str], k: int = 10) -> float:
    if not expected:
        return 1.0
    top_k = set(returned[:k])
    hits = sum(1 for eid in expected if eid in top_k)
    return hits / len(expected)


def _reciprocal_rank(expected: list[str], returned: list[str]) -> float:
    expected_set = set(expected)
    for rank, eid in enumerate(returned, start=1):
        if eid in expected_set:
            return 1.0 / rank
    return 0.0


def load_questions() -> list[dict[str, object]]:
    """Load the eval question bank from the JSON file."""
    with EVAL_DATA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)  # type: ignore[no-any-return]


async def run_search_eval(
    session: AsyncSession,
    neo4j_driver: AsyncDriver,
    *,
    k: int = 10,
) -> SearchEvalResult:
    """Run all eval questions and return aggregated metrics."""
    questions = load_questions()
    results: list[QuestionResult] = []

    log.info("search_eval_start", question_count=len(questions), k=k)

    for q in questions:
        qid = str(q["id"])
        text = str(q["question"])
        expected_ids: list[str] = [str(e) for e in (q.get("expected_in_top10") or [])]

        sr = await hybrid_search(text, k=k, session=session, neo4j_driver=neo4j_driver)
        returned_ids = [str(h.event_id) for h in sr.hits]

        recall = _recall_at_k(expected_ids, returned_ids, k=k)
        rr = _reciprocal_rank(expected_ids, returned_ids)
        hits_found = [eid for eid in expected_ids if eid in returned_ids]
        misses = [eid for eid in expected_ids if eid not in returned_ids]

        results.append(
            QuestionResult(
                question_id=qid,
                question=text,
                expected_ids=expected_ids,
                returned_ids=returned_ids,
                recall_at_10=recall,
                reciprocal_rank=rr,
                total_ms=sr.total_ms,
                hits_found=hits_found,
                misses=misses,
            )
        )
        log.debug(
            "search_eval_question",
            qid=qid,
            recall=round(recall, 3),
            rr=round(rr, 3),
            latency_ms=round(sr.total_ms, 1),
        )

    mean_recall = sum(r.recall_at_10 for r in results) / len(results) if results else 0.0
    mean_mrr = sum(r.reciprocal_rank for r in results) / len(results) if results else 0.0
    mean_latency = sum(r.total_ms for r in results) / len(results) if results else 0.0

    passed = mean_recall >= 0.70 and mean_mrr >= 0.50 and mean_latency <= 500.0

    log.info(
        "search_eval_done",
        mean_recall_at_10=round(mean_recall, 3),
        mean_mrr=round(mean_mrr, 3),
        mean_latency_ms=round(mean_latency, 1),
        passed=passed,
    )

    return SearchEvalResult(
        questions=results,
        mean_recall_at_10=mean_recall,
        mean_mrr=mean_mrr,
        mean_latency_ms=mean_latency,
        passed=passed,
    )


def render_search_report(result: SearchEvalResult, generated_at: str = "") -> str:
    """Render a Markdown eval report."""
    lines = [
        "# Phase 3D — Search Eval Results",
        "",
        f"**Generated**: {generated_at}  ",
        f"**Questions**: {len(result.questions)}  ",
        f"**Model**: BAAI/bge-small-en-v1.5 (384 dims)  ",
        "",
        "## Summary",
        "",
        f"| Metric | Value | Target | Pass? |",
        f"|--------|-------|--------|-------|",
        f"| Recall@10 (mean) | {result.mean_recall_at_10:.3f} | ≥ 0.70 | {'✓' if result.mean_recall_at_10 >= 0.70 else '✗'} |",
        f"| MRR (mean) | {result.mean_mrr:.3f} | ≥ 0.50 | {'✓' if result.mean_mrr >= 0.50 else '✗'} |",
        f"| Mean latency (ms) | {result.mean_latency_ms:.1f} | ≤ 500ms | {'✓' if result.mean_latency_ms <= 500.0 else '✗'} |",
        "",
        "## Per-question results",
        "",
        "| ID | Question (truncated) | Recall@10 | RR | Latency(ms) | Hits | Misses |",
        "|----|---------------------|-----------|----|-------------|------|--------|",
    ]
    for r in result.questions:
        q_short = r.question[:45] + ("…" if len(r.question) > 45 else "")
        lines.append(
            f"| {r.question_id} | {q_short} | {r.recall_at_10:.2f} | {r.reciprocal_rank:.2f} "
            f"| {r.total_ms:.0f} | {len(r.hits_found)}/{len(r.expected_ids)} | {len(r.misses)} |"
        )

    # Failure analysis
    failures = [r for r in result.questions if r.misses]
    if failures:
        lines += [
            "",
            "## Failure modes",
            "",
        ]
        for r in failures:
            lines.append(f"**{r.question_id}** — `{r.question}`")
            lines.append(f"Missed: {', '.join(r.misses[:3])}")
            lines.append("")

    lines += [
        "",
        "## Discussion",
        "",
        "*(Fill in after running. Describe: dominant failure modes, whether graph signal "
        "helps or hurts, whether blend weights should be adjusted, and what would change "
        "with a larger corpus or a better model.)*",
    ]
    return "\n".join(lines)
