"""Alias-tolerant matching between extracted output and ground truth.

Entity resolution is Phase 3B, not now — so the extractor legitimately emits
``auth-service``, ``AuthSvc``, and ``the auth service`` as three different surface forms.
This module canonicalises both the extracted output and (implicitly) the ground truth to
the same key space, so a match is counted whenever the surface forms refer to the same
real entity. Phase 3B will do this merging *upstream* in the graph, at which point the
matcher's alias tolerance becomes redundant — that is the intended trajectory, and it is
named here as a deliberate temporary measure, not a hidden hack.

Two canonicalisation paths:

- **Entities** are type-scoped: a Person named ``payments`` and a Team named ``Payments``
  live in different namespaces, so the bare token ``payments`` resolves differently per
  type (Person->none, Team->the team, Service->payments-api alias). This avoids the one
  genuine surface-form collision in the corpus.
- **Relationship endpoints** carry no type in the LLM's output, so they are resolved
  using the *schema-implied* candidate types of each edge (e.g. an ``OWNED_BY`` target is
  a Person or a Team), trying those namespaces in order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.schemas.graph import RelationshipType
from app.synthetic import narrative as nv
from app.synthetic.company import COMPANY, SyntheticCompany

if TYPE_CHECKING:
    from app.extraction.models import EntityType, ExtractionResult

# Schema-implied candidate node types for each edge's (source, target), in resolution
# precedence order. Mirrors the relationship table in docs/design/graph-schema.md.
ENDPOINT_TYPES: dict[RelationshipType, tuple[tuple[EntityType, ...], tuple[EntityType, ...]]] = {
    RelationshipType.DEPENDS_ON: (("Service",), ("Service", "System")),
    RelationshipType.OWNED_BY: (("Service", "System"), ("Person", "Team")),
    RelationshipType.MEMBER_OF: (("Person",), ("Team",)),
    RelationshipType.DEPRECATES: (("Decision",), ("System",)),
    RelationshipType.ABOUT: (("Decision",), ("System", "Service")),
    RelationshipType.APPROVED_BY: (("Decision",), ("Person",)),
    # Message-anchored edges are out of eval scope (ADR 0013), but resolve sensibly if seen.
    RelationshipType.AUTHORED: (("Person",), ("Decision",)),
    RelationshipType.MENTIONS: (("Person",), ("Service", "System", "Team", "Decision", "Person")),
    RelationshipType.CONTRADICTS: (("Person",), ("Decision",)),
}


def normalize(name: str) -> str:
    """Lowercase, drop a leading ``@``, collapse non-alphanumerics to single hyphens.

    ``"@alice"`` -> ``"alice"``, ``"Alice Chen"`` -> ``"alice-chen"``,
    ``"the auth service"`` -> ``"the-auth-service"``. This makes a display name normalise
    to the same token as the company's canonical_id where they agree (``Alice Chen`` ->
    ``alice-chen``), so most matches need no alias table at all.
    """
    cleaned = name.strip().lower().lstrip("@")
    return re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")


class SurfaceIndex:
    """Per-type maps from a normalised surface form to a canonical key.

    Built from the locked company (``company.py``) plus the explicit alias inventory
    (``narrative.ALIAS_GROUPS``). Lookup falls back to the normalised form itself, so an
    unknown name canonicalises to a stable token that simply will not match ground truth
    (i.e. it is correctly counted as spurious).
    """

    def __init__(self, company: SyntheticCompany = COMPANY) -> None:
        self._by_type: dict[EntityType, dict[str, str]] = {
            "Person": {},
            "Service": {},
            "System": {},
            "Team": {},
            "Decision": {},
        }
        self._build(company)

    def _add(self, etype: EntityType, surface: str, key: str) -> None:
        token = normalize(surface)
        if token:
            self._by_type[etype].setdefault(token, key)

    def _build(self, company: SyntheticCompany) -> None:
        for p in company.people:
            for form in (p.display_name, p.handle, p.email, p.nickname, p.former_handle, *p.title_refs):
                if form:
                    self._add("Person", form, p.canonical_id)
        for s in company.services:
            for form in s.name_forms():
                self._add("Service", form, s.canonical_name)
            if s.former_name:
                self._add("Service", s.former_name, s.canonical_name)
        for sys_ in company.systems:
            for form in (sys_.canonical_name, *sys_.aliases):
                self._add("System", form, sys_.canonical_name)
        for t in company.teams:
            for form in (t.canonical_name, t.display_name):
                self._add("Team", form, t.canonical_name)
        for d in company.decisions:
            self._add("Decision", d.id, d.id)
            self._add("Decision", d.title, d.id)
        # Fold in the explicit alias inventory (some forms — e.g. "@payments' service" —
        # exist only here, not on the company dataclasses).
        for group in nv.ALIAS_GROUPS:
            etype: EntityType = "Person" if group.entity_kind == "person" else "Service"
            for form in group.surface_forms:
                self._add(etype, form, group.canonical)

    def entity_key(self, etype: EntityType, name: str) -> str:
        """Canonical key for an entity of a known type."""
        return self._by_type[etype].get(normalize(name), normalize(name))

    def endpoint_key(self, name: str, candidate_types: tuple[EntityType, ...]) -> str:
        """Canonical key for a relationship endpoint of unknown type.

        Tries each candidate namespace in order (schema-implied precedence). Falls back to
        the normalised form so an unresolved endpoint is stable but unmatchable.
        """
        token = normalize(name)
        for etype in candidate_types:
            if token in self._by_type[etype]:
                return self._by_type[etype][token]
        return token


@dataclass(frozen=True)
class EntityMention:
    """One extracted entity, canonicalised, with provenance for failure-mode examples."""

    type: EntityType
    canonical_key: str
    raw_name: str
    confidence: float
    evidence_quote: str
    event_id: str


@dataclass(frozen=True)
class RelationshipMention:
    """One extracted relationship, canonicalised, with provenance."""

    type: RelationshipType
    source_key: str
    target_key: str
    raw_source: str
    raw_target: str
    confidence: float
    evidence_quote: str
    event_id: str


@dataclass(frozen=True)
class MatchedExtraction:
    """The full corpus extraction, canonicalised. Sets drive metrics; mentions drive examples."""

    entity_mentions: tuple[EntityMention, ...]
    relationship_mentions: tuple[RelationshipMention, ...]

    @property
    def entity_keys(self) -> frozenset[tuple[EntityType, str]]:
        return frozenset((m.type, m.canonical_key) for m in self.entity_mentions)

    @property
    def relationship_keys(self) -> frozenset[tuple[RelationshipType, str, str]]:
        return frozenset(
            (m.type, m.source_key, m.target_key) for m in self.relationship_mentions
        )


def canonicalize_extractions(
    items: list[tuple[str, ExtractionResult]],
    index: SurfaceIndex | None = None,
) -> MatchedExtraction:
    """Canonicalise every extraction from ``(event_id, result)`` pairs.

    Returns a ``MatchedExtraction`` whose ``*_keys`` sets are alias-collapsed (ready for
    set-arithmetic metrics) and whose ``*_mentions`` retain raw surface forms, evidence
    quotes, confidences, and event ids (for the failure-mode report).
    """
    idx = index or SurfaceIndex()
    entity_mentions: list[EntityMention] = []
    relationship_mentions: list[RelationshipMention] = []

    for event_id, result in items:
        for ent in result.entities:
            entity_mentions.append(
                EntityMention(
                    type=ent.type,
                    canonical_key=idx.entity_key(ent.type, ent.canonical_name),
                    raw_name=ent.canonical_name,
                    confidence=ent.confidence,
                    evidence_quote=ent.evidence_quote,
                    event_id=event_id,
                )
            )
        for rel in result.relationships:
            src_types, tgt_types = ENDPOINT_TYPES.get(rel.type, ((), ()))
            relationship_mentions.append(
                RelationshipMention(
                    type=rel.type,
                    source_key=idx.endpoint_key(rel.source_canonical_name, src_types),
                    target_key=idx.endpoint_key(rel.target_canonical_name, tgt_types),
                    raw_source=rel.source_canonical_name,
                    raw_target=rel.target_canonical_name,
                    confidence=rel.confidence,
                    evidence_quote=rel.evidence_quote,
                    event_id=event_id,
                )
            )

    return MatchedExtraction(
        entity_mentions=tuple(entity_mentions),
        relationship_mentions=tuple(relationship_mentions),
    )
