"""Tier 1 deterministic resolution rules (Phase 3A).

Each rule is a pure function returning the rule's name when it fires, or ``None``. A rule
firing is an *exact-identity* signal: shared email, shared handle, a curated known-alias, an
equal canonical name, or a recorded former name. Tier 1 auto-merges on any rule match (ADR
0014), so each rule's docstring names its false-positive risk.

The known-alias dictionary is built from the locked company (``company.py``) plus the alias
inventory (``narrative.ALIAS_GROUPS``), normalised with the same ``normalize`` the Phase 2B
matcher uses. In production this dictionary is an SSO/HR/service-catalog export; here it is
the synthetic narrative that is our single source of truth (named limitation — see the design
doc).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.eval.matcher import normalize
from app.models.enums import NodeType
from app.synthetic import narrative as nv
from app.synthetic.company import COMPANY, SyntheticCompany

if TYPE_CHECKING:
    from app.resolution.models import ResolvableNode


class AliasDictionary:
    """Per-type map from a normalised surface form to a canonical entity key.

    Unlike the matcher's ``SurfaceIndex``, lookup returns ``None`` on a miss (not a
    normalised fallback), so the ``known_alias`` rule only fires on a *real* dictionary hit —
    never on two unknown nodes that happen to normalise to the same token.
    """

    def __init__(self, company: SyntheticCompany = COMPANY) -> None:
        self._by_type: dict[NodeType, dict[str, str]] = {nt: {} for nt in NodeType}
        self._build(company)

    def _add(self, node_type: NodeType, surface: str | None, canonical: str) -> None:
        if not surface:
            return
        token = normalize(surface)
        if token:
            self._by_type[node_type].setdefault(token, canonical)

    def _build(self, company: SyntheticCompany) -> None:
        for p in company.people:
            for form in (
                p.canonical_id, p.display_name, p.handle, p.email,
                p.nickname, p.former_handle, *p.title_refs,
            ):
                self._add(NodeType.Person, form, p.canonical_id)
        for s in company.services:
            for form in (*s.name_forms(), s.former_name):
                self._add(NodeType.Service, form, s.canonical_name)
        for sys_ in company.systems:
            for form in (sys_.canonical_name, *sys_.aliases):
                self._add(NodeType.System, form, sys_.canonical_name)
        for t in company.teams:
            for form in (t.canonical_name, t.display_name):
                self._add(NodeType.Team, form, t.canonical_name)
        for d in company.decisions:
            self._add(NodeType.Decision, d.id, d.id)
            self._add(NodeType.Decision, d.title, d.id)
        # The explicit alias inventory — some forms (e.g. "@payments' service") live only here.
        for group in nv.ALIAS_GROUPS:
            node_type = NodeType.Person if group.entity_kind == "person" else NodeType.Service
            for form in group.surface_forms:
                self._add(node_type, form, group.canonical)

    def canonical(self, node_type: NodeType, surface: str) -> str | None:
        """Canonical key for a surface form of a known type, or None if not in the dict."""
        return self._by_type[node_type].get(normalize(surface))

    def resolve_node(self, node: ResolvableNode) -> str | None:
        """First dictionary hit among a node's identity-bearing surface forms, or None."""
        for surface in _node_surfaces(node):
            hit = self.canonical(node.node_type, surface)
            if hit is not None:
                return hit
        return None


def _node_surfaces(node: ResolvableNode) -> list[str]:
    """The identity-bearing strings a node carries, for alias lookup."""
    surfaces = [node.node_id]
    for key in ("display_name", "handle", "email", "canonical_name", "former_name", "title"):
        value = node.prop_str(key)
        if value:
            surfaces.append(value)
    return surfaces


# ---------------------------------------------------------------------------
# Individual rules. Each returns its name on a match, else None.
# ---------------------------------------------------------------------------
def exact_email(a: ResolvableNode, b: ResolvableNode) -> str | None:
    """Both Person nodes carry the same email.

    FP risk: ~zero — a corporate email is a unique identifier. The only failure mode is a
    shared role mailbox, which Northwind does not model.
    """
    ea, eb = a.prop_str("email"), b.prop_str("email")
    if ea and eb and ea.strip().lower() == eb.strip().lower():
        return "exact_email"
    return None


def exact_handle(a: ResolvableNode, b: ResolvableNode) -> str | None:
    """Both Person nodes carry the same handle (``@alice``).

    FP risk: very low within one org — handles are unique. Cross-org reuse is out of scope
    (single tenant).
    """
    ha, hb = a.prop_str("handle"), b.prop_str("handle")
    if ha and hb and normalize(ha) == normalize(hb):
        return "exact_handle"
    return None


def exact_canonical_name(a: ResolvableNode, b: ResolvableNode) -> str | None:
    """Both nodes' canonical names are equal after normalisation (case/punctuation-folded).

    FP risk: near zero. Post-MERGE the graph rarely holds two byte-identical names, so this
    rule mostly catches case/whitespace variants of the same Service/System/Team name.
    """
    name_a = a.prop_str("canonical_name") or a.node_id
    name_b = b.prop_str("canonical_name") or b.node_id
    if normalize(name_a) == normalize(name_b):
        return "exact_canonical_name"
    return None


def known_alias(a: ResolvableNode, b: ResolvableNode, alias_dict: AliasDictionary) -> str | None:
    """Both nodes' surface forms resolve, via the curated dictionary, to the same entity.

    FP risk: only as good as the dictionary — a wrong entry is a wrong merge. The dictionary
    is curated from the company definition + ALIAS_GROUPS (see class docstring).
    """
    canon_a = alias_dict.resolve_node(a)
    canon_b = alias_dict.resolve_node(b)
    if canon_a is not None and canon_a == canon_b:
        return "known_alias"
    return None


def former_name(a: ResolvableNode, b: ResolvableNode) -> str | None:
    """One Service/System node's canonical name equals the other's recorded former name.

    FP risk: low — former names are explicit in the company definition. The hazard is a name
    genuinely reused for a different service, which the look-alike negative case guards
    against.
    """
    for x, y in ((a, b), (b, a)):
        former = y.prop_str("former_name")
        name_x = x.prop_str("canonical_name") or x.node_id
        if former and normalize(former) == normalize(name_x):
            return "former_name"
    return None


def apply_tier1_rules(
    a: ResolvableNode, b: ResolvableNode, alias_dict: AliasDictionary
) -> list[str]:
    """Run the type-appropriate Tier 1 rules, returning every rule that fired (possibly none).

    Person → email / handle / known_alias. Service|System → canonical_name / known_alias /
    former_name. Team / Decision → canonical_name / known_alias.
    """
    matched: list[str] = []
    node_type = a.node_type

    if node_type == NodeType.Person:
        checks = (exact_email(a, b), exact_handle(a, b), known_alias(a, b, alias_dict))
    elif node_type in (NodeType.Service, NodeType.System):
        checks = (exact_canonical_name(a, b), known_alias(a, b, alias_dict), former_name(a, b))
    else:  # Team, Decision
        checks = (exact_canonical_name(a, b), known_alias(a, b, alias_dict), None)

    for result in checks:
        if result is not None:
            matched.append(result)
    return matched
