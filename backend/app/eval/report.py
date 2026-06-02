"""Render ``EvalResult``s to a Markdown report.

The report is the interview-defensibility artefact: overall scores, per-type breakdowns,
failure-mode counts, and the three worst concrete examples per category — plus a
hand-written Discussion section (left as a marked placeholder for the human to fill, per
the Phase 2B spec: numbers must be *interpreted*, not just pasted).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.eval.failure_modes import FailureMode

if TYPE_CHECKING:
    from app.eval.metrics import Metrics
    from app.eval.runner import EvalResult

DISCUSSION_MARKER = "<!-- DISCUSSION: replace this block with hand-written analysis -->"

_FAILURE_ORDER = [
    FailureMode.MISSED_ENTITY,
    FailureMode.SPURIOUS_ENTITY,
    FailureMode.WRONG_ENTITY_TYPE,
    FailureMode.MISSED_RELATIONSHIP,
    FailureMode.SPURIOUS_RELATIONSHIP,
    FailureMode.WRONG_RELATIONSHIP_TYPE,
    FailureMode.ALIAS_NOT_MERGED,
]


def _f(value: float) -> str:
    return f"{value:.2f}"


def _metrics_row(label: str, m: Metrics) -> str:
    return (
        f"| {label} | {m.precision:.2f} | {m.recall:.2f} | {m.f1:.2f} "
        f"| {m.true_positives} | {m.false_positives} | {m.false_negatives} |"
    )


def _overall_table(results: list[EvalResult]) -> str:
    head = (
        "| Model | Entity P | Entity R | Entity F1 | Rel P | Rel R | Rel F1 | Cost (USD) |\n"
        "|-------|----------|----------|-----------|-------|-------|--------|------------|"
    )
    rows = [
        f"| `{r.model}` | {_f(r.entity_metrics.precision)} | {_f(r.entity_metrics.recall)} "
        f"| {_f(r.entity_metrics.f1)} | {_f(r.relationship_metrics.precision)} "
        f"| {_f(r.relationship_metrics.recall)} | {_f(r.relationship_metrics.f1)} "
        f"| {r.total_cost_usd:.4f} |"
        for r in results
    ]
    return head + "\n" + "\n".join(rows)


def _by_type_section(title: str, by_type: dict[str, Metrics]) -> str:
    head = (
        f"**{title}**\n\n"
        "| Type | P | R | F1 | TP | FP | FN |\n"
        "|------|---|---|----|----|----|----|"
    )
    rows = [_metrics_row(t, by_type[t]) for t in sorted(by_type)]
    return head + "\n" + "\n".join(rows)


def _failure_counts_table(results: list[EvalResult]) -> str:
    header = "| Failure mode | " + " | ".join(f"`{r.model}`" for r in results) + " |"
    sep = "|" + "---|" * (len(results) + 1)
    rows = []
    for mode in _FAILURE_ORDER:
        cells = " | ".join(str(r.failures.count(mode)) for r in results)
        rows.append(f"| {mode.value} | {cells} |")
    return header + "\n" + sep + "\n" + "\n".join(rows)


def _worst_examples(result: EvalResult) -> str:
    lines: list[str] = []
    for mode in _FAILURE_ORDER:
        examples = result.failures.examples.get(mode, [])
        if not examples:
            continue
        lines.append(f"**{mode.value}** ({result.failures.count(mode)} total)")
        for ex in examples:
            quote = f' — evidence: "{ex.evidence_quote}"' if ex.evidence_quote else ""
            event = f" [event {ex.event_id[:8]}]" if ex.event_id else ""
            lines.append(
                f"- extractor said: {ex.what_extractor_said}; "
                f"expected: {ex.what_was_expected}{quote}{event}"
            )
        lines.append("")
    return "\n".join(lines).strip() or "_No failures recorded._"


def _calibration_line(result: EvalResult) -> str:
    c = result.failures.confidence
    verdict = "MISCALIBRATED" if c.miscalibrated else "ok"
    return (
        f"Mean confidence — correct: {_f(c.mean_confidence_correct)} "
        f"(n={c.n_correct}), incorrect: {_f(c.mean_confidence_incorrect)} "
        f"(n={c.n_incorrect}) — **{verdict}**."
    )


def render_report(
    results: list[EvalResult],
    *,
    generated_at: str | None = None,
) -> str:
    """Render a full Markdown report for one or more models.

    The model list order is preserved; for a multi-model run the overall and failure
    tables become side-by-side comparisons.
    """
    if not results:
        raise ValueError("cannot render a report with no results")

    primary = results[0]
    gt = primary.ground_truth
    parts: list[str] = []

    parts.append("# Phase 2B — Extraction Eval Results\n")
    if generated_at:
        parts.append(f"_Generated: {generated_at}_\n")
    parts.append(
        f"Corpus: **{primary.event_count} events**. Ground truth: "
        f"**{len(gt.entities)} entities**, **{len(gt.relationships)} relationships** "
        "(derived from `narrative.py` — ADR 0013).\n"
    )

    parts.append("## Overall results\n")
    parts.append(_overall_table(results) + "\n")
    total_cost = sum(r.total_cost_usd for r in results)
    fresh = sum(r.fresh_cost_usd for r in results)
    parts.append(
        f"\n**Total cost across all models: ${total_cost:.4f}** "
        f"(fresh API spend this run: ${fresh:.4f}; the remainder was served from cache).\n"
    )

    parts.append("## Failure modes (counts per model)\n")
    parts.append(_failure_counts_table(results) + "\n")

    for r in results:
        parts.append(f"## Model: `{r.model}`\n")
        parts.append(
            f"Parse failures: {r.parse_failures}/{r.event_count} events. "
            f"Cost: ${r.total_cost_usd:.4f}.\n"
        )
        parts.append(_calibration_line(r) + "\n")
        parts.append(_by_type_section("Entities by type", r.entity_metrics_by_type) + "\n")
        parts.append(
            _by_type_section("Relationships by type", r.relationship_metrics_by_type) + "\n"
        )
        parts.append("### Worst-case examples\n")
        parts.append(_worst_examples(r) + "\n")

    parts.append("## Discussion\n")
    parts.append(DISCUSSION_MARKER + "\n")

    return "\n".join(parts) + "\n"
