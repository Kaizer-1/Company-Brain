# Synthetic Company — Northwind Payments

> **Status**: Locked in Phase 2A. This document is the substrate for the synthetic
> data generator (`backend/app/synthetic/`). Strategy rationale: [ADR 0011](../decisions/0011-synthetic-data-strategy.md).
> Every entity, decision, and adversarial case named here is realised as data in
> `company.py` / `narrative.py` and asserted by `backend/tests/synthetic/`.
> The generator does **not** invent any of this — it composes what is fixed here.

This is not a Faker-style "10,000 random users" corpus. It is a small, hand-curated,
*adversarially designed* dataset for a single fictional company. Every planted trap
exists to stress a specific later phase: entity resolution (Phase 3B), the four killer
queries (Phase 3A–3C), reconciliation (Phase 4). The design is deliberate so that the
single biggest interview critique — *"of course it works, you wrote the data"* — is
answered by showing the data was built to be **hard**, not easy.

---

## 1. Company Narrative

**Northwind Payments** is a B2B payments processor founded ~6 years ago (2020). It sits
between online merchants and the card networks/banks: merchants integrate one API, and
Northwind handles authorization, capture, payouts, billing, invoicing, and reporting on
their behalf. It is ~70 people; the ~13-person engineering organisation modelled here is
the slice that produces the messages, decisions, and docs Company Brain ingests. The
company is mid-migration on two fronts that drive almost all of the interesting data: it
is (a) replacing a 6-year-old `core-monolith` with discrete services via a strangler-fig
pattern, and (b) replacing its original `legacy-auth` system with a new `auth-service`.
Both migrations are *incomplete*, which is exactly why the graph is full of contradictions,
stale assumptions, and partial dependencies — the messiness is structural, not noise.

The corpus spans a ~12-month window. The dataset's fixed "current time" is
**2026-06-01** (`REFERENCE_NOW`); all relative ages below are measured back from it. This
fixed anchor is what makes generation deterministic (see ADR 0011).

---

## 2. Org Chart

Five engineering teams plus a teamless Director who approves decisions. Emails are
`first.last@northwind.io`; informal Slack handles are `@first` unless noted. Canonical IDs
are kebab-case and are the identity key the eventual entity-resolution phase will assign.

| Team (`canonical_name`) | Mission | Lead | Members |
|---|---|---|---|
| `platform` | Shared auth, data, and infra services | Alice Chen | Alice Chen, Hassan Mehta |
| `payments` | Core money movement: auth, capture, payouts, billing | Diego Ramirez | Diego Ramirez, Bob Tanaka *(departed)*, Erik Johansson, Iris Petrova, Carol Nwosu |
| `growth` | Merchant-facing surfaces, onboarding, notifications | Priya Nair | Priya Nair, Fatima Al-Rashid |
| `data` | Reporting, invoicing, analytics | Sam Okafor | Sam Okafor, Grace Liu |
| `sre` | Reliability, deploy, event bus, on-call | Ben Smith | Ben Smith |

| Person (`canonical_id`) | Display name | Email | Handle(s) | Team | Role |
|---|---|---|---|---|---|
| `alice-chen` | Alice Chen | alice.chen@northwind.io | `@alice` (also "Al") | platform | Platform Lead |
| `hassan-mehta` | Hassan Mehta | hassan.mehta@northwind.io | `@hassan` | platform | Platform Engineer |
| `diego-ramirez` | Diego Ramirez | diego.ramirez@northwind.io | `@diego` | payments | Payments Lead |
| `bob-tanaka` | Bob Tanaka | bob.tanaka@northwind.io | `@bob` | payments | Payments Engineer *(left ~3mo ago)* |
| `erik-johansson` | Erik Johansson | erik.johansson@northwind.io | `@erik` | payments | Payments Engineer |
| `iris-petrova` | Iris Petrova | iris.petrova@northwind.io | `@iris` | payments | Staff Engineer |
| `carol-nwosu` | Carol Nwosu | carol.nwosu@northwind.io | `@carol` | payments | Payments Engineer |
| `priya-nair` | Priya Nair | priya.nair@northwind.io | `@priya` | growth | Growth Lead |
| `fatima-al-rashid` | Fatima Al-Rashid | fatima.alrashid@northwind.io | `@fatima` | growth | Growth Engineer |
| `sam-okafor` | Sam Okafor | sam.okafor@northwind.io | `@sam` | data | Data Lead |
| `grace-liu` | Grace Liu | grace.liu@northwind.io | `@grace` | data | Data Engineer |
| `ben-smith` | Ben Smith | ben.smith@northwind.io | `@ben` (formerly `@bsmith`) | sre | SRE Lead |
| `jordan-wells` | Jordan Wells | jordan.wells@northwind.io | `@jordan` | — | Director of Engineering |

