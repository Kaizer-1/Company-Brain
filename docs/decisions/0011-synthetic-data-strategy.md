# ADR 0011 — Adversarial Hand-Curated Synthetic Data

## Status

Accepted

## Context

Phase 2A must produce the corpus that every downstream phase is evaluated against:
extraction (Phase 2B reports F1), entity resolution (Phase 3B), the four killer queries
(Phase 3A–3C), reconciliation (Phase 4), and the final demo (Phase 6). The corpus is not a
side artefact — it *is* the test fixture for the whole back half of the project. Two forces
dominate. First, **eval stability**: extraction F1 and entity-resolution precision are only
meaningful if the input is byte-for-byte reproducible across runs and machines; a corpus
that drifts makes every metric un-comparable. Second, **interview-defensibility**: the
predictable critique of any self-built knowledge-graph demo is *"of course it works — you
wrote the data so it works."* If we do nothing deliberate, we get a Faker-style pile of
random rows that is reproducible but trivially extractable, and the critique lands. The
data must be reproducible *and* genuinely hard.

## Decision

A **hand-curated fictional company** (Northwind Payments, locked in
`docs/design/synthetic-company.md`), with **adversarial cases designed by a human before any
generator code is written**, generated **deterministically** from a single seeded RNG, and
emitted as **raw `events` rows into Postgres** (not graph nodes) so the extraction pipeline
remains the thing under test.

## Alternatives Considered

### Option A — Faker-style random generator

**What it is**: generate N random people/services/messages with `faker`, wire up random
relationships.

**Pros**:
- Trivial to write; scales to any volume instantly.
- Naturally reproducible under a fixed seed.

**Cons**:
- Random data has no *planted structure*. There is no 4-hop ownership chain to find, no
  active-decision-vs-recent-discussion contradiction, no depth-≥4 dependency path — so it
  cannot exercise the killer queries at all.
- Random surface forms do not create *coherent* aliases ("Alice Chen" / `@alice` / "Al" all
  being one person). Entity resolution has nothing real to resolve.
- It makes the "you wrote the data" critique *worse*, not better: the data is both fake and
  structureless.

**Rejected**: volume without targeting is useless here. The schema's value is in traversals
random data never produces.

### Option B — A real open-source company's data (e.g. Apache mailing lists)

**What it is**: ingest real ASF dev@ mailing-list archives or a public Slack/Discourse export
as the corpus.

**Pros**:
- Genuinely realistic language, real ambiguity, real org messiness — immune to "you wrote it".
- Large and free.

**Cons**:
- **No ground truth.** We cannot score extraction F1 or entity-resolution precision without a
  hand-labelled gold set, which for thousands of real messages is a project of its own.
- The killer queries assume a *payments-company* shape (services deprecating systems,
  blast radius through a payments service). Real ASF data is about software projects, not the
  service/decision/ownership ontology our schema models — the queries would not map.
- Licensing/PII headaches; real names and emails violate the project's stated no-PII scope.
- Non-deterministic to curate: re-pulling an archive can change it.

**Rejected**: no ground truth and an ontology mismatch make it unusable as an eval fixture,
despite its realism.

### Option C — An existing labelled dataset (e.g. Enron email corpus)

**What it is**: use the Enron corpus, which is large, real, and widely studied.

**Pros**:
- Real human communication at scale; some research labelling exists.
- A recognisable benchmark.

**Cons**:
- Same ontology mismatch as Option B: Enron is email about an energy/finance business, not
  services, decisions, deprecations, and dependency graphs. The four killer queries have
  nothing to traverse.
- Its labels are for email classification / social-network research, not for our
  service-ownership-and-decision graph — so they provide no ground truth *for us*.
- PII and tonal baggage (it is litigation discovery data) are a poor fit for a portfolio piece.

**Rejected**: wrong shape for the schema; its labels do not answer our questions.

### Option D — Hand-curated adversarial fictional company (chosen)

**What it is**: a human designs a small fictional company and an explicit inventory of
adversarial traps (each tied to a killer query or to entity resolution) *first*, in a design
doc; the generator mechanically composes that fixed design into events under a fixed seed.

