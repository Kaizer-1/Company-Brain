# ADR 0016 — Temporal query model: `as_of` + `SUPERSEDES`

## Status

Accepted

## Context

KQ2 ("decisions contradicted by discussions in the last month") and KQ4 ("what changed in
the last quarter") are time-windowed relative to *now*. But the synthetic corpus is anchored
to a fixed `REFERENCE_NOW = 2026-06-01` (Phase 2A), and the recent tail the generator
deliberately placed at 16–22 days before that anchor is the data both queries depend on. If a
query evaluated windows against `datetime.now()`, every run after 2026-06 would slide the
window past the data and return nothing — a silent, time-dependent eval failure. Separately,
the `Decision` schema reserves `valid_from`/`valid_to`/`status`, but extraction never populates
the dates, and there is no graph-native signal for supersession (graph-schema open question
#5 deferred a `SUPERSEDES` edge to "Phase 4A").

## Decision

Every temporal query takes `as_of: datetime | None = None` that defaults to
`synthetic.REFERENCE_NOW`; windows are computed as `as_of - window`. Decision temporal fields
are populated by a Phase-3B enricher from authoritative provenance (`valid_from` = earliest
source-event timestamp). We pull `SUPERSEDES` (`Decision -> Decision`) into the closed schema
now, derived from the decision body's "supersedes D-####" text, and use it to set the
superseded decision's `status='superseded'` and `valid_to`.

## Alternatives Considered

### Option A — `datetime.now()` windows

**What it is**: evaluate windows against wall-clock now.

**Pros**: matches production semantics with no parameter.

**Cons**: the eval corpus is frozen at `REFERENCE_NOW`; windows drift off the data immediately;
KQ2/KQ4 become un-testable and the demo rots with time.

### Option B — `as_of` parameter defaulting to `REFERENCE_NOW` *(chosen)*

**What it is**: an explicit injectable "now" that defaults to the corpus anchor.

**Pros**: dev/eval are reproducible; production overrides with real now; one well-named seam;
makes "what was true at time T" expressible later.

**Cons**: callers must know the default exists (documented in every query docstring and in
CLAUDE.md).

### Option C — bitemporal model

**What it is**: separate transaction time and valid time on every fact.

**Pros**: gold-standard auditability.

**Cons**: doubles every temporal property and complicates every query; rejected in
graph-schema.md for this demo's scale. Overkill.

## Consequences

**Enables**: deterministic temporal eval; a clean dev/prod boundary; KQ4's timeline rendered
with real supersession links.

**Constrains**: `SUPERSEDES` is now part of the closed vocabulary (9 → 10 edge types); a
future schema audit must account for it.

**Locked into**: `REFERENCE_NOW` as the dev/eval clock; changing the corpus anchor shifts
every window.

**At larger scale / in production**: `as_of` defaults to `datetime.now(UTC)` via config; the
"supersedes" signal would come from a structured decision-record field, not body-text regex.

## Interview Defense

> "We made `now` an injectable parameter defaulting to the corpus's frozen reference time,
> because our eval data is anchored there — wall-clock windows would slide off the data and
> break the demo over time. The trade-off is callers must respect the default; production just
> passes real now. We pulled the `SUPERSEDES` edge forward from a deferred schema question
> because KQ4's timeline and the temporal enricher both need a graph-native supersession signal."
