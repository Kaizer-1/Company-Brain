# Company Brain — LLM Extraction Pipeline (Phase 2B)

> **Status**: Implemented in Phase 2B. Decisions captured in [ADR 0012](../decisions/0012-extraction-via-openrouter.md)
> (OpenRouter + JSON-mode + curated schema) and [ADR 0013](../decisions/0013-eval-ground-truth-from-narrative.md)
> (eval ground truth derived from `narrative.py`).
> Code: [`backend/app/extraction/`](../../backend/app/extraction/) (pipeline) and
> [`backend/app/eval/`](../../backend/app/eval/) (harness).

This document is the long-form rationale for how Company Brain turns the raw Postgres
`events` log (Phase 2A) into the locked Neo4j graph (Phase 1B), and how we *measure*
whether that extraction is any good. The measurement is the point: the numbers produced
by the eval harness are what we cite when an interviewer asks "how good is your
extraction?" An honest 0.78 F1 with a named failure-mode taxonomy is worth more than a
claimed 0.95 with no failure analysis. This pipeline is built so the honest number is the
one we get.

---

## Pipeline overview

The flow is a straight line from a Postgres row to a Neo4j subgraph, with an audit row
written for every attempt:

```
Postgres events → prompt builder → LLM (via OpenRouter) →
  JSON validator (Pydantic, strict) → graph writer (Neo4j MERGE) →
    extraction_runs row (Postgres audit)
                                    ↓
                          eval harness reads the extractor's OUTPUT,
                          compares to ground truth from narrative.py,
                          emits precision/recall/F1 + failure modes
```

One event is read from Postgres (`EventDTO`). The **prompt builder** (`prompts.py`)
wraps its `content` in a system instruction, a curated schema description, and two
worked examples. The **client** (`client.py`) sends that to a model through OpenRouter,
requesting a single JSON object, and returns the response text plus the real dollar cost
of the call. The **parser** (`parser.py`) strictly validates that text into an
`ExtractionResult` — a flat list of entities and relationships. The **graph writer**
(`graph_writer.py`) `MERGE`s those into Neo4j with provenance pointing back to the event
UUID. Finally the **pipeline** (`pipeline.py`) records the whole attempt in
`extraction_runs` — created in the *failed* state up front (Phase 1C convention), flipped
to *success* only after a clean parse-and-write.

The single most important architectural line is the one between the *extractor* and the
*eval*. The extractor does not know the eval exists; the eval runs the extractor and
judges its output. That separation is what lets us swap models without touching the eval,
and rewrite the eval without touching the extractor. The eval harness deliberately judges
the extractor's **`ExtractionResult` output**, not the resulting Neo4j graph: judging the
output keeps eval correctness independent of graph-writer correctness (which has its own
tests), and lets the eval run with nothing but an API key — no databases.

---

## Why structured-output prompting, not free-form-then-parse

A tempting first design is to ask the model to "describe the entities and relationships"
in prose and then parse them out with regexes or a second LLM call. We reject this. The
failure surface of free-form-then-parse is enormous: the model wanders into commentary,
formats lists three different ways across three events, and emits "the auth service
(formerly legacy-auth)" in a way no regex reliably splits. Every one of those is a parse
bug we would own.