---

## 3. Service Inventory

A **Service** is a deployed, running software unit with owners and runtime dependencies
(graph-schema.md). Twelve services. `canonical_name` is the entity-resolution key.

| `canonical_name` | Owning team | Tier | Description |
|---|---|---|---|
| `payments-api` | payments | critical | Core money-movement API. The blast-radius seed (KQ3). Still partly on `legacy-auth` (KQ1). |
| `auth-service` | platform | critical | New authn/authz service replacing `legacy-auth`. The change-tracking subject (KQ4). |
| `checkout-service` | payments | critical | Hosted checkout; depends on `payments-api`. |
| `billing-v2` | payments | standard | Recurring billing. **Renamed from `legacy-billing`** after a rewrite (alias trap). Owner transferred Bob→Carol. |
| `payouts-service` | payments | critical | Merchant payouts; depends on `payments-api`. |
| `subscriptions-service` | growth | standard | Subscription plans; depends on `payments-api` **and still on `legacy-auth`** (KQ1 secondary). |
| `notifications-api` | growth | standard | **Public API that accepts** notification requests. Half of the look-alike pair. |
| `notification-worker` | growth | standard | **Background worker that delivers** notifications off `event-bus`. The other half — a different thing. |
| `web-storefront` | growth | standard | Merchant-facing web app; top of the depth-≥4 chain. |
| `merchant-dashboard` | data | standard | Merchant analytics UI; depends on `billing-v2` + `payouts-service`. |
| `invoicing-service` | data | standard | Invoice generation; depends on `billing-v2`. |
| `reporting-api` | data | standard | Reporting/exports. **Contested ownership** (growth vs data) — resolves to data (KQ1 authority). |

### Dependency graph (`DEPENDS_ON`)

Direction: `A → B` means "A depends on B" (A breaks if B breaks). Sources are always
Services; targets may be Services or Systems (graph-schema.md).

```
web-storefront → checkout-service → payments-api → auth-service → user-store(Sys)
                                          ↓              ↓
                                     legacy-auth(Sys)  primary-db(Sys)
                                          ↑
                              subscriptions-service
checkout-service, billing-v2, payouts-service, subscriptions-service,
notifications-api, reporting-api      → payments-api
merchant-dashboard → billing-v2, payouts-service
invoicing-service  → billing-v2
notification-worker → notifications-api, event-bus(Sys)
reporting-api → primary-db(Sys)
```

- **Deep chain (KQ3, depth 4):** `web-storefront → checkout-service → payments-api → auth-service → user-store`. Four `DEPENDS_ON` hops, terminating at a System.
- **Blast radius of `payments-api` (KQ3):** the 10 services that transitively depend on it — `checkout-service, billing-v2, payouts-service, subscriptions-service, notifications-api, reporting-api` (direct) + `web-storefront, merchant-dashboard, invoicing-service, notification-worker` (transitive). `auth-service`/`user-store`/`legacy-auth`/`primary-db` are *downstream* dependencies, not in the blast radius.

---

## 4. System Inventory

A **System** is a higher-level named asset/platform a decision can deprecate — generally
longer-lived than a Service (graph-schema.md). Five systems. Two are deprecated; the
Service-vs-System line is deliberately exercised by `user-store` (see note).

| `canonical_name` | Owning team | Status | Description |
|---|---|---|---|
| `legacy-auth` | platform | **deprecated** (by D-0006) | Original auth system. KQ1 anchor. Still has live dependents (`payments-api`, `subscriptions-service`). |
| `core-monolith` | platform | **deprecated** (by D-0003) | The original 6-year-old monolith, being strangled. Stale-wiki bait. |
| `primary-db` | platform | active | Primary Postgres cluster. Terminal of several dependency chains. |
| `event-bus` | sre | active | Kafka backbone for async messaging. |
| `user-store` | platform | active | User-profile datastore behind `auth-service`. **Modelled as a System, not a Service** — a deliberate exercise of the schema's softest boundary (graph-schema.md "Service vs. System"); it is a passive data asset, not a runtime service with its own dependents. |

---

## 5. Decision History

Ten decisions, `D-0001`…`D-0010`, numbered monotonically by date. "Formal" = lands in a
decision-record doc; "informal" = a Slack discussion that resulted in a change (the
generator still emits a decision-record doc plus the originating thread). Ages are days
before `REFERENCE_NOW` (2026-06-01).

