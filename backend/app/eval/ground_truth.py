"""Derive extraction ground truth from the synthetic company — the single source of truth.

There is deliberately **no hand-labelled JSON file** (ADR 0013). The corpus is generated
from ``company.py`` + ``narrative.py``; deriving the expected entities/edges from those
same dataclasses means the gold set cannot drift from the data, and regenerating the
corpus regenerates the truth for free. The named cost: the eval is only as good as
``narrative.py`` — which is acceptable precisely because that is the dataset we control.

Inclusion rule (documented and testable):

- **Entity** ``X`` is expected iff ``X`` is defined in ``company.py`` AND at least one of
  its surface forms appears in the generated corpus text. (In practice every company
  entity is mentioned, but the rule is enforced, not assumed — an entity named *only* by,
  say, an email that never appears would be excluded, because the model cannot know it.)
- **Relationship** ``R`` is expected iff the corpus *asserts* it. We include exactly the
  structural edges the generator plants in text: ``DEPENDS_ON`` (the dependency map),
  ``OWNED_BY`` (the service catalog's owner column), ``MEMBER_OF`` (the org chart),
  ``DEPRECATES``/``ABOUT``/``APPROVED_BY`` (the decision records). ``System`` ownership is
  **excluded** because no event states it (only services have a catalog owner), and the
  ``Message``-anchored edges (``AUTHORED``/``MENTIONS``/``CONTRADICTS``) are out of scope
  for this eval — ``Message`` nodes are created mechanically from events, not extracted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.schemas.graph import RelationshipType
from app.synthetic import narrative as nv
from app.synthetic.company import COMPANY, SyntheticCompany, SyntheticPerson
from app.synthetic.generator import SyntheticDataGenerator

if TYPE_CHECKING:
    from app.extraction.models import EntityType


@dataclass(frozen=True)
class ExpectedEntity:
    """A ``(type, canonical_key)`` the corpus should let an extractor recover."""

    type: EntityType
    canonical_name: str  # the canonical KEY (canonical_id for Person, id for Decision)


@dataclass(frozen=True)
class ExpectedRelationship:
    """A ``(type, source_key, target_key)`` edge the corpus asserts."""

    type: RelationshipType
    source_canonical_name: str
    target_canonical_name: str


@dataclass(frozen=True)
class GroundTruth:
    """The complete expected extraction, in canonical-key space."""

    entities: frozenset[ExpectedEntity]
    relationships: frozenset[ExpectedRelationship]


def _corpus_text(company: SyntheticCompany) -> str:
    """Concatenate the generated corpus into one lowercased blob for the inclusion rule."""
    events = SyntheticDataGenerator(seed=42, company=company).generate()
    return "\n".join(e.content for e in events).lower()


def _person_surface_forms(p: SyntheticPerson) -> tuple[str, ...]:
    forms = [p.display_name, p.handle, p.email]
    if p.nickname:
        forms.append(p.nickname)
    if p.former_handle:
        forms.append(p.former_handle)
    forms.extend(p.title_refs)
    return tuple(forms)


def build_ground_truth(company: SyntheticCompany = COMPANY) -> GroundTruth:
    """Build the gold set of entities and relationships from the locked company.

    Pure function of ``company`` (and the deterministic generator). Returns frozensets so
    the result is hashable and trivially comparable in tests.
    """
    corpus = _corpus_text(company)

    def mentioned(forms: tuple[str, ...]) -> bool:
        return any(form and form.lower() in corpus for form in forms)

    entities: set[ExpectedEntity] = set()

    for p in company.people:
        if mentioned(_person_surface_forms(p)):
            entities.add(ExpectedEntity("Person", p.canonical_id))
    for s in company.services:
        forms = (*s.name_forms(), s.former_name or "")
        if mentioned(forms):
            entities.add(ExpectedEntity("Service", s.canonical_name))
    for sys_ in company.systems:
        if mentioned((sys_.canonical_name, *sys_.aliases)):
            entities.add(ExpectedEntity("System", sys_.canonical_name))
    for t in company.teams:
        if mentioned((t.canonical_name, t.display_name)):
            entities.add(ExpectedEntity("Team", t.canonical_name))
    for d in company.decisions:
        if mentioned((d.id, d.title)):
            entities.add(ExpectedEntity("Decision", d.id))

    relationships: set[ExpectedRelationship] = set()

    # DEPENDS_ON — every planted dependency edge (asserted in the dependency map doc).
    for edge in nv.DEPENDENCY_GRAPH.edges:
        relationships.add(
            ExpectedRelationship(RelationshipType.DEPENDS_ON, edge.upstream, edge.downstream)
        )

    # OWNED_BY — services only (the catalog states service ownership; systems' is unstated).
    for s in company.services:
        relationships.add(
            ExpectedRelationship(RelationshipType.OWNED_BY, s.canonical_name, s.owning_team)
        )
        if s.owner_person:
            relationships.add(
                ExpectedRelationship(RelationshipType.OWNED_BY, s.canonical_name, s.owner_person)
            )

    # MEMBER_OF — every person with a team (the org chart lists each under their team).
    for p in company.people:
        if p.team:
            relationships.add(
                ExpectedRelationship(RelationshipType.MEMBER_OF, p.canonical_id, p.team)
            )

    # DEPRECATES / ABOUT / APPROVED_BY — from each decision record.
    for d in company.decisions:
        if d.deprecates:
            relationships.add(
                ExpectedRelationship(RelationshipType.DEPRECATES, d.id, d.deprecates)
            )
        for subject in d.about:
            relationships.add(ExpectedRelationship(RelationshipType.ABOUT, d.id, subject))
        for approver in d.approvers:
            relationships.add(
                ExpectedRelationship(RelationshipType.APPROVED_BY, d.id, approver)
            )

    return GroundTruth(
        entities=frozenset(entities),
        relationships=frozenset(relationships),
    )
