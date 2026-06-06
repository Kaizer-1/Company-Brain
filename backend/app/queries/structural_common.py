"""Shared helpers for the Phase 4C structural query tools.

The structural tools (``get_entity``, ``neighbors``, ``enumerate_by_type``,
``aggregate_by_type``) all operate over the same heterogeneous node identity model that the
extracted graph actually uses, so the identity-matching predicate, the uniform display-name
expression, the closed type/status enums, and the neo4j→JSON value coercion live here once.

Identity in the real graph is per-label (verified against the live schema, not assumed):

* ``Person``  → ``canonical_id`` (e.g. ``diego-ramirez``); also addressable by ``handle``.
* ``Service`` / ``System`` / ``Team`` → ``canonical_name``.
* ``Decision`` → ``id`` (e.g. ``D-0006``), displayed via ``title``.
* ``Message``  → ``id``.

So a single ``canonical_id``-only match (as an earlier spec draft assumed) would only ever
match Person nodes. ``IDENTITY_MATCH`` matches on any of the identity fields plus ``handle``.
"""

from __future__ import annotations

from typing import Any, Literal

# The closed set of queryable node labels (CLAUDE.md graph schema; _Migration excluded).
NodeTypeLiteral = Literal["Person", "Team", "Service", "System", "Decision", "Message"]
NODE_TYPES: frozenset[str] = frozenset(
    {"Person", "Team", "Service", "System", "Decision", "Message"}
)

# Lifecycle filter modes shared by enumerate + aggregate. See ADR 0028 for the semantics of
# each (active excludes deprecated/superseded/merged; deprecated is the ended-not-merged set;
# all is everything except resolution losers).
StatusLiteral = Literal["active", "deprecated", "all"]


def node_display_name(var: str) -> str:
    """Cypher expression giving a uniform display name for node variable ``var``.

    Coalesces across the heterogeneous identity fields so every node type yields *something*
    human-readable: canonical_name (Service/System/Team) → canonical_id (Person) → title
    (Decision) → id (Message, fallback).
    """
    return (
        f"coalesce({var}.canonical_name, {var}.canonical_id, {var}.title, {var}.id)"
    )


def status_predicate(var: str, param: str = "status_mode") -> str:
    """Cypher WHERE fragment for the lifecycle filter on node ``var``, driven by ``$param``.

    ``$status_mode`` is a bound parameter (one of ``active`` / ``deprecated`` / ``all``), so
    nothing is interpolated except the variable name. Semantics (ADR 0028): ``active``
    excludes merged + deprecated + superseded; ``deprecated`` is the ended-but-not-merged set;
    ``all`` is everything except resolution losers (merged). Defined on ``coalesce`` status
    because Person/Team carry no status property and Service has a stray ``deployed`` value.
    """
    return (
        f"coalesce({var}.status, 'active') <> 'merged' "
        f"AND ("
        f"${param} = 'all' "
        f"OR (${param} = 'active' AND NOT coalesce({var}.status, 'active') IN ['deprecated', 'superseded']) "
        f"OR (${param} = 'deprecated' AND coalesce({var}.status, 'active') IN ['deprecated', 'superseded'])"
        f")"
    )


def identity_predicate(var: str, param: str) -> str:
    """Cypher WHERE fragment matching node ``var`` against the bound id parameter ``param``.

    Matches across every identity field (and ``handle``, so ``@diego`` resolves) because the
    caller does not know the node's label up front. Comparison is **case-insensitive**: team
    canonical_names are capitalised (``Payments``) while services and person ids are lower
    (``payments-api``, ``diego-ramirez``), and the router/user cannot be relied on to match
    case exactly. ``toLower`` of a null property is null, which compares false — safe.
    """
    return (
        f"(toLower({var}.canonical_id) = toLower(${param}) "
        f"OR toLower({var}.canonical_name) = toLower(${param}) "
        f"OR toLower({var}.id) = toLower(${param}) "
        f"OR toLower({var}.handle) = toLower(${param}))"
    )


def jsonable_props(props: dict[str, Any]) -> dict[str, Any]:
    """Coerce a neo4j property map into JSON-serialisable values.

    neo4j temporal types (DateTime/Date/Time) carry an ``iso_format`` method; everything that
    is not a JSON primitive (or list/dict thereof) is stringified so the result models survive
    ``model_dump(mode="json")``.
    """
    return {k: _jsonable(v) for k, v in props.items()}


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    iso = getattr(value, "iso_format", None)
    if callable(iso):
        return iso()
    return str(value)
