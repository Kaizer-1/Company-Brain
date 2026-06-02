"""The extraction prompt: system instructions, a curated schema, and few-shot examples.

This module is the single source of truth for what the LLM is asked to do. It is kept
separate from the client (transport) and the parser (validation) so prompt iteration —
the bulk of Phase 2B's engineering effort — touches exactly one file.

Three deliberate choices, documented in ``docs/design/extraction-pipeline.md``:

- **A hand-curated ``SCHEMA_DESCRIPTION``**, not ``ExtractionResult.model_json_schema()``.
  A verbatim Pydantic JSON Schema dump is ~5x longer, full of ``$defs``/``anyOf`` noise
  that confuses smaller models and inflates token cost. A clean Markdown table of the
  closed entity/edge vocabularies extracts better and costs less. ADR 0012 §"curated
  schema".
- **Two few-shot examples**: one rich positive (a decision record yielding several
  entities and edges) and one negative (a vague message whose correct answer is empty).
  The negative example is the one that most improves precision — it teaches the model to
  *not* invent structure from chit-chat.
- **JSON-mode prompting** (paired with ``response_format={"type":"json_object"}`` at the
  client): we ask for a single JSON object and describe its shape, rather than parsing
  fenced JSON out of free text. ADR 0012 §"JSON mode over free-form".
"""

import hashlib

from app.extraction.models import (
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
)
from app.schemas.graph import RelationshipType

# Bumped whenever the prompt template changes in a way that should invalidate cached
# extractions / be auditable in extraction_runs. Stored as the run's ``model_version``
# and folded into every edge's ``extracted_by`` so a prompt regression is traceable.
PROMPT_VERSION = "2b-v1"

# ---------------------------------------------------------------------------
# System prompt — role, task, and the hard rules that bound hallucination.
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
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
"""


# ---------------------------------------------------------------------------
# Curated schema description — hand-written, NOT a JSON Schema dump.
# ---------------------------------------------------------------------------
SCHEMA_DESCRIPTION = """\
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
`properties` holds only attributes the text states explicitly, e.g. a Service's
`{"status": "deprecated"}` or a Decision's `{"status": "superseded"}`. Omit if none.

## Relationships — `relationships[]`
| type        | source -> target          | trigger phrasing in the text                    |
|-------------|---------------------------|-------------------------------------------------|
| DEPENDS_ON  | Service -> Service/System | "A depends on / calls / reads from / uses B"     |
| OWNED_BY    | Service/System -> Person/Team | "A is owned by / belongs to / is B's"        |
| MEMBER_OF   | Person -> Team            | "P is on / is part of team T"                    |
| DEPRECATES  | Decision -> System        | "Decision deprecates / retires / sunsets S"      |
| ABOUT       | Decision -> System/Service| "Decision concerns / changes / covers X"         |
| APPROVED_BY | Decision -> Person        | "Decision approved by / signed off by P"         |

Each relationship: `{type, source_canonical_name, target_canonical_name,
evidence_quote, confidence}`. Endpoints are named exactly as the text names them.
"""


# ---------------------------------------------------------------------------
# Few-shot examples. (event_content, expected ExtractionResult).
#
# Example 1 (positive): a compact decision record yields a Decision, a System, a
# Service, two People, and the DEPRECATES / ABOUT / APPROVED_BY edges between them —
# the canonical "rich" extraction.
#
# Example 2 (negative): a vague Slack message whose correct extraction is EMPTY. This
# is the example that most improves precision by teaching the model to refuse to
# invent structure from chit-chat.
# ---------------------------------------------------------------------------

_POSITIVE_EVENT = """\
[decision_record] ADR D-0006 — Deprecate legacy-auth; migrate all services to auth-service by Q4
Status: active
Date: 2026-03-08
Approvers: Jordan Wells (@jordan), Alice Chen (@alice)