| ID | Age (d) | Title | Status | About / Deprecates | Approver(s) | Source |
|---|---|---|---|---|---|---|
| D-0001 | 360 | Postgres (`primary-db`) is the system of record | active | ABOUT `primary-db` | `alice-chen` | formal |
| D-0002 | 300 | Adopt `event-bus` (Kafka) for async comms | active | ABOUT `event-bus` | `ben-smith` *(as `@bsmith`)* | formal |
| D-0003 | 240 | Strangle the `core-monolith`; new features as services | active | ABOUT `core-monolith` | `jordan-wells` | formal |
| D-0004 | 150 | `auth-service` v1: stateful session model | **superseded** (by D-0010) | ABOUT `auth-service` | `alice-chen` | formal |
| D-0005 | 120 | New payment integrations stay on `legacy-auth` token validation through year-end | active | ABOUT `legacy-auth`, `payments-api` | `diego-ramirez` | formal |
| D-0006 | 85 | **Deprecate `legacy-auth`**; migrate all services to `auth-service` by Q4 | active | **DEPRECATES `legacy-auth`**, ABOUT `auth-service` | `jordan-wells`, `alice-chen` | formal |
| D-0007 | 60 | Enforce mTLS between `auth-service` and `user-store` | active | ABOUT `auth-service` | `ben-smith` *(as `@ben`)* | informal |
| D-0008 | 45 | Rotate `auth-service` signing keys monthly | active | ABOUT `auth-service` | `hassan-mehta` | informal |
| D-0009 | 30 | Standardize async writes on `event-bus`; prohibit direct `primary-db` writes from new services | active | ABOUT `event-bus`, `primary-db` | `ben-smith` | formal |
| D-0010 | 25 | Move `auth-service` to stateless JWT (**supersedes D-0004**) | active | ABOUT `auth-service` | `alice-chen`, `jordan-wells` | formal |

**Chronological flow.** Early decisions establish infrastructure (`primary-db`, `event-bus`,
monolith strangulation). The mid-period launches `auth-service` (D-0004) and, slightly
later, hedges with a stability freeze keeping new payment integrations on `legacy-auth`
(D-0005). The recent quarter is the auth migration in full swing: deprecate `legacy-auth`
(D-0006), then a rapid series of `auth-service` hardening changes (D-0007, D-0008, D-0010)
— with D-0010 explicitly superseding the original session model from D-0004.

**KQ4 window.** Four decisions about the auth subject fall inside the last quarter (≤90d):
D-0006 (85d), D-0007 (60d), D-0008 (45d), D-0010 (25d) — a mix of formal and informal,
each with a named approver, plus one supersession (D-0010 → D-0004).

---

## 6. Adversarial Planted Cases

This is the heart of the dataset. Each case is specific (named entities), ties to a killer
query or to Phase 3B entity resolution, and is *tricky but recoverable* by a careful
extractor. Each is realised in `narrative.py` and asserted by `test_narrative.py`.

### 6.1 Entity-resolution traps (Phase 3B)

**Three people, ≥3 surface forms each:**

