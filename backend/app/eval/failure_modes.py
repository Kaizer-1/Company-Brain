"""Classify every false positive and false negative into a named failure taxonomy.

A bare F1 is interview-fatal without this: the value of the eval is the *named* failure
modes (docs/design/extraction-pipeline.md). For each mismatch we decide which kind of
error it is, keep a few worst-case examples per kind (with the model's own evidence
quote), and summarise confidence calibration.

The taxonomy distinguishes "wrong type" (the model found the right entity/edge but
mislabelled it — e.g. Service vs System) from a plain miss or a plain hallucination,
because the three have different fixes. ``ALIAS_NOT_MERGED`` is reported as a *known
limitation*, not a bug: the alias-tolerant matcher collapses surface forms so it costs no
F1 here, but we still surface that the raw extractor would have produced split nodes —
which is exactly what Phase 3B entity resolution will fix.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.eval.ground_truth import GroundTruth
    from app.eval.matcher import EntityMention, MatchedExtraction, RelationshipMention

_MAX_EXAMPLES = 3


class FailureMode(StrEnum):
    """The closed taxonomy used in the eval report."""

    MISSED_ENTITY = "missed_entity"
    SPURIOUS_ENTITY = "spurious_entity"
    WRONG_ENTITY_TYPE = "wrong_entity_type"
    MISSED_RELATIONSHIP = "missed_relationship"
    SPURIOUS_RELATIONSHIP = "spurious_relationship"
    WRONG_RELATIONSHIP_TYPE = "wrong_relationship_type"
    ALIAS_NOT_MERGED = "alias_not_merged"


@dataclass(frozen=True)
class FailureExample:
    """One concrete instance of a failure, for the report's worst-cases section."""

    mode: FailureMode
    what_extractor_said: str
    what_was_expected: str
    evidence_quote: str
    event_id: str


@dataclass(frozen=True)
class ConfidenceStats:
    """Calibration summary: do correct extractions carry higher confidence than wrong ones?"""

    mean_confidence_correct: float
    mean_confidence_incorrect: float
    n_correct: int
    n_incorrect: int

    @property
    def miscalibrated(self) -> bool:
        """True if wrong extractions are (on average) at least as confident as right ones."""
        if self.n_correct == 0 or self.n_incorrect == 0:
            return False
        return self.mean_confidence_incorrect >= self.mean_confidence_correct