Instead we prompt for **structured output**: we describe a JSON object shape in the
prompt and pair it with the model's JSON-object response mode
(`response_format={"type":"json_object"}`, set in `client.py`). The model is constrained
to emit syntactically valid JSON; our job shrinks to *schema* validation (does this valid
JSON have the right fields and types?) rather than *extraction from prose*. JSON-mode is
supported across all three compared models via OpenRouter, so the same code path serves
gpt-4o-mini, claude-3.5-haiku, and gemini-2.5-flash-lite (the cheap-tier successor to the
specced gemini-2.0-flash, which OpenRouter retired). Where a model ignores JSON-mode and
wraps its answer in a ```` ```json ```` fence anyway, the parser strips the fence
defensively before validating — but the fence is the exception, not the parsing strategy.

---

## The extraction prompt design

The prompt is the highest-leverage artefact in the phase, so it lives in exactly one
file (`prompts.py`) to make iteration cheap. It has three parts: a **system prompt** that
sets the role and the hard rules, a **curated schema description**, and **two few-shot
examples**.

The most important single decision in the whole prompt is that **every extracted item
must carry an `evidence_quote`** — an exact substring of the event that justifies it. This
does two things. First, it raises precision: a model that must quote the text to assert a
fact will not assert facts the text does not contain, which is exactly the discipline that
kills hallucinated edges. Second, it gives the eval a debugging anchor — when an
extraction is wrong, the quote shows *why* the model thought it was right, which is how we
populate the worst-case examples in the report.

The two few-shot examples are chosen deliberately. The **positive** example is a compact
decision record that yields several entities (a Decision, a System, a Service, two People)
and the `DEPRECATES`/`ABOUT`/`APPROVED_BY` edges between them — it teaches the rich, multi-
entity extraction the corpus needs. The **negative** example is a vague Slack message
("we should probably move some of this stuff around at some point… anyway, lunch?") whose
correct answer is `{"entities": [], "relationships": []}`. The negative example is the one
that most improves precision: roughly a third of the corpus is ambient chit-chat, and a
model that manufactures entities from it tanks precision. Showing it the empty answer once
is far more effective than any number of "be careful" instructions.

The actual prompt text follows. This is the verbatim system prompt and schema description
from `prompts.py`; the assembled prompt sent per event (system + schema + both worked
examples + the event) is ~220 lines.

### System prompt (verbatim)

```text
You are a precise information-extraction engine for a software company's knowledge
graph. You read ONE event at a time — a Slack message, an architecture/decision
document, or a wiki page — and return the entities and relationships that the text of
THAT event explicitly asserts.

Your output is consumed by an automated pipeline, not a human. You MUST return a single
JSON object and nothing else: no prose, no markdown, no code fences.

CORE PRINCIPLE — GROUND EVERYTHING IN THE TEXT.
Extract only what the event states or directly implies. You are rewarded for precision,
not coverage. When in doubt, leave it out. Never use outside knowledge about real
companies, common architectures, or what services "usually" depend on. If the event does
not mention it, it does not exist for you.

EVIDENCE IS MANDATORY.
Every entity and every relationship MUST include an `evidence_quote`: an exact,
verbatim substring copied from the event that justifies the extraction. If you cannot
quote a span of the event for an item, do not extract that item. Do not paraphrase the
quote.

ENTITY TYPES (closed set — use no others):
- Person: a human (engineer, lead, approver, author). Names, @handles, or emails.
- Service: a deployed, running software unit with owners/dependencies (e.g. payments-api).
- System: a higher-level platform/asset a decision can deprecate (e.g. legacy-auth,
  primary-db, event-bus, a monolith). When unsure between Service and System: a thing
  that *runs requests and has owners* is a Service; a *platform/datastore/backbone a
  decision acts on* is a System.
- Team: a named engineering team (e.g. Payments, Platform, SRE).
- Decision: a choice that was made, usually with an ID like D-0006 and/or a title.

RELATIONSHIP TYPES (closed set — use no others). Direction matters; respect it:
- DEPENDS_ON: Service -> Service|System  ("X calls/uses/reads from/depends on Y")
- OWNED_BY: Service|System -> Person|Team  ("X is owned by / belongs to Y")
- MEMBER_OF: Person -> Team  ("X is on the Y team")
- DEPRECATES: Decision -> System  ("Decision D deprecates system S")
- ABOUT: Decision -> System|Service  ("Decision D concerns/changes X")
- APPROVED_BY: Decision -> Person  ("Decision D was approved by / signed off by P")

NAMING.
Use the most specific name the text gives. Prefer a canonical slug (auth-service) over a
descriptive phrase ("the auth service") when both appear, but if only a descriptive
phrase or a title ("the payments lead") is present, use that — a later resolution step
merges aliases. Do NOT invent a canonical name the text never uses.

CONFIDENCE.
Set `confidence` in [0,1]: ~0.9+ when the text states the fact outright, ~0.6–0.8 when
it is strongly implied, <0.5 when it is a guess (and prefer to omit guesses entirely).

