"""The deterministic synthetic-event generator.

Composes the locked company (``company.py``) and planted cases (``narrative.py``) into
varied raw ``events`` rows, using the phrasings in ``templates.py``. Output is a pure
function of the seed: a single ``random.Random(seed)`` is threaded through everything
(no global ``random``), the dataset's "now" is the fixed ``REFERENCE_NOW`` constant, and
all iteration is over ordered tuples — so ``generate()`` is byte-for-byte reproducible
(ADR 0011). The graph stays empty; only Postgres ``events`` are produced (Phase 2B
extracts the graph).
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.models.enums import SourceType
from app.schemas.postgres import EventCreate
from app.synthetic import narrative as nv
from app.synthetic.company import COMPANY, SyntheticCompany, SyntheticPerson
from app.synthetic.templates import (
    ALIAS_PERSON_TEMPLATES,
    ALIAS_SERVICE_TEMPLATES,
    AMBIENT_TEMPLATES,
    CHANGE_DISCUSSION_TEMPLATES,
    CONTRADICTION_TEMPLATES,
    DEPARTURE_TEMPLATES,
    DEPENDENCY_TEMPLATES,
    DEPRECATION_TEMPLATES,
    HANDLE_CHANGE_TEMPLATES,
    LOOKALIKE_TEMPLATES,
    Template,
    arch_overview,
    decision_record,
    org_chart,
    service_catalog,
    stale_wiki,
    wiki_page,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

# Number of ambient (non-planted but entity-grounded) messages. Fixed, not random,
# so the total message count is deterministic and stays within [80, 150].
AMBIENT_COUNT = 26

_ARROW = next(t for t in DEPENDENCY_TEMPLATES if t.id == "dep_arrow")
_DEP_SLACK = tuple(t for t in DEPENDENCY_TEMPLATES if t.id != "dep_arrow")


@dataclass(frozen=True)
class _Channel:
    name: str
    channel_id: str


_TEAM_CHANNELS: dict[str, _Channel] = {
    "platform": _Channel("#platform", "C_PLATFORM"),
    "payments": _Channel("#payments", "C_PAYMENTS"),
    "growth": _Channel("#growth", "C_GROWTH"),
    "data": _Channel("#data", "C_DATA"),
    "sre": _Channel("#sre", "C_SRE"),
}
_ARCH = _Channel("#architecture", "C_ARCH")
_AUTHMIG = _Channel("#auth-migration", "C_AUTHMIG")
_GENERAL = _Channel("#general", "C_GEN")


class SyntheticDataGenerator:
    """Builds the synthetic corpus as a list of ``EventCreate`` DTOs.

    ``generate()`` is deterministic: calling it repeatedly (on the same or a fresh
    instance with the same seed) yields byte-identical events.
    """

    def __init__(
        self,
        seed: int = 42,
        company: SyntheticCompany = COMPANY,
        now: datetime | None = None,
    ) -> None:
        self._seed = seed
        self._company = company
        self._now = now if now is not None else company.reference_now
        self._rng = random.Random(seed)
        self._slack_seq = 0

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def generate(self) -> list[EventCreate]:
        """Produce the full corpus. Resets RNG state so repeat calls are identical."""
        self._rng = random.Random(self._seed)
        self._slack_seq = 0

        events: list[EventCreate] = []
        events += self._emit_decision_docs()
        events += self._emit_arch_docs()
        events += self._emit_wiki_docs()
        events += self._emit_stale_docs()
        events += self._emit_dependency_messages()
        events += self._emit_deprecation_messages()
        events += self._emit_contradiction_thread()
        events += self._emit_change_timeline_messages()
        events += self._emit_alias_messages()
        events += self._emit_lookalike_messages()
        events += self._emit_ownership_ambiguity_messages()
        events += self._emit_departure_messages()
        events += self._emit_handle_change_bridge()
        events += self._emit_ambient_messages()
        return events

    # ------------------------------------------------------------------
    # Low-level builders
    # ------------------------------------------------------------------
    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _created_at(self, age_days: float) -> datetime:
        # Deterministic intra-day jitter keeps created_at values distinct without
        # disturbing the multi-day ordering the planted cases rely on.
        jitter = self._rng.randint(0, 86_399)
        return self._now - timedelta(days=age_days, seconds=jitter)

    def _iso(self, age_days: float) -> str:
        return (self._now - timedelta(days=age_days)).date().isoformat()

    def _pick(self, options: Sequence[Template]) -> Template:
        return options[self._rng.randrange(len(options))]

    def _pick_person(self, candidates: Sequence[SyntheticPerson]) -> SyntheticPerson:
        return candidates[self._rng.randrange(len(candidates))]

    def _doc(
        self, doc_type: str, slug: str, title: str, author_id: str, content: str, age_days: float
    ) -> EventCreate:
        metadata: dict[str, Any] = {
            "doc_type": doc_type,
            "title": title,
            "path": slug,
            "author_id": author_id,
        }
        return EventCreate(
            source_type=SourceType.doc,
            source_external_id=f"doc:{slug}",
            content=content,
            source_metadata=metadata,
            created_at=self._created_at(age_days),
            content_hash=self._hash(content),
        )

    def _slack(
        self,
        channel: _Channel,
        author: SyntheticPerson,
        content: str,
        age_days: float,
        thread_id: str | None = None,
    ) -> EventCreate:
        self._slack_seq += 1
        metadata: dict[str, Any] = {
            "channel": channel.name,
            "channel_id": channel.channel_id,
            "author_handle": author.handle_at_age(int(age_days)),
            "author_id": author.canonical_id,
        }
        if thread_id is not None:
            metadata["thread_id"] = thread_id
        return EventCreate(
            source_type=SourceType.slack_message,
            source_external_id=f"{channel.channel_id}-{self._slack_seq:04d}",
            content=content,
            source_metadata=metadata,
            created_at=self._created_at(age_days),
            content_hash=self._hash(content),
        )

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------
    def _emit_decision_docs(self) -> list[EventCreate]:
        out: list[EventCreate] = []
        for d in self._company.decisions:
            approvers = ", ".join(
                f"{self._company.person(a).display_name} "
                f"({self._company.person(a).handle_at_age(d.age_days)})"
                for a in d.approvers
            )
            content = decision_record(
                decision_id=d.id,
                title=d.title,
                status=d.status,
                date_iso=self._iso(d.age_days),
                approvers=approvers,
                body=d.body,
                supersedes=d.supersedes,
            )
            out.append(
                self._doc("decision_record", f"adr/{d.id}", f"{d.id} {d.title}", d.approvers[0], content, d.age_days)
            )
        return out

    def _emit_arch_docs(self) -> list[EventCreate]:
        out: list[EventCreate] = []

        # 1. The full dependency map — guarantees every DEPENDS_ON edge appears in a doc.
        dep_lines = [_ARROW.render(up=e.upstream, down=e.downstream) for e in nv.DEPENDENCY_GRAPH.edges]
        out.append(
            self._doc(
                "architecture", "arch/dependency-map", "Service Dependency Map",
                "alice-chen",
                arch_overview(
                    "Service Dependency Map",
                    "Authoritative DEPENDS_ON edges across Northwind Payments services.",
                    dep_lines,
                ),
                age_days=70,
            )
        )

        # 2. Payments overview — payments-api seed + its aliases.
        out.append(
            self._doc(
                "architecture", "arch/payments-overview", "Payments Architecture Overview",
                "diego-ramirez",
                arch_overview(
                    "Payments Architecture Overview",
                    "payments-api (also called 'the Payments team's API') is the core money-movement "
                    "service. checkout-service, billing-v2, payouts-service, subscriptions-service, "
                    "notifications-api and reporting-api all depend on payments-api.",
                    [
                        "payments-api --DEPENDS_ON--> auth-service",
                        "payments-api --DEPENDS_ON--> legacy-auth (deprecated, migration pending)",
                        "payments-api --DEPENDS_ON--> primary-db",
                    ],
                ),
                age_days=95,
            )
        )

        # 3. Auth platform overview — auth-service aliases + KQ4 subject.
        out.append(
            self._doc(
                "architecture", "arch/auth-overview", "Auth Platform Overview",
                "alice-chen",
                arch_overview(
                    "Auth Platform Overview",
                    "auth-service (AuthSvc) is the new auth system replacing legacy-auth. The auth "
                    "service reads from user-store and writes to primary-db.",
                    [
                        "auth-service --DEPENDS_ON--> user-store",
                        "auth-service --DEPENDS_ON--> primary-db",
                    ],
                ),
                age_days=80,
            )
        )

        # 4. Growth overview — keeps the look-alike pair explicitly distinct.
        out.append(
            self._doc(
                "architecture", "arch/growth-overview", "Growth Services Overview",
                "priya-nair",
                arch_overview(
                    "Growth Services Overview",
                    "notifications-api is the public API that accepts notification requests; "
                    "notification-worker is the separate background worker that delivers them off "
                    "event-bus. They are different services. web-storefront depends on checkout-service.",
                    [
                        "notification-worker --DEPENDS_ON--> notifications-api",
                        "notification-worker --DEPENDS_ON--> event-bus",
                        "web-storefront --DEPENDS_ON--> checkout-service",
                    ],
                ),
                age_days=110,
            )
        )

        # 5. Data overview.
        out.append(
            self._doc(
                "architecture", "arch/data-overview", "Data Platform Overview",
                "sam-okafor",
                arch_overview(
                    "Data Platform Overview",
                    "reporting-api and invoicing-service are owned by Data. merchant-dashboard depends "
                    "on billing-v2 and payouts-service.",
                    [
                        "merchant-dashboard --DEPENDS_ON--> billing-v2",
                        "merchant-dashboard --DEPENDS_ON--> payouts-service",
                        "invoicing-service --DEPENDS_ON--> billing-v2",
                        "reporting-api --DEPENDS_ON--> primary-db",
                    ],
                ),
                age_days=100,
            )
        )
        return out

    def _emit_wiki_docs(self) -> list[EventCreate]:
        out: list[EventCreate] = []

        # Org chart — anchors every person's display name, email, handle.
        team_lines: list[str] = []
        for t in self._company.teams:
            team_lines.append(f"## {t.display_name} (lead: {self._company.person(t.lead).display_name})")
            team_lines.append(t.mission)
            for p in self._company.members_of(t.canonical_name):
                handle = f"{p.handle} (formerly {p.former_handle})" if p.former_handle else p.handle
                team_lines.append(f"- {p.display_name} — {p.role} — {p.email} — {handle}")
            team_lines.append("")
        teamless = [p for p in self._company.people if p.team is None]
        if teamless:
            team_lines.append("## Leadership")
            for p in teamless:
                team_lines.append(f"- {p.display_name} — {p.role} — {p.email} — {p.handle}")
        out.append(
            self._doc("wiki", "wiki/org-chart", "Engineering Org Chart", "jordan-wells",
                      org_chart(self._company.name, team_lines), age_days=150)
        )

        # Service catalog — the AUTHORITATIVE ownership record (resolves reporting-api → data).
        rows: list[str] = []
        for s in self._company.services:
            owner = f"{s.owning_team} (owner: {s.owner_person})" if s.owner_person else s.owning_team
            renamed = f" (formerly {s.former_name})" if s.former_name else ""
            rows.append(f"- {s.canonical_name}{renamed} — owned by {owner} — {s.description}")
        out.append(
            self._doc("wiki", "wiki/service-catalog", "Service Catalog", "alice-chen",
                      service_catalog(rows), age_days=40)
        )

        # Onboarding guide.
        out.append(
            self._doc(
                "wiki", "wiki/onboarding", "Engineering Onboarding", "priya-nair",
                wiki_page(
                    "Engineering Onboarding", self._iso(120),
                    [
                        "Welcome to Northwind Payments. Our core service is payments-api.",
                        "We are migrating auth from legacy-auth to auth-service (AuthSvc) — see the auth "
                        "decision records.",
                        "Async messaging goes through event-bus. The system of record is primary-db.",
                    ],
                ),
                age_days=120,
            )
        )

        # On-call runbook.
        out.append(
            self._doc(
                "wiki", "wiki/oncall-runbook", "On-call Runbook", "ben-smith",
                wiki_page(
                    "On-call Runbook", self._iso(55),
                    [
                        "If payments is paging, check auth-service and primary-db first.",
                        "AuthSvc key rotation is monthly (see the signing-key decision).",
                        "notification-worker backlog: check event-bus consumer lag, not notifications-api.",
                    ],
                ),
                age_days=55,
            )
        )

        # Glossary — a couple of resolution signals (partial on purpose).
        out.append(
            self._doc(
                "wiki", "wiki/glossary", "Glossary", "sam-okafor",
                wiki_page(
                    "Glossary", self._iso(60),
                    [
                        "AuthSvc — shorthand for the auth-service.",
                        "legacy-billing — the old billing system, rewritten and renamed to billing-v2.",
                    ],
                ),
                age_days=60,
            )
        )
        return out

    def _emit_stale_docs(self) -> list[EventCreate]:
        out: list[EventCreate] = []
        for i, doc in enumerate(nv.STALE_DOCS):
            title = f"{doc.topic.title()} Guide"
            body = (
                f"This remains our recommended approach. (Note: this page has not been updated "
                f"since {self._iso(doc.age_days)}.)"
            )
            content = stale_wiki(title, self._iso(doc.age_days), doc.stale_claim, body)
            out.append(
                self._doc("wiki", f"wiki/stale-{i}", title, "alice-chen", content, doc.age_days)
            )
        return out

    # ------------------------------------------------------------------
    # Messages — dependency assertions (KQ3 reinforcement)
    # ------------------------------------------------------------------
    def _emit_dependency_messages(self) -> list[EventCreate]:
        out: list[EventCreate] = []
        for i, e in enumerate(nv.DEPENDENCY_GRAPH.edges):
            tmpl = self._pick(_DEP_SLACK)
            up_service = self._company.service(e.upstream)
            up_form = up_service.name_forms()[self._rng.randrange(len(up_service.name_forms()))]
            content = tmpl.render(up=up_form, down=e.downstream)
            author = self._pick_person(self._company.members_of(up_service.owning_team))
            age = 40 + (i * 7) % 160
            out.append(self._slack(_ARCH, author, content, age_days=age))
        return out

    # ------------------------------------------------------------------
    # KQ1 — deprecation chain
    # ------------------------------------------------------------------
    def _emit_deprecation_messages(self) -> list[EventCreate]:
        out: list[EventCreate] = []
        chain = nv.DEPRECATION_CHAINS[0]
        team = self._company.team(chain.owning_team)
        owner = self._company.person(chain.owner_person)
        thread = "kq1-legacy-auth"

        heads_up = next(t for t in DEPRECATION_TEMPLATES if t.id == "dep_chain_heads_up")
        out.append(
            self._slack(
                _AUTHMIG, self._company.person("alice-chen"),
                heads_up.render(
                    system=chain.deprecated_system, decision=chain.decision_id,
                    service="the Payments team's API", owner_team=team.display_name,
                ),
                age_days=80, thread_id=thread,
            )
        )
        owner_t = next(t for t in DEPRECATION_TEMPLATES if t.id == "dep_chain_owner")
        out.append(
            self._slack(
                _AUTHMIG, self._company.person("iris-petrova"),
                # Title reference (not the name) — Diego's title alias trap, in the KQ1 context.
                owner_t.render(
                    service=chain.dependent_service, system=chain.deprecated_system,
                    owner_team=team.display_name, owner=owner.title_refs[0],
                ),
                age_days=78, thread_id=thread,
            )
        )
        sec_t = next(t for t in DEPRECATION_TEMPLATES if t.id == "dep_chain_secondary")
        for sec in chain.secondary_dependents:
            out.append(
                self._slack(
                    _AUTHMIG, self._company.person("priya-nair"),
                    sec_t.render(service=sec, system=chain.deprecated_system, decision=chain.decision_id),
                    age_days=76, thread_id=thread,
                )
            )
        return out

    # ------------------------------------------------------------------
    # KQ2 — temporal contradiction
    # ------------------------------------------------------------------
    def _emit_contradiction_thread(self) -> list[EventCreate]:
        out: list[EventCreate] = []
        pair = nv.CONTRADICTION_PAIRS[0]
        thread = "kq2-d0005"
        alice = self._company.person("alice-chen")
        iris = self._company.person("iris-petrova")

        opener = next(t for t in CONTRADICTION_TEMPLATES if t.id == "contra_open")
        out.append(
            self._slack(
                _AUTHMIG, alice,
                opener.render(
                    decision=pair.decision_id, decision_claim=pair.decision_claim,
                    contradiction_claim=pair.contradiction_claim,
                ),
                age_days=pair.discussion_age_days, thread_id=thread,
            )
        )
        reply = next(t for t in CONTRADICTION_TEMPLATES if t.id == "contra_reply")
        out.append(
            self._slack(
                _AUTHMIG, iris,
                reply.render(decision=pair.decision_id, contradiction_claim=pair.contradiction_claim),
                age_days=pair.discussion_age_days - 1, thread_id=thread,
            )
        )
        push = next(t for t in CONTRADICTION_TEMPLATES if t.id == "contra_push")
        out.append(
            self._slack(
                _AUTHMIG, alice,
                push.render(decision=pair.decision_id, contradiction_claim=pair.contradiction_claim),
                age_days=pair.discussion_age_days - 2, thread_id=thread,
            )
        )
        return out

    # ------------------------------------------------------------------
    # KQ4 — change timeline
    # ------------------------------------------------------------------
    def _emit_change_timeline_messages(self) -> list[EventCreate]:
        out: list[EventCreate] = []
        timeline = nv.CHANGE_TIMELINES[0]
        ship = next(t for t in CHANGE_DISCUSSION_TEMPLATES if t.id == "change_ship")
        supersede = next(t for t in CHANGE_DISCUSSION_TEMPLATES if t.id == "change_supersede")
        superseding_id, superseded_id = timeline.supersession

        for did in timeline.decision_ids:
            d = self._company.decision(did)
            approver = self._company.person(d.approvers[0])
            approver_form = f"{approver.display_name} ({approver.handle_at_age(d.age_days)})"
            if did == superseding_id:
                content = supersede.render(
                    decision=did, old_decision=superseded_id, approver=approver_form
                )
            else:
                content = ship.render(decision=did, title=d.title, approver=approver_form)
            out.append(
                self._slack(_AUTHMIG, approver, content, age_days=max(d.age_days - 1, 16),
                            thread_id=f"kq4-{did}")
            )
        return out

    # ------------------------------------------------------------------
    # Entity-resolution alias coverage — every surface form appears
    # ------------------------------------------------------------------
    def _emit_alias_messages(self) -> list[EventCreate]:
        out: list[EventCreate] = []
        for group in nv.ALIAS_GROUPS:
            for j, form in enumerate(group.surface_forms):
                if group.entity_kind == "person":
                    person = self._company.person(group.canonical)
                    tmpl = self._pick(ALIAS_PERSON_TEMPLATES)
                    content = tmpl.render(who=form, topic=person.team or "platform")
                    # The former handle is only plausible in OLD messages.
                    age = 250.0 if form == person.former_handle else 60.0 + j * 9
                    channel = _TEAM_CHANNELS.get(person.team or "platform", _GENERAL)
                    author = self._pick_person(
                        tuple(p for p in self._company.people if p.canonical_id != person.canonical_id)
                    )
                else:
                    svc = self._company.service(group.canonical)
                    tmpl = self._pick(ALIAS_SERVICE_TEMPLATES)
                    content = tmpl.render(what=form)
                    # The former name is only plausible in OLD messages.
                    age = 200.0 if form == svc.former_name else 50.0 + j * 11
                    channel = _TEAM_CHANNELS.get(svc.owning_team, _GENERAL)
                    author = self._pick_person(self._company.members_of(svc.owning_team))
                out.append(self._slack(channel, author, content, age_days=age))
        return out

    def _emit_lookalike_messages(self) -> list[EventCreate]:
        out: list[EventCreate] = []
        pair = nv.LOOK_ALIKE_PAIRS[0]
        for tmpl in LOOKALIKE_TEMPLATES:
            author = self._pick_person(self._company.members_of("growth"))
            out.append(
                self._slack(
                    _TEAM_CHANNELS["growth"], author,
                    tmpl.render(a=pair.service_a, b=pair.service_b),
                    age_days=90,
                )
            )
        return out

    # ------------------------------------------------------------------
    # Bonus: ambiguous ownership, departure, handle change
    # ------------------------------------------------------------------
    def _emit_ownership_ambiguity_messages(self) -> list[EventCreate]:
        out: list[EventCreate] = []
        amb = nv.OWNERSHIP_AMBIGUITIES[0]
        # Old, contested claim (the bait).
        out.append(
            self._slack(
                _TEAM_CHANNELS[amb.contested_team], self._company.person("fatima-al-rashid"),
                f"{amb.service} dashboards are a {amb.contested_team} deliverable, we own that.",
                age_days=200,
            )
        )
        # Recent resolution by authority.
        out.append(
            self._slack(
                _TEAM_CHANNELS[amb.authoritative_team], self._company.person("sam-okafor"),
                f"wait, isn't {amb.service} a {amb.contested_team} thing? — no, per the catalog "
                f"{amb.service} is {amb.authoritative_team}'s now.",
                age_days=40,
            )
        )
        return out

    def _emit_departure_messages(self) -> list[EventCreate]:
        out: list[EventCreate] = []
        transfer = nv.DEPARTURE_TRANSFERS[0]
        bob = self._company.person(transfer.person_left)
        carol = self._company.person(transfer.successor)
        # Bob active in old messages (distinct lines so content stays unique).
        bob_lines = (
            f"pushed a fix to {transfer.asset} (formerly legacy-billing), tests green.",
            f"{transfer.asset} migration off the old legacy-billing schema is done on my end.",
        )
        for line, age in zip(bob_lines, (190, 160), strict=True):
            out.append(self._slack(_TEAM_CHANNELS["payments"], bob, line, age_days=age))
        # Recent departure + transfer.
        opener = next(t for t in DEPARTURE_TEMPLATES if t.id == "departure")
        out.append(
            self._slack(
                _TEAM_CHANNELS["payments"], self._company.person("diego-ramirez"),
                opener.render(person=bob.handle, asset=transfer.asset, successor=carol.handle),
                age_days=20, thread_id="departure-bob",
            )
        )
        followup = next(t for t in DEPARTURE_TEMPLATES if t.id == "departure_followup")
        out.append(
            self._slack(
                _TEAM_CHANNELS["payments"], carol,
                followup.render(successor=carol.handle, asset=transfer.asset, person=bob.handle),
                age_days=19, thread_id="departure-bob",
            )
        )
        return out

    def _emit_handle_change_bridge(self) -> list[EventCreate]:
        ben = self._company.person("ben-smith")
        tmpl = HANDLE_CHANGE_TEMPLATES[0]
        assert ben.former_handle is not None
        content = tmpl.render(old=ben.former_handle, new=ben.handle)
        return [self._slack(_TEAM_CHANNELS["sre"], ben, content, age_days=120)]

    # ------------------------------------------------------------------
    # Ambient realism — fixed count, still entity-grounded
    # ------------------------------------------------------------------
    def _emit_ambient_messages(self) -> list[EventCreate]:
        out: list[EventCreate] = []
        people = self._company.people
        services = self._company.services
        for i in range(AMBIENT_COUNT):
            person = people[i % len(people)]
            svc = services[(i * 5 + 2) % len(services)]
            tmpl = AMBIENT_TEMPLATES[i % len(AMBIENT_TEMPLATES)]
            who = person.mention_forms()[self._rng.randrange(len(person.mention_forms()))]
            what = svc.name_forms()[self._rng.randrange(len(svc.name_forms()))]
            content = tmpl.render(who=who, what=what)
            channel = _TEAM_CHANNELS.get(person.team or "platform", _GENERAL)
            age = 45 + (i * 11) % 290
            out.append(self._slack(channel, person, content, age_days=age))
        return out