**Pros**:
- **Ground truth is free**: because we authored every entity and relationship, the gold set
  for extraction/resolution evals is the design doc itself.
- **Targeted difficulty**: every alias, contradiction, supersession, and dependency depth is
  placed to stress a *named* later phase. Hardness is designed, not accidental.
- **On-ontology**: built directly against the locked graph schema, so all four killer queries
  traverse naturally.
- **Reproducible**: a single `random.Random(seed)` plus a fixed `REFERENCE_NOW` yields
  byte-identical output, so evals are comparable across runs and machines.
- **Defensible**: the design doc *is* the answer to "you wrote the data" — yes, and here is
  the explicit list of traps we wrote it to fail on.

**Cons**:
- Small scale; not a stress test of throughput (acceptable — that is not what we are evaluating).
- The design is labour-intensive up front (the point: the thinking happens before the code).

**Chosen**: it is the only option that gives reproducibility, ground truth, on-ontology
traversals, *and* designed adversarial difficulty simultaneously.

## Why deterministic seeding

Phase 2B reports extraction F1; Phase 3B reports entity-resolution precision/recall. Those
numbers are only meaningful if the input is fixed. A single `random.Random(seed=42)` instance
is threaded through the generator (no global `random`), and the dataset's "now" is a fixed
constant (`REFERENCE_NOW = 2026-06-01`) rather than `datetime.now()`, so `generate()` is a
pure function of the seed and produces byte-identical content every run.
`test_generator_determinism.py` enforces this as a hard contract: if it breaks, no eval run
downstream is reproducible.

## Why adversarial cases are designed before generation

If the LLM (or the generator) invented the "tricky" cases, the difficulty would be whatever
the model finds easy to produce — which is, by construction, what models find easy. The traps
must be authored by a human adversary who knows the schema's soft spots (Service/System
fuzziness, deferred entity resolution, no `SUPERSEDES` edge) and plants cases that hit them.
Hence the planted cases live as data in `narrative.py`, are asserted by `test_narrative.py`
*before* the generator is written (test-first for the part that matters), and the generator's
only job is to render them into varied natural-language surface forms.

## Why raw events into Postgres, not graph nodes

The thing under evaluation in Phase 2B is **extraction**: turning raw text into graph nodes.
If the generator wrote graph nodes directly, it would be grading its own homework — there
would be nothing left for extraction to do, and F1 would be meaningless. So Phase 2A lands
only immutable `events` rows (the provenance anchor; ADR 0009), and the graph stays empty
until Phase 2B extracts it. This also keeps the generator decoupled from Neo4j entirely.

## Consequences

**Enables**: a reproducible, ground-truthed, on-ontology eval fixture for Phases 2B–6;
extraction is genuinely tested because the generator never touches the graph.

**Constrains**: the corpus is single-company and small; broadening it means editing the design
doc (the source of truth), never ad-hoc edits in generator code. New adversarial cases are
added as data in `narrative.py` with a test first.

**Locked into**: the Northwind Payments company definition and the `REFERENCE_NOW` anchor; the
seed (`42`) used for the canonical dataset. Changing any of these invalidates downstream eval
baselines and must be a deliberate, documented act.

**At larger scale / in production**: a real system ingests real, messy, non-deterministic
data and cannot rely on a fixed seed. The reproducibility guarantee here is a *test-fixture*
property, not a production one; production would replace this generator with real source
connectors and a separately maintained, sampled gold set for evaluation.

## Interview Defense

> "We hand-built a small fictional payments company and designed the adversarial cases — the
> aliases, the active-decision-vs-recent-discussion contradiction, the depth-4 dependency
> chain — *before* writing the generator, so difficulty is intentional rather than whatever a
> model finds easy. It's fully deterministic (one seeded RNG, a fixed reference date) so every
> downstream F1 number is reproducible, and the design doc doubles as the ground-truth labels.
> We deliberately emit only raw Postgres events, never graph nodes, so the extraction pipeline
> is actually the thing being tested. The honest trade-off is scale: this proves correctness
> on hard cases, not throughput — a production system would swap the generator for real
> connectors and a sampled gold set."
