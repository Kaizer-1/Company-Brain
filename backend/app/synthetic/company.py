"""The locked fictional company: Northwind Payments.

These are *internal generator domain objects*, not API DTOs and not graph nodes —
hence plain frozen dataclasses rather than Pydantic models. They are the single
in-code source of truth for the company defined in
``docs/design/synthetic-company.md``; the generator composes them (together with the
planted cases in ``narrative.py``) into raw ``events`` rows.

Nothing here is random. Counts and identities are asserted by
``backend/tests/synthetic/test_company.py`` to catch accidental scope drift from the
design doc (10–15 people, 4–6 teams, 8–12 services, 4–6 systems, 6–10 decisions).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

# The dataset's fixed "current time". Generation is anchored to this constant rather
# than ``datetime.now()`` so ``generate()`` is a pure function of the seed and stays
# byte-for-byte reproducible (ADR 0011). It matches the project's current date.
REFERENCE_NOW = datetime(2026, 6, 1, tzinfo=UTC)

# Below this age (days before REFERENCE_NOW) Ben Smith authors/approves as ``@ben``;
# at or above it he is still ``@bsmith``. The mid-history handle change is an
# entity-resolution trap (see ``narrative.py`` AliasGroup for ben-smith).
HANDLE_CHANGE_AGE_DAYS = 120

ServiceTier = Literal["critical", "standard", "experimental"]
LifecycleStatus = Literal["active", "deprecated"]
DecisionStatus = Literal["active", "superseded", "rejected"]


@dataclass(frozen=True)
class SyntheticPerson:
    """A person in the company, with the surface forms the generator may render.

    ``canonical_id`` is the eventual entity-resolution merge target. ``nickname``,
    ``former_handle`` and ``title_refs`` are the deliberate alias surface forms; the
    generator picks among them to stress Phase 3B resolution.
    """

    canonical_id: str
    display_name: str
    email: str
    handle: str
    role: str
    team: str | None
    nickname: str | None = None
    former_handle: str | None = None
    title_refs: tuple[str, ...] = ()
    left_company: bool = False

    def handle_at_age(self, age_days: int) -> str:
        """Return the handle this person used ``age_days`` before REFERENCE_NOW.

        Models Ben Smith's mid-history ``@bsmith`` → ``@ben`` change: anyone with a
        ``former_handle`` used it for events older than ``HANDLE_CHANGE_AGE_DAYS``.
        """
        if self.former_handle is not None and age_days >= HANDLE_CHANGE_AGE_DAYS:
            return self.former_handle
        return self.handle

    def mention_forms(self) -> tuple[str, ...]:
        """All non-former-handle surface forms usable to mention this person in text."""
        forms = [self.display_name, self.handle, self.email]
        if self.nickname is not None:
            forms.append(self.nickname)
        forms.extend(self.title_refs)
        return tuple(forms)


@dataclass(frozen=True)
class SyntheticTeam:
    """An engineering team that owns services and contains people."""

    canonical_name: str
    display_name: str
    mission: str
    lead: str  # person canonical_id


@dataclass(frozen=True)
class SyntheticService:
    """A deployed, running software unit.

    ``aliases`` carries abbreviations / descriptive / team-coupled forms; ``former_name``
    is a prior canonical name kept for the rename trap (``legacy-billing`` → ``billing-v2``).
    Ownership is by team unless ``owner_person`` is set (the individual-ownership /
    departure case).
    """

    canonical_name: str
    owning_team: str
    tier: ServiceTier
    description: str
    aliases: tuple[str, ...] = ()
    former_name: str | None = None
    owner_person: str | None = None

    def name_forms(self) -> tuple[str, ...]:
        """Canonical name plus aliases (excludes the former name, used only in old text)."""
        return (self.canonical_name, *self.aliases)


@dataclass(frozen=True)
class SyntheticSystem:
    """A higher-level named asset/platform a decision can deprecate."""

    canonical_name: str
    owning_team: str
    status: LifecycleStatus
    description: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class SyntheticDecision:
    """A decision, dated by age in days before REFERENCE_NOW.

    ``about`` and ``deprecates`` reference system/service canonical names; ``approvers``
    reference person canonical ids. ``formal`` distinguishes a decision-record doc from a
    Slack-originated change. ``supersedes`` carries the textual supersession signal (the
    graph has no SUPERSEDES edge yet — graph-schema.md open question #5).
    """

    id: str
    title: str
    body: str
    status: DecisionStatus
    age_days: int
    approvers: tuple[str, ...]
    formal: bool
    about: tuple[str, ...] = ()
    deprecates: str | None = None
    supersedes: str | None = None


@dataclass(frozen=True)
class SyntheticCompany:
    """The whole fictional company, with lookup helpers used by the generator."""

    name: str
    domain: str
    reference_now: datetime
    people: tuple[SyntheticPerson, ...]
    teams: tuple[SyntheticTeam, ...]
    services: tuple[SyntheticService, ...]
    systems: tuple[SyntheticSystem, ...]
    decisions: tuple[SyntheticDecision, ...]

    def person(self, canonical_id: str) -> SyntheticPerson:
        for p in self.people:
            if p.canonical_id == canonical_id:
                return p
        raise KeyError(canonical_id)

    def team(self, canonical_name: str) -> SyntheticTeam:
        for t in self.teams:
            if t.canonical_name == canonical_name:
                return t
        raise KeyError(canonical_name)

    def service(self, canonical_name: str) -> SyntheticService:
        for s in self.services:
            if s.canonical_name == canonical_name:
                return s
        raise KeyError(canonical_name)

    def system(self, canonical_name: str) -> SyntheticSystem:
        for s in self.systems:
            if s.canonical_name == canonical_name:
                return s
        raise KeyError(canonical_name)

    def decision(self, decision_id: str) -> SyntheticDecision:
        for d in self.decisions:
            if d.id == decision_id:
                return d
        raise KeyError(decision_id)

    def members_of(self, team_canonical_name: str) -> tuple[SyntheticPerson, ...]:
        return tuple(p for p in self.people if p.team == team_canonical_name)


# ---------------------------------------------------------------------------
# The locked definition. Mirrors docs/design/synthetic-company.md exactly.
# ---------------------------------------------------------------------------

_PEOPLE: tuple[SyntheticPerson, ...] = (
    SyntheticPerson(
        "alice-chen", "Alice Chen", "alice.chen@northwind.io", "@alice",
        "Platform Lead", "platform", nickname="Al",
    ),
    SyntheticPerson(
        "hassan-mehta", "Hassan Mehta", "hassan.mehta@northwind.io", "@hassan",
        "Platform Engineer", "platform",
    ),
    SyntheticPerson(
        "diego-ramirez", "Diego Ramirez", "diego.ramirez@northwind.io", "@diego",
        "Payments Lead", "payments",
        title_refs=("the payments lead", "Payments' tech lead"),
    ),
    SyntheticPerson(
        "bob-tanaka", "Bob Tanaka", "bob.tanaka@northwind.io", "@bob",
        "Payments Engineer", "payments", left_company=True,
    ),
    SyntheticPerson(
        "erik-johansson", "Erik Johansson", "erik.johansson@northwind.io", "@erik",
        "Payments Engineer", "payments",
    ),
    SyntheticPerson(
        "iris-petrova", "Iris Petrova", "iris.petrova@northwind.io", "@iris",
        "Staff Engineer", "payments",
    ),
    SyntheticPerson(
        "carol-nwosu", "Carol Nwosu", "carol.nwosu@northwind.io", "@carol",
        "Payments Engineer", "payments",
    ),
    SyntheticPerson(
        "priya-nair", "Priya Nair", "priya.nair@northwind.io", "@priya",
        "Growth Lead", "growth",
    ),
    SyntheticPerson(
        "fatima-al-rashid", "Fatima Al-Rashid", "fatima.alrashid@northwind.io", "@fatima",
        "Growth Engineer", "growth",
    ),
    SyntheticPerson(
        "sam-okafor", "Sam Okafor", "sam.okafor@northwind.io", "@sam",
        "Data Lead", "data",
    ),
    SyntheticPerson(
        "grace-liu", "Grace Liu", "grace.liu@northwind.io", "@grace",
        "Data Engineer", "data",
    ),
    SyntheticPerson(
        "ben-smith", "Ben Smith", "ben.smith@northwind.io", "@ben",
        "SRE Lead", "sre", former_handle="@bsmith",
    ),
    SyntheticPerson(
        "jordan-wells", "Jordan Wells", "jordan.wells@northwind.io", "@jordan",
        "Director of Engineering", None,
    ),
)

_TEAMS: tuple[SyntheticTeam, ...] = (
    SyntheticTeam("platform", "Platform", "Shared auth, data, and infra services", "alice-chen"),
    SyntheticTeam("payments", "Payments", "Core money movement", "diego-ramirez"),
    SyntheticTeam("growth", "Growth", "Merchant-facing surfaces and onboarding", "priya-nair"),
    SyntheticTeam("data", "Data", "Reporting, invoicing, analytics", "sam-okafor"),
    SyntheticTeam("sre", "SRE", "Reliability, deploy, event bus, on-call", "ben-smith"),
)

_SERVICES: tuple[SyntheticService, ...] = (
    SyntheticService(
        "payments-api", "payments", "critical",
        "Core money-movement API; blast-radius seed",
        aliases=("the Payments team's API", "@payments' service", "payments"),
    ),
    SyntheticService(
        "auth-service", "platform", "critical",
        "New authn/authz service replacing legacy-auth",
        aliases=("AuthSvc", "the auth service", "the auth system"),
    ),
    SyntheticService("checkout-service", "payments", "critical", "Hosted checkout"),
    SyntheticService(
        "billing-v2", "payments", "standard",
        "Recurring billing; rewritten from legacy-billing",
        aliases=("the billing service",),
        former_name="legacy-billing", owner_person="carol-nwosu",
    ),
    SyntheticService("payouts-service", "payments", "critical", "Merchant payouts"),
    SyntheticService("subscriptions-service", "growth", "standard", "Subscription plans"),
    SyntheticService(
        "notifications-api", "growth", "standard",
        "Public API that accepts notification requests",
    ),
    SyntheticService(
        "notification-worker", "growth", "standard",
        "Background worker that delivers notifications off event-bus",
    ),
    SyntheticService("web-storefront", "growth", "standard", "Merchant-facing web app"),
    SyntheticService("merchant-dashboard", "data", "standard", "Merchant analytics UI"),
    SyntheticService("invoicing-service", "data", "standard", "Invoice generation"),
    SyntheticService("reporting-api", "data", "standard", "Reporting and exports"),
)

_SYSTEMS: tuple[SyntheticSystem, ...] = (
    SyntheticSystem(
        "legacy-auth", "platform", "deprecated",
        "Original auth system; deprecated by D-0006 but still has live dependents",
        aliases=("the legacy auth system",),
    ),
    SyntheticSystem(
        "core-monolith", "platform", "deprecated",
        "Original 6-year-old monolith, being strangled into services",
        aliases=("the monolith",),
    ),
    SyntheticSystem("primary-db", "platform", "active", "Primary Postgres cluster"),
    SyntheticSystem("event-bus", "sre", "active", "Kafka backbone for async messaging"),
    SyntheticSystem("user-store", "platform", "active", "User-profile datastore behind auth-service"),
)

_DECISIONS: tuple[SyntheticDecision, ...] = (
    SyntheticDecision(
        "D-0001", "Postgres (primary-db) is the system of record",
        "We standardize on primary-db as the canonical store for all transactional data.",
        "active", 360, ("alice-chen",), formal=True, about=("primary-db",),
    ),
    SyntheticDecision(
        "D-0002", "Adopt event-bus (Kafka) for async service communication",
        "All inter-service async messaging moves onto event-bus.",
        "active", 300, ("ben-smith",), formal=True, about=("event-bus",),
    ),
    SyntheticDecision(
        "D-0003", "Strangle the core-monolith; build new features as services",
        "No new feature work lands in core-monolith; we extract services incrementally.",
        "active", 240, ("jordan-wells",), formal=True, about=("core-monolith",),
    ),
    SyntheticDecision(
        "D-0004", "auth-service v1: stateful session model",
        "Launch auth-service with server-side sessions and cut over login traffic.",
        "superseded", 150, ("alice-chen",), formal=True, about=("auth-service",),
    ),
    SyntheticDecision(
        "D-0005", "New payment integrations stay on legacy-auth through year-end",
        "For stability, new payment integrations continue using legacy-auth token "
        "validation until the end of the year.",
        "active", 120, ("diego-ramirez",), formal=True, about=("legacy-auth", "payments-api"),
    ),
    SyntheticDecision(
        "D-0006", "Deprecate legacy-auth; migrate all services to auth-service by Q4",
        "legacy-auth is deprecated. All dependent services must migrate to auth-service "
        "by Q4.",
        "active", 85, ("jordan-wells", "alice-chen"), formal=True,
        about=("legacy-auth", "auth-service"), deprecates="legacy-auth",
    ),
    SyntheticDecision(
        "D-0007", "Enforce mTLS between auth-service and user-store",
        "All traffic between auth-service and user-store must use mutual TLS.",
        "active", 60, ("ben-smith",), formal=False, about=("auth-service",),
    ),
    SyntheticDecision(
        "D-0008", "Rotate auth-service signing keys monthly",
        "auth-service signing keys rotate monthly instead of quarterly.",
        "active", 45, ("hassan-mehta",), formal=False, about=("auth-service",),
    ),
    SyntheticDecision(
        "D-0009", "Standardize async writes on event-bus; no direct primary-db writes",
        "New services publish via event-bus; direct primary-db writes from new services "
        "are prohibited.",
        "active", 30, ("ben-smith",), formal=True, about=("event-bus", "primary-db"),
    ),
    SyntheticDecision(
        "D-0010", "Move auth-service to stateless JWT",
        "auth-service moves to stateless JWT, superseding the D-0004 session model.",
        "active", 25, ("alice-chen", "jordan-wells"), formal=True,
        about=("auth-service",), supersedes="D-0004",
    ),
)

COMPANY = SyntheticCompany(
    name="Northwind Payments",
    domain="northwind.io",
    reference_now=REFERENCE_NOW,
    people=_PEOPLE,
    teams=_TEAMS,
    services=_SERVICES,
    systems=_SYSTEMS,
    decisions=_DECISIONS,
)
