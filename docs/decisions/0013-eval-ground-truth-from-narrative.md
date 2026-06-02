# ADR 0013 — Eval ground truth derived from `narrative.py`, not a hand-labelled file

## Status

Accepted

## Context

The Phase 2B eval needs a gold set: the entities and relationships a perfect extractor
should recover from the corpus. The obvious approach is to hand-label a JSON file of
expected outputs. But the corpus is itself *generated* from `company.py` + `narrative.py`
(Phase 2A), deterministically from seed 42. A separate hand-labelled file would be a second
source of truth that can drift from the generator: change a planted dependency edge in
`narrative.py` and the hand-labelled file is silently wrong, so the F1 it reports is
measuring the gap between the extractor and a stale label set — a meaningless number that
*looks* meaningful. Phase 2A's HANDOFF explicitly flagged this and recommended deriving
ground truth from the generator. If we did nothing, eval drift would be invisible until it
embarrassed us in an interview.

## Decision

Derive the gold set **programmatically from the same dataclasses the generator uses**:
`build_ground_truth()` reads `company.py` (entities) and `narrative.py` (the planted
`DEPENDENCY_GRAPH`, decision `approvers`/`about`/`deprecates`, service ownership, org
membership) and returns a `GroundTruth` of `frozenset[ExpectedEntity]` and
`frozenset[ExpectedRelationship]` in canonical-key space. No hand-labelled file exists.

## Alternatives Considered

### Option A — Hand-labelled JSON gold file

**What it is**: a checked-in `gold.json` of expected entities/edges per event, written by
hand.

**Pros**:
- Can encode subtle per-event expectations the generator does not model.
- Independent of generator bugs (a true second opinion).

**Cons**:
- A second source of truth that drifts the moment `narrative.py` changes.
- Labour-intensive to keep correct across 111 events as the corpus evolves.

### Option B — Derive from the generator dataclasses *(chosen)*

**What it is**: a pure function over `company.py` + `narrative.py` that emits the gold set.

**Pros**:
- Single source of truth; regenerating the corpus regenerates the truth for free.
- No drift: the same edit changes both corpus and gold set.
- Testable as a pure function.

**Cons**:
- The eval is only as good as `narrative.py` — a planted case that is wrong is "correct"
  to the eval. Accepted, because `narrative.py` is the dataset we deliberately control.

## What the derivation returns

`GroundTruth.entities` is the set of `(type, canonical_key)` for every Person, Service,
System, Team, and Decision **defined in `company.py` whose surface form appears in the
generated corpus** (the inclusion rule). `GroundTruth.relationships` is the set of
`(type, source_key, target_key)` for the structural edges the corpus *asserts*:
`DEPENDS_ON` (the dependency map), `OWNED_BY` (service catalog owners), `MEMBER_OF` (org
chart), and `DEPRECATES`/`ABOUT`/`APPROVED_BY` (decision records).

## Named limitations

1. **The eval is only as good as `narrative.py`.** This is the central caveat and it is
   acceptable: that dataset is the thing we control and have designed to be adversarial.
2. **Inclusion rule excludes the unmentioned.** An entity named *only* by, say, an email
   address that never appears in any event is *not* in ground truth — the model cannot be
   expected to know an entity it was never shown. The rule is: in `company.py` **and** a
   surface form appears in ≥1 generated event.
3. **Out-of-scope edges.** `Message`-anchored edges (`AUTHORED`, `MENTIONS`, `CONTRADICTS`)
   and `System` ownership are excluded — `Message` nodes are created mechanically from
   events (not extracted), and no event states which team *owns* a system.
4. **Alias tolerance lives in the matcher, not the truth.** Because entity resolution is
   Phase 3B, the matcher canonicalises surface forms (`AuthSvc` → `auth-service`) before
   comparing, so the gold set stays in clean canonical-key space and the extractor is not
   penalised for un-merged aliases (those are counted separately as a known limitation).

## Consequences

**Enables**: zero-drift eval, a pure-function gold set that tests can assert against, and a
report whose numbers move only when the data or the extractor moves.

**Constrains**: ground-truth quality is bounded by `narrative.py`; a real-world eval would
need human-labelled data from real sources.

**Locked into**: the canonical-key space shared by `build_ground_truth()` and the matcher,
and the inclusion rule above.

**At larger scale / in production**: ground truth would come from human annotation of real
documents with inter-annotator agreement, and this generator-derived gold set would become
a fast, deterministic regression check rather than the primary quality measure.

## Interview Defense

*"Isn't deriving ground truth from your own generator circular?"* — It would be if the
generator and the extractor shared code, but they do not: the generator renders entities
into varied natural-language *text*, and the extractor must recover structure from that
text with no access to the dataclasses. The derivation just spares us a hand-labelled file
that would drift; the extraction problem stays genuinely hard. The honest limitation —
"only as good as `narrative.py`" — is named, not hidden, and is exactly why Phase 2A made
`narrative.py` adversarial.