- **`alice-chen` → KQ4.** Appears as `Alice Chen` (org doc), `alice.chen@northwind.io`
  (decision approver line), `@alice` (Slack), and the nickname **`Al`** ("Al, can you
  review the JWT cutover?"). KQ4's approver attribution for the auth timeline fails unless
  all four resolve to one person.
- **`diego-ramirez` → KQ1.** Named directly as `Diego Ramirez` / `@diego` in some events,
  but referred to **only by title** in others — *"the payments lead"*, *"Payments' tech
  lead"* — with no name. KQ1's answer ("who owns `payments-api`?") is Diego; the title
  references must resolve to him.
- **`ben-smith` → KQ4.** His handle **changed mid-history**: `@bsmith` authors/approves
  early events (D-0002, ~300d ago); `@ben` authors/approves later ones (D-0007, ~60d ago).
  Only a single bridging message states the change. KQ4 attribution for the auth timeline
  must merge `@bsmith` and `@ben` into one approver.

**Three services, ≥3 surface forms each:**

- **`auth-service` → KQ4.** `auth-service` (canonical), **`AuthSvc`** (abbreviation), and
  *"the auth service"* / *"the auth system"* (descriptive). The change-tracking subject
  must be resolved across all three.
- **`payments-api` → KQ3.** Canonical `payments-api`, plus **team-coupled** phrasings —
  *"the Payments team's API"*, *"@payments' service"*, bare *"payments"*. The blast-radius
  seed must resolve from these.
- **`billing-v2` → KQ3.** **Renamed from `legacy-billing`.** Old docs/messages (≥150d) say
  `legacy-billing`; recent ones say `billing-v2`; one bridging message states the rename.
  The blast radius must not split this into two services.

**One deliberate ambiguity:** `notifications-api` (a request-accepting API) vs
`notification-worker` (a delivery worker) — **different services, look-alike names**. The
corpus contains events where a careless reader would conflate them; KQ3's blast radius is
*wrong* if they are merged. Tied to KQ3.

### 6.2 KQ1 — Multi-hop ownership (Decision → System → Service → Team/Person)

`D-0006` **DEPRECATES** `legacy-auth`. `payments-api` still **DEPENDS_ON** `legacy-auth`
(incomplete migration). `payments-api` is **OWNED_BY** `payments`, led by `diego-ramirez`.
The 4-hop traversal `D-0006 → legacy-auth ← payments-api → payments → diego-ramirez` is the
canonical KQ1 answer. `subscriptions-service` (owned by `growth`/`priya-nair`) is a
**secondary** dependent of `legacy-auth`, so KQ1 legitimately returns two owners.

**Sources are split** so no single document answers it: D-0006 lives in a decision-record
doc; the `payments-api → legacy-auth` dependency is asserted in an architecture-diagram doc
*and* a Slack message; ownership is in the service-catalog doc; team membership is in the
org-chart doc. The only way to answer KQ1 is to traverse.

### 6.3 KQ2 — Temporal contradiction (active decision vs recent discussion)

`D-0005` (120d ago, **active**, formal): *new payment integrations stay on `legacy-auth`
through year-end*. A recent Slack thread (**~22d ago**) has `@alice` and `@iris` explicitly
contradicting it: *"we should not be putting new integrations on legacy-auth — it's
deprecated; new work goes on auth-service now."* **No formal superseding decision exists.**
The contradiction is real and detectable, but the `CONTRADICTS` edge has no matching
`supersedes` — that gap is the point of KQ2.

### 6.4 KQ3 — Blast radius (depth ≥4 + branching tree)

Covered structurally in §3: a depth-4 `DEPENDS_ON` chain and a 10-service transitive blast
radius from `payments-api` (≥4 direct dependents, fanning out through two more levels). Each
edge is asserted in at least one event, distributed across architecture docs and Slack.

### 6.5 KQ4 — Provenance + change tracking

Covered in §5: a ≥3-month timeline of four auth decisions (D-0006, D-0007, D-0008, D-0010)
with explicit approvers, mixing formal decision-record docs and informal Slack-originated
changes, including the D-0010→D-0004 supersession. The graph schema represents supersession
via `status=superseded` + `valid_to` (graph-schema.md open question #5 defers a dedicated
`SUPERSEDES` edge); the generator plants the textual *"supersedes D-0004"* signal so any
later representation can be populated.

### 6.6 Bonus messiness

- **Two stale wiki pages.** (a) `core-monolith` billing guide (~240d): *"build new billing
  logic in the monolith"* — contradicted by D-0003 (strangle the monolith) and by the
  `billing-v2` rewrite. (b) `legacy-auth` integration guide (~240d): *"legacy-auth is the
  standard for service auth"* — contradicted by D-0006. The doc content is the bait; the old
  timestamp plus recent contradictory decisions reveal the staleness.
- **One departure.** `bob-tanaka` appears active in old (≥100d) events; a recent message
  (~20d) states *"since Bob left, `billing-v2` ownership moved to @carol."* Ownership of
  `billing-v2` is `bob-tanaka` in old events, `carol-nwosu` in recent ones.
- **One ambiguous ownership.** An old Slack message (~200d) claims `growth` owns
  `reporting-api`; the service-catalog doc and an org decision assign it to `data`. KQ1
  resolves to `data` via authority (decision/catalog > stale Slack), but the ambiguity is
  detectable.

---

## Scope Honesty

This is synthetic data for **one** fictional company. The generator does not claim general
open-world data generation. The dataset is small and curated on purpose: its value is
adversarial *targeting*, not volume. Every limitation of the schema it exercises
(Service/System fuzziness, deferred entity resolution, no `SUPERSEDES` edge) is named here
and in the ADRs, not hidden.

---

## Related ADRs

- [ADR 0011](../decisions/0011-synthetic-data-strategy.md) — Why synthetic data; adversarial test cases; single-source-of-truth eval discipline