EMPTY IS A VALID ANSWER.
Many messages are chit-chat, status pings, or vague musing ("we should probably tidy
this up sometime"). For those, return {"entities": [], "relationships": []}. Do not
manufacture entities or edges to seem useful.

OUTPUT SHAPE — return exactly this JSON object:
{
  "entities": [
    {"type": "<EntityType>", "canonical_name": "<name>",
     "properties": {<optional explicit attributes>},
     "evidence_quote": "<verbatim span>", "confidence": <float>}
  ],
  "relationships": [
    {"type": "<RelationshipType>", "source_canonical_name": "<name>",
     "target_canonical_name": "<name>",
     "evidence_quote": "<verbatim span>", "confidence": <float>}
  ]
}
```

### Curated schema description (verbatim)

```text
# Target schema (closed vocabularies — never use a type outside these tables)

## Entities — `entities[]`
| type     | what it is                                              | name to use                         |
|----------|---------------------------------------------------------|-------------------------------------|
| Person   | a human: engineer, lead, approver, author               | name, @handle, or email as written  |
| Service  | a deployed software unit with owners and dependencies   | its slug, e.g. `payments-api`       |
| System   | a platform/datastore/backbone a decision can deprecate  | its slug, e.g. `legacy-auth`        |
| Team     | a named engineering team                                | team name, e.g. `Payments`          |
| Decision | a recorded choice (often `D-####` and/or a title)       | the ID if present, else the title   |

Each entity: `{type, canonical_name, properties{}, evidence_quote, confidence}`.

## Relationships — `relationships[]`
| type        | source -> target          | trigger phrasing in the text                    |
|-------------|---------------------------|-------------------------------------------------|
| DEPENDS_ON  | Service -> Service/System | "A depends on / calls / reads from / uses B"     |
| OWNED_BY    | Service/System -> Person/Team | "A is owned by / belongs to / is B's"        |
| MEMBER_OF   | Person -> Team            | "P is on / is part of team T"                    |
| DEPRECATES  | Decision -> System        | "Decision deprecates / retires / sunsets S"      |
| ABOUT       | Decision -> System/Service| "Decision concerns / changes / covers X"         |
| APPROVED_BY | Decision -> Person        | "Decision approved by / signed off by P"         |
```

### Positive worked example (verbatim, abridged)

```text
EVENT:
[decision_record] ADR D-0006 — Deprecate legacy-auth; migrate all services to auth-service by Q4
Status: active
Date: 2026-03-08
Approvers: Jordan Wells (@jordan), Alice Chen (@alice)

legacy-auth is deprecated. All dependent services must migrate to auth-service by Q4.
payments-api still depends on legacy-auth and must cut over first.

CORRECT OUTPUT:
{
  "entities": [
    {"type": "Decision", "canonical_name": "D-0006", "properties": {"status": "active", ...},
     "evidence_quote": "ADR D-0006 — Deprecate legacy-auth ...", "confidence": 0.98},
    {"type": "System", "canonical_name": "legacy-auth", "properties": {"status": "deprecated"},
     "evidence_quote": "legacy-auth is deprecated.", "confidence": 0.97},
    {"type": "Service", "canonical_name": "auth-service", ...},
    {"type": "Service", "canonical_name": "payments-api", ...},
    {"type": "Person", "canonical_name": "Jordan Wells", ...},
    {"type": "Person", "canonical_name": "Alice Chen", ...}
  ],
  "relationships": [
    {"type": "DEPRECATES", "source_canonical_name": "D-0006", "target_canonical_name": "legacy-auth", ...},
    {"type": "ABOUT", "source_canonical_name": "D-0006", "target_canonical_name": "auth-service", ...},
    {"type": "APPROVED_BY", "source_canonical_name": "D-0006", "target_canonical_name": "Jordan Wells", ...},
    {"type": "APPROVED_BY", "source_canonical_name": "D-0006", "target_canonical_name": "Alice Chen", ...},
    {"type": "DEPENDS_ON", "source_canonical_name": "payments-api", "target_canonical_name": "legacy-auth", ...}
  ]
}
```

### Negative worked example (verbatim)

```text
EVENT:
[slack #general] @priya: honestly we should probably move some of this stuff around
at some point, it's getting a bit messy lol. anyway, lunch?

CORRECT OUTPUT:
{"entities": [], "relationships": []}
```

---

## Chunking strategy

For now: **one event = one chunk, no splitting.** The synthetic events are short — a
Slack message, a decision record, a wiki page — comfortably inside every compared model's
context window even with the ~220-line prompt prepended. Chunking adds cost (re-sending
the prompt per chunk) and a stitching problem (an entity mentioned in chunk 1 and depended
on in chunk 3 needs cross-chunk reconciliation) that buys us nothing at this corpus size.

The documented future move, if events grow (a 5,000-word RFC, a long meeting transcript):
split on a token budget with overlap (e.g. 1,500-token windows, 200-token overlap), run
each window independently, then union the per-window `ExtractionResult`s. The graph writer
is already idempotent (`MERGE` on canonical key with `source_event_ids` set-union), so
overlapping windows that both mention `auth-service` collapse to one node for free — the
write path needs no change to support chunking. We note it here so a future session adds
chunking deliberately rather than discovering the need by surprise.

---

## JSON schema given to the model

The schema shown to the model is a **hand-curated Markdown description, not a dump of
`ExtractionResult.model_json_schema()`.** The contrast is the whole argument:

| Curated description (what we send) | `model_json_schema()` dump (what we don't) |
|------------------------------------|--------------------------------------------|
| Two small Markdown tables (entities, relationships) + one example object — ~30 lines | ~120+ lines of nested `$defs`, `anyOf`, `allOf`, `enum`, `additionalProperties` |
| Names the six entity types and six edge types in plain English with trigger phrasing | Encodes the same vocabulary as `enum` arrays the model must cross-reference |
| Zero JSON-Schema keywords for the model to (mis)interpret | Full of `"$ref": "#/$defs/RelationshipType"` indirection that smaller models follow poorly |
| Cheap: ~400 tokens | Expensive: ~1,500 tokens, repeated on every one of 111×3 calls |

A 120-line schema makes the prompt expensive *and* measurably worse: the smaller models in
the comparison (haiku, flash) follow a clean English table more reliably than a nested
`$defs` graph, and the `anyOf` unions (`Service | System` targets) invite the model to
emit the schema's own union syntax instead of a concrete value. The curated table says the
same thing in a quarter of the tokens, so we curate by hand and keep the Pydantic model
(`ExtractionResult`) purely for *validating* the response — never for *describing* it to
the model. The Pydantic model and the curated description are kept in sync by the same
author in the same file; the prompt fingerprint (`prompt_fingerprint()`) hashes the
description so a drift between them is at least auditable in `extraction_runs`.

---

## Validation strategy

The LLM boundary is untrusted (the new boundary this phase introduces, per the Phase 1C
lesson that boundaries are where bugs hide). The parser validates with Pydantic v2 in
**strict mode** (`ExtractionResult.model_validate(payload, strict=True)`): no type
coercion, so a `confidence` returned as the string `"0.9"` is a failure, not a silent
cast. The models forbid unknown fields (`extra="forbid"`), so a hallucinated key surfaces
loudly. On any failure the parser raises a typed `ExtractionParseError` carrying the raw
response and a `stage` (`"json"` for a decode failure vs `"schema"` for a shape failure).

The pipeline's response to a failure is the fail-loud rule from Phase 1B: **log the
failure mode, mark `extraction_runs.status = "failed"` with the error message, and do not
write any partial graph state.** A bad extraction produces an audited failed row and an
unchanged graph — never a half-written subgraph reported as success. (The graph writer
also writes each event's nodes and edges in a single Neo4j transaction, so even a mid-
write error cannot leave a partial subgraph.)

---

## Provenance writing

Provenance is property-based (graph-schema.md "Provenance Model"), and the writer honours
the contract:

- **Every node carries `source_event_ids`** — the Postgres event UUID(s) it was extracted
  from. On first creation the list is `[event_id]`; on re-extraction the writer appends via
  set-union (`CASE WHEN $eid IN n.source_event_ids …`). The rule, stated explicitly: **a
  node may accumulate `source_event_ids` over many extractions.** Entity resolution is
  Phase 3B, but the schema already supports multi-source provenance, and the writer already
  populates it — when `auth-service` is mentioned in eight events, its node ends up with
  eight source ids.
- **Every edge carries `confidence`, `extracted_by`, `source_event_id`, and `created_at`.**
  `extracted_by` is `"{model}@{PROMPT_VERSION}"` (e.g. `openai/gpt-4o-mini@2b-v1`) so edges
  from a model/prompt later found unreliable can be purged. `confidence` is the model's own
  per-edge confidence, enabling a query-time precision/recall threshold (graph-schema.md
  "Confidence and Extraction Metadata"). We additionally store the `evidence_quote` on the
  edge as a grounding aid.

Because identity is best-effort this phase, `Alice Chen` and `@alice` become two `Person`
nodes (keyed by a slug of the surface form). This is the named entity-resolution caveat,
not a bug; the eval *measures* how often it happens (the `alias_not_merged` count) without
penalising F1 for it (the matcher is alias-tolerant — see ADR 0013).

---

## Cost telemetry

OpenRouter returns the real dollar cost of each call in `usage.cost` when the request asks
for it (`"usage": {"include": true}`, set in `client.py`). The client logs that cost on
every call (`openrouter_completion` structlog line), the eval harness sums it per model,
and the report prints total cost per model and the grand total. The per-event raw response
is cached on disk keyed by `(model, prompt-fingerprint, event-id)`, so re-running the eval
or adding a fourth model only pays for what is genuinely new; the report distinguishes
"total representative cost" from "fresh API spend this run". The whole three-model eval
over 111 events is budgeted under **$5** and in practice costs far less — these are cheap
models and short events.

---

## Failure modes we expect, and how we measure them

The eval classifies every false positive and false negative into a named taxonomy
(`failure_modes.py`). Naming them is what turns a bare F1 into an interview-defensible
result:

- **Missed entity** — a Person/Service/System/Team/Decision that is in ground truth and in
  the text, but the extractor did not surface. Measured as a false negative whose canonical
  key the extractor produced under *no* type.
- **Spurious entity** — an entity the extractor invented that ground truth does not contain
  (often a real-world service it "knows about", or a fragment of text mistaken for a name).
  Measured as a false positive whose key is absent from ground truth.
- **Wrong entity type** — the right entity, mislabelled: the Service-vs-System boundary is
  the schema's softest spot (graph-schema.md), so `legacy-auth` extracted as a Service is
  the canonical case. Measured as a key present in both sets but with differing type.
- **Missed relationship** — an edge the corpus asserts that the extractor did not produce
  (a `DEPENDS_ON` chain stated in text but not surfaced).
- **Spurious / hallucinated relationship** — an edge the extractor asserted that the text
  does not support (e.g. inferring `checkout DEPENDS_ON primary-db` from world knowledge).
- **Wrong relationship type** — the right endpoints, wrong edge (`OWNED_BY` extracted as
  `DEPENDS_ON`). Measured as an endpoint pair present in both sets with differing type.
- **Alias not merged** — the extractor produced two different nodes for one entity
  (`auth-service` and `AuthSvc`). Tracked as a **known limitation, not a bug** (Phase 3B
  fixes it upstream); the alias-tolerant matcher means it costs no F1 here, but the report
  counts it so the limitation is visible.
- **Confidence miscalibration** — high confidence on wrong extractions, low on right ones.
  Measured by comparing mean confidence of correct vs incorrect extractions; the report
  flags a model whose wrong extractions are, on average, at least as confident as its right
  ones.

The report shows the count of each mode per model and the three worst concrete examples
per category (the model's own `evidence_quote` plus what was expected), so the verdict in
the Discussion section is grounded in specific, inspectable cases rather than aggregate
numbers alone.

---

## Related ADRs

- [ADR 0012](../decisions/0012-extraction-via-openrouter.md) — OpenRouter + JSON-mode + curated schema: why not function calling, why not deterministic rules
- [ADR 0013](../decisions/0013-eval-ground-truth-from-narrative.md) — Eval ground truth derived from `narrative.py`: no hand-labelled annotation file
