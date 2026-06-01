"""Natural-language templates for the synthetic corpus.

This module is the *surface* layer: it holds the varied phrasings the generator chooses
among so the same entity appears in many different forms across the corpus (the alias
trap lives here, at the template level — ADR 0011). Message templates are ``Template``
objects carrying a ``style``; structured documents are built by the scaffold functions
at the bottom, which take already-rendered lines so this module stays decoupled from
``company.py``.

Templates use ``str.format`` placeholders (no Jinja dependency). The generator supplies
surface forms for the placeholders; this module never decides *which* form to use.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TemplateStyle(StrEnum):
    """The register a template is written in. Variety across styles stresses extraction."""

    FORMAL_DOC = "formal-doc"
    CASUAL_SLACK = "casual-slack"
    SLACK_THREAD_REPLY = "slack-thread-reply"
    DECISION_RECORD = "decision-record"
    ARCH_DIAGRAM = "architecture-diagram-description"


@dataclass(frozen=True)
class Template:
    """A single phrasing with a style. ``render`` fills the ``{...}`` placeholders."""

    id: str
    style: TemplateStyle
    body: str

    def render(self, **fields: str) -> str:
        return self.body.format(**fields)


# ---------------------------------------------------------------------------
# Dependency assertions ({up} DEPENDS_ON {down})
# ---------------------------------------------------------------------------
DEPENDENCY_TEMPLATES: tuple[Template, ...] = (
    Template("dep_calls", TemplateStyle.CASUAL_SLACK,
             "{up} calls into {down} on the hot path — if {down} is down, {up} is down too."),
    Template("dep_reminder", TemplateStyle.CASUAL_SLACK,
             "reminder for deploys: {up} depends on {down}, so coordinate before touching {down}."),
    Template("dep_traced", TemplateStyle.CASUAL_SLACK,
             "traced the {up} latency spike back to {down} — {up} sits right on top of it."),
    Template("dep_arrow", TemplateStyle.ARCH_DIAGRAM,
             "{up} --DEPENDS_ON--> {down}"),
    Template("dep_runtime", TemplateStyle.CASUAL_SLACK,
             "fyi {up} can't start without {down} reachable; it's a hard runtime dependency."),
)


# ---------------------------------------------------------------------------
# Deprecation chain (KQ1)
# ---------------------------------------------------------------------------
DEPRECATION_TEMPLATES: tuple[Template, ...] = (
    Template("dep_chain_heads_up", TemplateStyle.CASUAL_SLACK,
             "heads up: {system} is deprecated as of {decision}, but {service} still talks to "
             "it. that migration is on {owner_team}."),
    Template("dep_chain_owner", TemplateStyle.CASUAL_SLACK,
             "who owns the {service} migration off {system}? that's {owner_team}'s — ping {owner}."),
    Template("dep_chain_secondary", TemplateStyle.CASUAL_SLACK,
             "{service} is also still wired to {system}. add it to the {decision} migration list."),
)


# ---------------------------------------------------------------------------
# Temporal contradiction (KQ2)
# ---------------------------------------------------------------------------
CONTRADICTION_TEMPLATES: tuple[Template, ...] = (
    Template("contra_open", TemplateStyle.CASUAL_SLACK,
             "re {decision}: it says {decision_claim}. honestly that's not what we're doing — "
             "{contradiction_claim}."),
    Template("contra_reply", TemplateStyle.SLACK_THREAD_REPLY,
             "+1, {contradiction_claim}. nobody has written a superseding decision though, "
             "so {decision} is still technically active."),
    Template("contra_push", TemplateStyle.SLACK_THREAD_REPLY,
             "yeah {decision} is stale. {contradiction_claim}. we should formalize that."),
)


# ---------------------------------------------------------------------------
# Change-timeline discussion (KQ4)
# ---------------------------------------------------------------------------
CHANGE_DISCUSSION_TEMPLATES: tuple[Template, ...] = (
    Template("change_ship", TemplateStyle.CASUAL_SLACK,
             "shipped {decision}: {title}. approved by {approver}."),
    Template("change_recap", TemplateStyle.SLACK_THREAD_REPLY,
             "for the record {decision} ({title}) was signed off by {approver}."),
    Template("change_supersede", TemplateStyle.CASUAL_SLACK,
             "{decision} supersedes {old_decision} — the old session model is gone. {approver} approved."),
)


# ---------------------------------------------------------------------------
# Entity-resolution alias mentions
# ---------------------------------------------------------------------------
ALIAS_PERSON_TEMPLATES: tuple[Template, ...] = (
    Template("person_review", TemplateStyle.CASUAL_SLACK, "{who} is reviewing this, hold for sign-off."),
    Template("person_ping", TemplateStyle.CASUAL_SLACK, "ping {who} on this one, it's their area."),
    Template("person_credit", TemplateStyle.SLACK_THREAD_REPLY, "nice, {who} already fixed it."),
    Template("person_assign", TemplateStyle.CASUAL_SLACK, "assigning the {topic} follow-up to {who}."),
)

ALIAS_SERVICE_TEMPLATES: tuple[Template, ...] = (
    Template("svc_deploy", TemplateStyle.CASUAL_SLACK, "deploying {what} in ~10, watch the dashboards."),
    Template("svc_alert", TemplateStyle.CASUAL_SLACK, "{what} is throwing 5xx again, looking now."),
    Template("svc_ref", TemplateStyle.SLACK_THREAD_REPLY, "this is on {what}, not us."),
    Template("svc_plan", TemplateStyle.CASUAL_SLACK, "next sprint we harden {what} a bit."),
)


# ---------------------------------------------------------------------------
# Look-alike pair (must stay distinct)
# ---------------------------------------------------------------------------
LOOKALIKE_TEMPLATES: tuple[Template, ...] = (
    Template("lookalike_clarify", TemplateStyle.SLACK_THREAD_REPLY,
             "careful — {a} accepts the request, {b} actually delivers it. they're different services."),
    Template("lookalike_a", TemplateStyle.CASUAL_SLACK,
             "{a} returned a 202 fine; the issue is downstream, not in {a}."),
    Template("lookalike_b", TemplateStyle.CASUAL_SLACK,
             "{b} backlog is growing — the worker isn't draining the queue."),
)


# ---------------------------------------------------------------------------
# Ownership statements + ambiguity
# ---------------------------------------------------------------------------
OWNERSHIP_TEMPLATES: tuple[Template, ...] = (
    Template("own_catalog", TemplateStyle.CASUAL_SLACK, "{service} is owned by {team}, per the catalog."),
    Template("own_contested", TemplateStyle.CASUAL_SLACK,
             "wait, isn't {service} a {contested} thing? — no, {service} is {authoritative}'s now."),
)


# ---------------------------------------------------------------------------
# Departure + handle change
# ---------------------------------------------------------------------------
DEPARTURE_TEMPLATES: tuple[Template, ...] = (
    Template("departure", TemplateStyle.CASUAL_SLACK,
             "since {person} left the company, {asset} ownership moved to {successor}."),
    Template("departure_followup", TemplateStyle.SLACK_THREAD_REPLY,
             "yep, {successor} owns {asset} now — update the catalog, {person} is gone."),
)

HANDLE_CHANGE_TEMPLATES: tuple[Template, ...] = (
    Template("handle_change", TemplateStyle.CASUAL_SLACK,
             "fyi I changed my handle from {old} to {new}, same person."),
)


# ---------------------------------------------------------------------------
# Ambient realism (still tied to real entities)
# ---------------------------------------------------------------------------
AMBIENT_TEMPLATES: tuple[Template, ...] = (
    Template("amb_standup", TemplateStyle.CASUAL_SLACK,
             "standup: {who} is on the {what} work today."),
    Template("amb_deploy", TemplateStyle.CASUAL_SLACK,
             "{what} deploy is green. nice one {who}."),
    Template("amb_oncall", TemplateStyle.CASUAL_SLACK,
             "{who} has oncall this week; page on {what} issues."),
    Template("amb_review", TemplateStyle.SLACK_THREAD_REPLY,
             "{who} reviewed the {what} change, good to merge."),
)


# ---------------------------------------------------------------------------
# Document scaffolds — take already-rendered lines, stay decoupled from company.py
# ---------------------------------------------------------------------------
def decision_record(
    decision_id: str,
    title: str,
    status: str,
    date_iso: str,
    approvers: str,
    body: str,
    supersedes: str | None = None,
) -> str:
    """A formal decision-record document (the ADR-style source for a Decision)."""
    lines = [
        f"# Decision {decision_id}: {title}",
        "",
        f"Status: {status}",
        f"Date: {date_iso}",
        f"Approved by: {approvers}",
    ]
    if supersedes is not None:
        lines.append(f"Supersedes: {supersedes}")
    lines += ["", "## Decision", "", body]
    return "\n".join(lines)


def arch_overview(title: str, intro: str, dependency_lines: list[str]) -> str:
    """An architecture overview describing dependencies as a textual diagram."""
    lines = [f"# {title}", "", intro, "", "## Service dependencies", ""]
    lines += dependency_lines
    return "\n".join(lines)


def org_chart(company_name: str, team_lines: list[str]) -> str:
    lines = [f"# {company_name} — Engineering Org Chart", ""]
    lines += team_lines
    return "\n".join(lines)


def service_catalog(rows: list[str]) -> str:
    lines = ["# Service Catalog", "", "Authoritative ownership of record.", ""]
    lines += rows
    return "\n".join(lines)


def wiki_page(title: str, date_iso: str, paragraphs: list[str]) -> str:
    lines = [f"# {title}", "", f"Last updated: {date_iso}", ""]
    lines += paragraphs
    return "\n".join(lines)


def stale_wiki(title: str, date_iso: str, claim: str, body: str) -> str:
    """A wiki page whose advice is now wrong; the old date is the tell."""
    return "\n".join([
        f"# {title}",
        "",
        f"Last updated: {date_iso}",
        "",
        f"Recommendation: {claim}.",
        "",
        body,
    ])
