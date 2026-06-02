# ADR 0012 — Extraction via OpenRouter, JSON-mode, and a curated schema

## Status

Accepted

## Context

Phase 2B must turn raw Postgres `events` into the locked Neo4j graph using an LLM, and it
must produce an *honest, comparable* quality number — the F1 we cite when asked "how good
is your extraction?" Three forces drive the design. First, **model comparison**: a
portfolio project is stronger if it can show that the choice of model was measured, not
assumed, so we want to run the same extractor against several models cheaply. Second,
**cost visibility**: extraction over a 111-event corpus across multiple models must stay
inside a small budget (<$5) and we must be able to *report* what it cost. Third,
**reliability at the LLM boundary**: this is the first untrusted boundary in the system
(Phase 1B/1C taught us boundaries are where silent bugs live), so the output must be
machine-validatable, not prose to be regex-parsed. Doing nothing deliberate here — one
hardcoded vendor SDK, free-form prompts, no cost tracking — gives an extractor that is
hard to compare, hard to budget, and hard to trust.

## Decision

Call models through **OpenRouter's** OpenAI-compatible API so a one-string change swaps
models; prompt for **JSON-mode structured output** (`response_format={"type":"json_object"}`)
and validate with strict Pydantic rather than parsing free text; describe the target
schema to the model with a **hand-curated Markdown table**, not a dump of the Pydantic
JSON Schema; and compare **three models** — `openai/gpt-4o-mini`, `anthropic/claude-3.5-haiku`,
`google/gemini-2.0-flash` — chosen as the cheap, capable tier where the interesting
quality differences live. (At run time OpenRouter had retired `gemini-2.0-flash`; the eval
uses its cheap-tier successor `google/gemini-2.5-flash-lite` — the model *tier*, not the
exact snapshot, is what the decision turns on.)

## Alternatives Considered

### Option A — One vendor SDK directly (e.g. OpenAI or Anthropic native)

**What it is**: depend on a single provider's SDK and models.

**Pros**:
- First-party SDK, slightly richer typed features.
- One fewer hop in the network path.

**Cons**:
- Comparing models means integrating *N* SDKs with *N* auth schemes and response shapes.
- No single place to read per-call cost across vendors.
- Locks the demo's narrative to one vendor; weakens the "we measured" story.

### Option B — OpenRouter + free-form prompt, parse prose afterwards

**What it is**: OpenRouter for routing, but ask for prose and extract structure with
regex / a second LLM pass.

**Pros**:
- Maximally flexible prompt; no JSON constraints on the model.

**Cons**:
- The parse step becomes the bug surface: inconsistent list formats, commentary, and
  alias parentheticals are ours to untangle on every event.
- A second LLM pass doubles cost and adds its own failure mode.

### Option C — OpenRouter + JSON-mode + full Pydantic JSON Schema in the prompt

**What it is**: the chosen transport, but show the model `ExtractionResult.model_json_schema()`.

**Pros**:
- The prompt schema is guaranteed in sync with the validator.

**Cons**:
- ~1,500 tokens of nested `$defs`/`anyOf`/`allOf` per call, repeated 111×3 times.
- Smaller models (haiku, flash) follow a nested `$ref` schema worse than a plain English
  table, and the union syntax invites the model to echo schema keywords as values.

**Chosen: OpenRouter + JSON-mode + curated schema** (Option C's transport, but a curated
description). OpenRouter gives one API, model comparison, and per-call cost in `usage.cost`.
JSON-mode shrinks our problem from "extract from prose" to "validate a JSON shape". The
curated schema costs a quarter of the tokens and extracts better on the small models — the
sync risk with the Pydantic model is mitigated by keeping both in one file and hashing the
description into the run's prompt fingerprint.

## Consequences

**Enables**: swapping or adding a model is a string; the three-model comparison table is
nearly free; every call's real dollar cost is logged and summed; the parser owns a small,
well-defined validation surface instead of an open-ended parsing one.

**Constrains**: we depend on OpenRouter availability and on its `usage.cost` accounting;
JSON-mode support varies slightly by model (handled by a defensive fence-strip in the
parser). The curated schema must be hand-maintained alongside the Pydantic model.

**Locked into**: the `ExtractionResult` output shape (flat entities + relationships keyed
by name) and the `extracted_by = "{model}@{prompt_version}"` provenance convention now
recorded on every edge.

**At larger scale / in production**: we would add a request budget/rate-limiter, persist
raw responses for replay/audit beyond the dev cache, and likely pin specific model
snapshots (not floating aliases) so extraction is reproducible across model updates.

## Interview Defense

*"Why OpenRouter and not just OpenAI?"* — The deliverable is a *measured* extractor, not a
working one. OpenRouter lets the same code judge three models and read each one's cost in a
single field, which is what makes the comparison table and the cost report cheap. *"Why
not give the model your real schema?"* — We do, for validation; we just don't *show* it the
120-line JSON-Schema dump, because a curated English table is a quarter of the tokens and
extracts better on the cheap models, and a bare F1 with a clear cost line beats a marginally
"more correct" schema the small models follow worse.
