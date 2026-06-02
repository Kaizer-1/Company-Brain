"""Tier 1 deterministic rules — pure functions, fast to exhaust with positive/negative cases."""

from __future__ import annotations

from app.models.enums import NodeType
from app.resolution.models import ResolvableNode
from app.resolution.rules import (
    AliasDictionary,
    apply_tier1_rules,
    exact_canonical_name,
    exact_email,
    exact_handle,
    former_name,
    known_alias,
)

ALIASES = AliasDictionary()


def person(node_id: str, **props: object) -> ResolvableNode:
    return ResolvableNode(node_type=NodeType.Person, node_id=node_id, properties=props)


def service(node_id: str, **props: object) -> ResolvableNode:
    return ResolvableNode(node_type=NodeType.Service, node_id=node_id, properties=props)


def test_exact_email_matches_case_insensitively() -> None:
    a = person("a", email="Alice.Chen@Northwind.io")
    b = person("b", email="alice.chen@northwind.io")
    assert exact_email(a, b) == "exact_email"


def test_exact_email_none_when_missing_or_different() -> None:
    assert exact_email(person("a", email="x@y.io"), person("b")) is None
    assert exact_email(person("a", email="x@y.io"), person("b", email="z@y.io")) is None


def test_exact_handle_normalised() -> None:
    assert exact_handle(person("a", handle="@Alice"), person("b", handle="@alice")) == "exact_handle"
    assert exact_handle(person("a", handle="@alice"), person("b", handle="@ben")) is None


def test_exact_canonical_name_folds_case_and_punctuation() -> None:
    assert exact_canonical_name(service("Auth-Service"), service("auth service")) == "exact_canonical_name"
    assert exact_canonical_name(service("auth-service"), service("payments-api")) is None


def test_known_alias_collapses_person_surface_forms() -> None:
    # All four Alice forms (as graph node-id slugs) resolve to alice-chen.
    assert known_alias(person("alice-chen"), person("al"), ALIASES) == "known_alias"
    assert known_alias(person("alice"), person("alice-chen-northwind-io"), ALIASES) == "known_alias"


def test_known_alias_does_not_merge_across_entities() -> None:
    assert known_alias(person("alice-chen"), person("ben"), ALIASES) is None


def test_known_alias_does_not_merge_look_alike_services() -> None:
    # The look-alike pair must NOT merge — different canonicals.
    assert known_alias(service("notifications-api"), service("notification-worker"), ALIASES) is None


def test_known_alias_service_abbreviation() -> None:
    assert known_alias(service("auth-service"), service("authsvc"), ALIASES) == "known_alias"


def test_former_name_rule() -> None:
    # legacy-billing was renamed to billing-v2; a node holding the former name as a property
    # merges into the canonical.
    a = service("billing-v2", former_name="legacy-billing")
    b = service("legacy-billing")
    assert former_name(a, b) == "former_name"
    assert former_name(service("billing-v2"), service("payments-api")) is None


def test_apply_tier1_rules_person_uses_alias() -> None:
    assert apply_tier1_rules(person("alice-chen"), person("al"), ALIASES) == ["known_alias"]


def test_apply_tier1_rules_unrelated_is_empty() -> None:
    assert apply_tier1_rules(person("alice-chen"), person("ben"), ALIASES) == []
    assert apply_tier1_rules(
        service("notifications-api"), service("notification-worker"), ALIASES
    ) == []