@dataclass
class FailureBreakdown:
    """Counts + examples per failure mode, plus confidence calibration."""

    counts: dict[FailureMode, int] = field(default_factory=dict)
    examples: dict[FailureMode, list[FailureExample]] = field(default_factory=dict)
    confidence: ConfidenceStats = field(
        default_factory=lambda: ConfidenceStats(0.0, 0.0, 0, 0)
    )

    def count(self, mode: FailureMode) -> int:
        return self.counts.get(mode, 0)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def classify(matched: MatchedExtraction, gt: GroundTruth) -> FailureBreakdown:
    """Produce counts and worst-case examples for every failure mode."""
    breakdown = FailureBreakdown()
    counts: dict[FailureMode, int] = defaultdict(int)
    examples: dict[FailureMode, list[FailureExample]] = defaultdict(list)

    def add_example(example: FailureExample) -> None:
        bucket = examples[example.mode]
        if len(bucket) < _MAX_EXAMPLES:
            bucket.append(example)

    # ---- Entities --------------------------------------------------------
    extracted_entities = matched.entity_keys  # frozenset[(type, key)]
    expected_entities = {(e.type, e.canonical_name) for e in gt.entities}
    extracted_by_key: dict[str, set[str]] = defaultdict(set)
    expected_by_key: dict[str, set[str]] = defaultdict(set)
    for etype, key in extracted_entities:
        extracted_by_key[key].add(etype)
    for etype, key in expected_entities:
        expected_by_key[key].add(etype)

    mention_lookup: dict[tuple[str, str], EntityMention] = {}
    for m in matched.entity_mentions:
        mention_lookup.setdefault((m.type, m.canonical_key), m)

    # Wrong entity type: a key both sides know, but with differing type sets.
    wrong_type_keys = {
        key
        for key in (extracted_by_key.keys() & expected_by_key.keys())
        if extracted_by_key[key] != expected_by_key[key]
    }
    for key in sorted(wrong_type_keys):
        counts[FailureMode.WRONG_ENTITY_TYPE] += 1
        got = ", ".join(sorted(extracted_by_key[key]))
        want = ", ".join(sorted(expected_by_key[key]))
        ex_m = next((mm for (t, k), mm in mention_lookup.items() if k == key), None)
        add_example(
            FailureExample(
                FailureMode.WRONG_ENTITY_TYPE,
                what_extractor_said=f"{key} as {got}",
                what_was_expected=f"{key} as {want}",
                evidence_quote=ex_m.evidence_quote if ex_m else "",
                event_id=ex_m.event_id if ex_m else "",
            )
        )

    for etype, key in sorted(expected_entities - extracted_entities):
        if key in extracted_by_key:  # found under a different type -> already wrong-type
            continue
        counts[FailureMode.MISSED_ENTITY] += 1
        add_example(
            FailureExample(
                FailureMode.MISSED_ENTITY,
                what_extractor_said="(nothing)",
                what_was_expected=f"{etype} {key}",
                evidence_quote="",
                event_id="",
            )
        )

    for etype, key in sorted(extracted_entities - expected_entities):
        if key in expected_by_key:  # right name, wrong type -> already counted
            continue
        counts[FailureMode.SPURIOUS_ENTITY] += 1
        sp_m = mention_lookup.get((etype, key))
        add_example(
            FailureExample(
                FailureMode.SPURIOUS_ENTITY,
                what_extractor_said=f"{etype} {key} (raw: {sp_m.raw_name if sp_m else key!r})",
                what_was_expected="(not in ground truth)",
                evidence_quote=sp_m.evidence_quote if sp_m else "",
                event_id=sp_m.event_id if sp_m else "",
            )
        )

    # ---- Relationships ---------------------------------------------------
    extracted_rels = matched.relationship_keys
    expected_rels = {
        (r.type, r.source_canonical_name, r.target_canonical_name) for r in gt.relationships
    }
    extracted_pairs: dict[tuple[str, str], set[str]] = defaultdict(set)
    expected_pairs: dict[tuple[str, str], set[str]] = defaultdict(set)
    for rtype, src, tgt in extracted_rels:
        extracted_pairs[(src, tgt)].add(str(rtype))
    for rtype, src, tgt in expected_rels:
        expected_pairs[(src, tgt)].add(str(rtype))

    rel_mention_lookup: dict[tuple[str, str, str], RelationshipMention] = {}
    for rm in matched.relationship_mentions:
        rel_mention_lookup.setdefault((str(rm.type), rm.source_key, rm.target_key), rm)

    wrong_rel_pairs = {
        pair
        for pair in (extracted_pairs.keys() & expected_pairs.keys())
        if extracted_pairs[pair] != expected_pairs[pair]
    }
    for src, tgt in sorted(wrong_rel_pairs):
        counts[FailureMode.WRONG_RELATIONSHIP_TYPE] += 1
        got = ", ".join(sorted(extracted_pairs[(src, tgt)]))
        want = ", ".join(sorted(expected_pairs[(src, tgt)]))
        ex_rm = next(
            (r for (t, s, g), r in rel_mention_lookup.items() if s == src and g == tgt),
            None,
        )
        add_example(
            FailureExample(
                FailureMode.WRONG_RELATIONSHIP_TYPE,
                what_extractor_said=f"{src} -[{got}]-> {tgt}",
                what_was_expected=f"{src} -[{want}]-> {tgt}",
                evidence_quote=ex_rm.evidence_quote if ex_rm else "",
                event_id=ex_rm.event_id if ex_rm else "",
            )
        )

    for rtype, src, tgt in sorted(expected_rels - extracted_rels, key=lambda x: (str(x[0]), x[1], x[2])):
        if (src, tgt) in extracted_pairs:
            continue
        counts[FailureMode.MISSED_RELATIONSHIP] += 1
        add_example(
            FailureExample(
                FailureMode.MISSED_RELATIONSHIP,
                what_extractor_said="(nothing)",
                what_was_expected=f"{src} -[{rtype}]-> {tgt}",
                evidence_quote="",
                event_id="",
            )
        )

    for rtype, src, tgt in sorted(extracted_rels - expected_rels, key=lambda x: (str(x[0]), x[1], x[2])):
        if (src, tgt) in expected_pairs:
            continue
        counts[FailureMode.SPURIOUS_RELATIONSHIP] += 1
        sp_rm = rel_mention_lookup.get((str(rtype), src, tgt))
        add_example(
            FailureExample(
                FailureMode.SPURIOUS_RELATIONSHIP,
                what_extractor_said=f"{src} -[{rtype}]-> {tgt}",
                what_was_expected="(not in ground truth)",
                evidence_quote=sp_rm.evidence_quote if sp_rm else "",
                event_id=sp_rm.event_id if sp_rm else "",
            )
        )

    # ---- Alias-not-merged (known limitation, not a bug) ------------------
    raw_forms_per_key: dict[str, set[str]] = defaultdict(set)
    for m in matched.entity_mentions:
        raw_forms_per_key[m.canonical_key].add(m.raw_name)
    for key, forms in sorted(raw_forms_per_key.items()):
        if len(forms) >= 2:
            counts[FailureMode.ALIAS_NOT_MERGED] += 1
            add_example(
                FailureExample(
                    FailureMode.ALIAS_NOT_MERGED,
                    what_extractor_said=f"{key}: {sorted(forms)}",
                    what_was_expected="one node (Phase 3B will merge these)",
                    evidence_quote="",
                    event_id="",
                )
            )

    # ---- Confidence calibration -----------------------------------------
    correct_conf: list[float] = []
    incorrect_conf: list[float] = []
    for m in matched.entity_mentions:
        bucket = correct_conf if (m.type, m.canonical_key) in expected_entities else incorrect_conf
        bucket.append(m.confidence)
    for rm in matched.relationship_mentions:
        is_correct = (rm.type, rm.source_key, rm.target_key) in expected_rels
        (correct_conf if is_correct else incorrect_conf).append(rm.confidence)

    breakdown.counts = dict(counts)
    breakdown.examples = {mode: exs for mode, exs in examples.items()}
    breakdown.confidence = ConfidenceStats(
        mean_confidence_correct=_mean(correct_conf),
        mean_confidence_incorrect=_mean(incorrect_conf),
        n_correct=len(correct_conf),
        n_incorrect=len(incorrect_conf),
    )
    return breakdown