legacy-auth is deprecated. All dependent services must migrate to auth-service by Q4.
payments-api still depends on legacy-auth and must cut over first."""

_POSITIVE_EXPECTED = ExtractionResult(
    entities=[
        ExtractedEntity(
            type="Decision",
            canonical_name="D-0006",
            properties={"status": "active", "title": "Deprecate legacy-auth; migrate all services to auth-service by Q4"},
            evidence_quote="ADR D-0006 — Deprecate legacy-auth; migrate all services to auth-service by Q4",
            confidence=0.98,
        ),
        ExtractedEntity(
            type="System",
            canonical_name="legacy-auth",
            properties={"status": "deprecated"},
            evidence_quote="legacy-auth is deprecated.",
            confidence=0.97,
        ),
        ExtractedEntity(
            type="Service",
            canonical_name="auth-service",
            properties={},
            evidence_quote="migrate all services to auth-service",
            confidence=0.95,
        ),
        ExtractedEntity(
            type="Service",
            canonical_name="payments-api",
            properties={},
            evidence_quote="payments-api still depends on legacy-auth",
            confidence=0.95,
        ),
        ExtractedEntity(
            type="Person",
            canonical_name="Jordan Wells",
            properties={"handle": "@jordan"},
            evidence_quote="Approvers: Jordan Wells (@jordan)",
            confidence=0.9,
        ),
        ExtractedEntity(
            type="Person",
            canonical_name="Alice Chen",
            properties={"handle": "@alice"},
            evidence_quote="Alice Chen (@alice)",
            confidence=0.9,
        ),
    ],
    relationships=[
        ExtractedRelationship(
            type=RelationshipType.DEPRECATES,
            source_canonical_name="D-0006",
            target_canonical_name="legacy-auth",
            evidence_quote="legacy-auth is deprecated.",
            confidence=0.95,
        ),
        ExtractedRelationship(
            type=RelationshipType.ABOUT,
            source_canonical_name="D-0006",
            target_canonical_name="auth-service",
            evidence_quote="migrate all services to auth-service by Q4",
            confidence=0.85,
        ),
        ExtractedRelationship(
            type=RelationshipType.APPROVED_BY,
            source_canonical_name="D-0006",
            target_canonical_name="Jordan Wells",
            evidence_quote="Approvers: Jordan Wells (@jordan)",
            confidence=0.92,
        ),
        ExtractedRelationship(
            type=RelationshipType.APPROVED_BY,
            source_canonical_name="D-0006",
            target_canonical_name="Alice Chen",
            evidence_quote="Alice Chen (@alice)",
            confidence=0.92,
        ),
        ExtractedRelationship(
            type=RelationshipType.DEPENDS_ON,
            source_canonical_name="payments-api",
            target_canonical_name="legacy-auth",
            evidence_quote="payments-api still depends on legacy-auth",
            confidence=0.9,
        ),
    ],
)

_NEGATIVE_EVENT = """\
[slack #general] @priya: honestly we should probably move some of this stuff around
at some point, it's getting a bit messy lol. anyway, lunch?"""

_NEGATIVE_EXPECTED = ExtractionResult(entities=[], relationships=[])


FEW_SHOT_EXAMPLES: tuple[tuple[str, ExtractionResult], ...] = (
    (_POSITIVE_EVENT, _POSITIVE_EXPECTED),
    (_NEGATIVE_EVENT, _NEGATIVE_EXPECTED),
)


# ---------------------------------------------------------------------------
# Prompt assembly.
# ---------------------------------------------------------------------------
def _render_example(event_content: str, expected: ExtractionResult) -> str:
    """Render one few-shot pair as an alternating user/assistant transcript fragment."""
    return (
        f"EVENT:\n{event_content}\n\n"
        f"CORRECT OUTPUT:\n{expected.model_dump_json(indent=2)}"
    )


def build_user_prompt(event_content: str) -> str:
    """Assemble the user-turn prompt: schema, worked examples, then the target event.

    The schema and examples are repeated in the user turn (not only the system turn)
    because some OpenRouter-routed models weight the final user message most heavily;
    putting the worked examples adjacent to the task improves adherence on the smaller
    models in the comparison.
    """
    examples = "\n\n---\n\n".join(
        _render_example(content, expected) for content, expected in FEW_SHOT_EXAMPLES
    )
    return (
        f"{SCHEMA_DESCRIPTION}\n\n"
        f"# Worked examples\n\n{examples}\n\n"
        f"---\n\n"
        f"# Now extract from this event\n\n"
        f"Return ONLY the JSON object described above — no prose, no code fences.\n\n"
        f"EVENT:\n{event_content}\n\n"
        f"CORRECT OUTPUT:"
    )


def build_messages(event_content: str) -> list[dict[str, str]]:
    """Return the OpenAI/OpenRouter ``messages`` array for a single event."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(event_content)},
    ]


def prompt_fingerprint() -> str:
    """Stable hash of the prompt *template* (not any single event).

    Identifies which prompt produced a run, for the ``extraction_runs`` audit and the
    eval cache key — so a prompt change invalidates stale cache entries automatically.
    """
    examples = "".join(
        f"{content}{expected.model_dump_json()}" for content, expected in FEW_SHOT_EXAMPLES
    )
    blob = f"{PROMPT_VERSION}\x00{SYSTEM_PROMPT}\x00{SCHEMA_DESCRIPTION}\x00{examples}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
