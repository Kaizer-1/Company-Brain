"""Pydantic v2 models for the Company Brain graph.

These are the *Python-side* representation of the graph schema locked in Phase
1B (see docs/design/graph-schema.md). The extraction pipeline (Phase 2D/2E)
produces these models; the write path translates them into Cypher ``MERGE``
statements. They are intentionally decoupled from the Cypher migrations: the
migration runner creates constraints/indexes and has no business knowing about
extraction-time models, and the models have no business knowing how the graph
is provisioned. ADR 0007 captures the high-level schema decisions.

Schema discipline from day one: every model is ``frozen`` (immutable after
construction — a node/edge is a fact, not a mutable record) and
``extra="forbid"`` (an unexpected field is a bug in the extractor, surfaced
loudly rather than silently dropped).
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Shared model configuration: immutable + reject unknown fields.
_STRICT = ConfigDict(frozen=True, extra="forbid")


class Node(BaseModel):
    """Base for every graph node.

    Carries the three things every node has regardless of label:

    - ``id``: the stable graph identity. For name-keyed nodes (Service, System,
      Team, Person) it mirrors the canonical key; for Decision/Message it *is*
      the canonical key. The generic write path and provenance code treat every
      node uniformly via ``.id``.
    - ``source_event_ids``: provenance — foreign keys into the Postgres
      ``events`` ingest log (provenance is property-based, not a graph node;
      see docs/design/graph-schema.md "Provenance Model"). Required: a node with
      no source event has no business being in the graph.
    - ``created_at``: the node's primary timestamp (first-observed / event time).
    """

    model_config = _STRICT

    id: str
    source_event_ids: list[str]
    created_at: datetime


class _NameKeyedNode(Node):
    """Shared structure for nodes whose canonical key is a human-readable name.

    Not a node label itself — Service, System, and Team extend it. The graph
    uniqueness constraint is on ``canonical_name``; ``id`` mirrors it so callers
    may supply only the name and still get a populated ``id``.
    """

    canonical_name: str

    @model_validator(mode="before")
    @classmethod
    def _mirror_id_from_name(cls, data: Any) -> Any:  # noqa: ANN401 - raw pre-validation input is arbitrary
        if isinstance(data, dict) and data.get("id") is None:
            name = data.get("canonical_name")
            if name is not None:
                return {**data, "id": name}
        return data


class Service(_NameKeyedNode):
    """A deployed, running software unit with owners and runtime dependencies.

    The operational atom of the architecture (e.g. ``payments-api``). Motivated
    by KQ1 (the owned, dependent service), KQ3 (blast-radius seed and
    dependents), and KQ4 (a decision can be *about* a service).
    """

    language: str | None = None
    tier: Literal["critical", "standard", "experimental"] | None = None
    status: Literal["active", "deprecated"] = "active"


class System(_NameKeyedNode):
    """A higher-level named asset or platform that a decision can deprecate.

    The thing architecture decisions act on (e.g. ``legacy-auth``). Distinct
    from Service by design (see docs/design/graph-schema.md "The Service vs.
    System Question"). Motivated by KQ1 (the deprecated system at the head of
    the ownership chain) and KQ4 (the system whose change history we rebuild).
    """

    status: Literal["active", "deprecated"] = "active"
    description: str | None = None


class Team(_NameKeyedNode):
    """An engineering team that can own services and contain people.

    Motivated by KQ1 (an owner may be a Team, not only a Person) and KQ3 (a
    team-owned affected service expands to its members via MEMBER_OF).
    """

    display_name: str | None = None


class Person(Node):
    """An individual: engineer, approver, author, or stakeholder.

    Motivated by KQ1 (the owner), KQ3 (affected people), KQ4 (the approver).
    Identity caveat: one human appears as ``@alice``, ``Alice Chen``,
    ``alice@company.com``; reconciling these is Phase 3 entity resolution, not
    now. ``canonical_id`` is the eventual merge target.
    """

    canonical_id: str
    display_name: str
    email: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _mirror_id_from_canonical(cls, data: Any) -> Any:  # noqa: ANN401 - raw pre-validation input is arbitrary
        if isinstance(data, dict) and data.get("id") is None:
            canonical_id = data.get("canonical_id")
            if canonical_id is not None:
                return {**data, "id": canonical_id}
        return data


class Decision(Node):
    """A choice that was made, with provenance and temporal validity.

    An ADR or a decision captured in a meeting note. The temporal heart of the
    schema: a Decision is *a choice made*; a System is *a thing that exists*;
    the DEPRECATES edge links them. ``status``/``valid_from``/``valid_to`` make
    "currently active" and time-window queries expressible as simple filters.
    Motivated by KQ1 (the seed Decision X), KQ2 (the contradicted active
    decisions), and KQ4 (the changes with approvers).
    """

    title: str
    status: Literal["active", "superseded", "rejected"]
    valid_from: datetime
    valid_to: datetime | None = None
    body: str | None = None


class Message(Node):
    """A Slack-style message — an atom of discussion.

    Carries the discussion corpus KQ2 compares against the decision corpus.
    Keyed by ``source_id:external_id`` so re-ingesting the same export is
    idempotent (``id`` is composed from those two if not supplied). ``created_at``
    is the message send time, the temporal axis KQ2 filters on. Motivated by KQ2
    (recent discussions that contradict decisions) and KQ4 (discussion context).
    """

    source_id: str
    external_id: str
    content: str

    @model_validator(mode="before")
    @classmethod
    def _compose_id(cls, data: Any) -> Any:  # noqa: ANN401 - raw pre-validation input is arbitrary
        if isinstance(data, dict) and data.get("id") is None:
            source_id = data.get("source_id")
            external_id = data.get("external_id")
            if source_id is not None and external_id is not None:
                return {**data, "id": f"{source_id}:{external_id}"}
        return data


class RelationshipType(StrEnum):
    """The closed set of relationship types in the v1 schema.

    Using a ``StrEnum`` instead of a bare ``str`` enforces the closed vocabulary
    at construction time: an unknown edge type raises ``ValidationError`` rather
    than silently entering the graph, while ``str(member)`` still yields the
    wire value (e.g. ``"DEPENDS_ON"``) for Cypher generation in Phase 2E. Each
    member is justified by a killer query in docs/design/graph-schema.md.
    """

    DEPENDS_ON = "DEPENDS_ON"
    OWNED_BY = "OWNED_BY"
    MEMBER_OF = "MEMBER_OF"
    DEPRECATES = "DEPRECATES"
    ABOUT = "ABOUT"
    APPROVED_BY = "APPROVED_BY"
    AUTHORED = "AUTHORED"
    MENTIONS = "MENTIONS"
    CONTRADICTS = "CONTRADICTS"


class Relationship(BaseModel):
    """A directed, typed edge produced by extraction.

    Every edge carries its extraction metadata, because the uncertain thing an
    LLM produces is the *assertion of a relationship*, not the existence of an
    entity (see docs/design/graph-schema.md "Confidence and Extraction
    Metadata"):

    - ``confidence`` in [0, 1]: the extractor's confidence in *this* edge,
      enabling a precision/recall threshold at query time.
    - ``extracted_by``: model name + version, so edges from a model later found
      unreliable can be re-evaluated or purged.
    - ``properties``: edge-specific extras such as ``deprecated_at`` on a lapsed
      DEPENDS_ON/OWNED_BY/MEMBER_OF edge.
    """

    model_config = _STRICT

    type: RelationshipType
    source_id: str
    target_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    extracted_by: str
    created_at: datetime
    # Edge properties are heterogeneous JSON scalars; ``object`` avoids ``Any``
    # while accepting any value Pydantic round-trips.
    properties: dict[str, object] | None = None
