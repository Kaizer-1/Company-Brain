# Phase 2A Interview Readiness

Q&A covering the synthetic data generator design (ADR 0011) and the Northwind Payments
fictional company. Each answer is deliverable in under 90 seconds. Honest answers; named
weaknesses. Full rationale lives in [`docs/design/synthetic-company.md`](../design/synthetic-company.md)
and [ADR 0011](../decisions/0011-synthetic-data-strategy.md).

---

## Q&A

### 1. Why hand-curated synthetic data instead of Faker, real OSS data, or Enron?

Four options were considered and three rejected. Faker-style random generation is trivial
to write but produces no planted structure — no 4-hop ownership chain, no
active-decision-vs-recent-discussion contradiction — so it cannot exercise the killer
queries and makes the "you wrote the data" critique worse, not better. A real open-source
corpus (Apache mailing lists) has genuine messiness but no ground truth: scoring extraction
F1 against thousands of unlabelled real messages is a separate labelling project, and the
ASF ontology (software projects, patches) does not map to our schema's
service/decision/ownership shape. Enron has the same ontology mismatch and adds PII
baggage. The hand-curated option is the only one that gives us reproducibility, derived
ground truth, on-ontology traversals, and designed adversarial difficulty simultaneously.
The design doc (`docs/design/synthetic-company.md`) doubles as the ground-truth labels,
so the "you wrote the data" critique becomes an answer, not an embarrassment.

---

### 2. Why are planted cases designed before the generator code, not after?

Because if the traps were invented during code-writing, the difficulty would be whatever
the generator finds easy to produce — which is, by construction, what the extractor finds
easy to recognise. The whole point of an adversarial case is that it is hard for the *later
phase*, not easy for the *current one*. So the design process is: (1) read the schema's
named soft spots (`Service`/`System` fuzziness, deferred entity resolution, no `SUPERSEDES`
edge), (2) plant cases that hit them — the `@bsmith`→`@ben` handle change, the
`legacy-billing`→`billing-v2` rename, the look-alike `notifications-api`/`notification-worker`
pair — as data in `narrative.py`, (3) write `test_narrative.py` to assert the inventory
before writing any generator code, and (4) only then write the generator. The generator's
only job is to render the fixed cases into varied natural-language surface forms; it does
not invent any of them. This discipline means every trap is intentional, named, and
tied to a specific killer query or Phase 3B entity resolution.

---

### 3. Walk me through how the KQ1 deprecation chain becomes multiple events in the corpus.

The chain is `D-0006 DEPRECATES legacy-auth ← DEPENDS_ON payments-api OWNED_BY payments /
diego-ramirez`. The key constraint is that no single document answers it — if any single
event described all four hops, a RAG system could retrieve it and KQ1 would be trivially
answerable without traversal. So the sources are deliberately split. `D-0006` lives in a
decision-record document (event type `decision_record`): it asserts the DEPRECATES edge and
the ABOUT edge with `alice-chen` and `jordan-wells` as approvers. The `payments-api →
legacy-auth` DEPENDS_ON edge is asserted in two separate events: an architecture-diagram
document and a Slack message in which someone mentions that `payments-api` still calls
`legacy-auth`. Ownership of `payments-api` is asserted in the service-catalog document, not
in the decision record. Team membership (Diego is the payments lead) is in the org-chart
document. The extraction pipeline must extract and the query engine must traverse all four
hops to reconstruct the answer; the graph is the only data structure that can hold all four
simultaneously and traverse them in one Cypher MATCH.

---

### 4. What does deterministic seeding actually buy you? What would break without it?

Every downstream eval number — extraction F1 in Phase 2B, entity-resolution precision in
Phase 3B, query recall in Phase 3A-C — is only meaningful if the corpus it is measured on
is byte-for-byte identical across runs and machines. Without a fixed seed, "the Phase 2B
run last Tuesday" and "the Phase 2B run this morning" could differ in which surface forms
the generator picked for `ben-smith` or `auth-service`, which events are in which order,
and which alias forms appear. That makes numbers non-comparable — you cannot tell if a
change in F1 is due to a model change or a corpus shuffle. Concretely, `test_generator_determinism.py`
asserts this as a hard contract by comparing a hash of the full generated corpus against a
known value; if the contract breaks, CI fails. In practice, determinism is achieved by
threading one `random.Random(seed=42)` instance through the entire generator — never the
global `random` module — and using `REFERENCE_NOW = datetime(2026, 6, 1)` as the fixed
"current time" for all relative date offsets.

---

### 5. Why is `REFERENCE_NOW` a fixed constant instead of `datetime.now()`?

Because the corpus contains relative temporal logic that must be stable. Events are dated
at offsets from `REFERENCE_NOW` — for example, `D-0006` is 85 days before it, the KQ2
contradicting Slack thread is 22 days before it, the KQ4 auth timeline spans the last
90 days. If `REFERENCE_NOW` were `datetime.now()`, re-running the seeder a week later would
shift every event date by a week. Events that were "22 days ago" become "29 days ago".
The KQ2 contradiction is defined as "a recent discussion in the last month contradicts an
active decision" — "last month" is relative to `REFERENCE_NOW`. If that constant drifts,
the query's one-month window filter might stop catching the planted contradiction, and Phase
3B's temporal reasoning is evaluated on a different corpus each run. The fix is trivially
simple: name one fixed date as the corpus's permanent "now" and bake it into the design doc
so any future session knows the anchor without having to re-derive it from timestamps.

---

### 6. How do you model an entity-resolution trap in the data? Use the `@bsmith` → `@ben` handle change as the concrete example.

An entity-resolution trap is an `AliasGroup` in `narrative.py`: a `dataclass(frozen=True)`
with a `canonical` identity (`ben-smith`), a set of `surface_forms` that all must appear
somewhere in the corpus, and a `kq` field naming the killer query whose answer breaks if
these forms are not merged (`KQ4`, because Ben approved D-0002 as `@bsmith` and D-0007 as
`@ben`, and KQ4's approval attribution must treat both as the same person). The generator is
required to use every surface form at least once — that is what `test_narrative.py` asserts.
For `ben-smith`, the surface forms are `Ben Smith` (formal org-chart mention), `@bsmith`
(early Slack messages, D-0002 approval ~300 days ago), `@ben` (later events, D-0007
approval ~60 days ago), and `ben.smith@northwind.io` (email in a decision approver line).
The critical adversarial ingredient is a single bridging message: an event that explicitly
states the handle change, without which no automatic resolver could connect `@bsmith` to
`@ben`. That bridge is planted deliberately; the entity resolver in Phase 3B must find it.
An extractor that does not merge these four forms will show `alias_not_merged` in the
eval report — which is exactly what Phase 2B measured (10–13 cases per model, as expected).

---

### 7. What's the risk of the "of course it works, you wrote the data" critique, and how does the design address it?

The critique has two variants. The weak form is "your data is too clean" — the extractor
succeeds because there are no ambiguous names, no contradictions, no traps. The strong form
is "your eval is circular" — you wrote the data and you wrote the evaluator, so you can
make F1 whatever you want by making the data easy. The design addresses both. Against the
weak form: every planted case is documented in `docs/design/synthetic-company.md` with an
explicit note on which phase it is designed to challenge. The look-alike pair
(`notifications-api` vs `notification-worker`), the renamed service (`legacy-billing` →
`billing-v2`), the handle change (`@bsmith` → `@ben`), the title-only reference ("the
payments lead") — each is designed to trip a specific kind of extractor or resolver. The
eval results show these traps working: all three Phase 2B models produced `alias_not_merged`
counts of 10–13, confirming the aliases genuinely confused extraction. Against the strong
form: ADR 0013 describes how ground truth is derived from `narrative.py` without any
model involvement — the cases were designed before the generator was written, and before any
model was run. The honest F1 numbers (relation F1 0.57–0.78) are not inflated.

---

### 8. Why is `user-store` modelled as a System and not a Service? When would you change this?

The `Service`/`System` boundary is the schema's softest named distinction (documented in
`docs/design/graph-schema.md`). The rule is: a Service runs requests and has its own
deployment, owns a dependency graph, and can be a blast-radius seed. A System is a
platform, datastore, or backbone that a Decision can deprecate — a passive asset rather than
an active request handler. `user-store` is a user-profile datastore accessed only via
`auth-service`; it has no direct API surface that other services call except through
`auth-service`'s abstraction, it does not appear in any blast-radius calculation as an
independent seed, and a decision could deprecate it without migrating every service
individually. That profile — passive data asset, no independent dependents, deprecatable as
a unit — is the System pattern. You would change it to a Service if `user-store` grew its
own direct REST API that other services called, if it acquired its own team ownership and
on-call rotation independent of `auth-service`, or if you needed to model `OWNED_BY` and
`DEPENDS_ON` relationships with it as a source rather than just a target. The fact that all
three Phase 2B models had non-zero `wrong_entity_type` counts for `event-bus`, `legacy-auth`,
and `primary-db` (but not `user-store`, because the prompt's "passive datastore" hint
helped) confirms this boundary is genuinely hard.

---

### 9. How do you keep the look-alike pair (`notifications-api` vs `notification-worker`) from being merged by a careless extractor?

The look-alike pair is a `LookAlikePair` in `narrative.py`: it names `service_a` and
`service_b`, the `kq` it targets (KQ3 — the blast radius is wrong if they merge), and a
human-readable note explaining the distinction. The corpus must contain events that make the
distinction explicit: `notifications-api` is described as "the public API that accepts
notification requests" and `notification-worker` is described as "the background worker that
delivers notifications off `event-bus`." The generator is required to use both names in
events that make their different roles visible. The blast-radius invariant is: only
`notification-worker` depends on `notifications-api` (via a DEPENDS_ON edge); merging them
would either create a self-loop or collapse a two-node chain into one, corrupting the KQ3
traversal. The correct extractor extracts two distinct `Service` nodes; a careless one
produces one. The eval harness scores them as two separate ground-truth entities, so a merge
shows up as a false positive + false negative pair rather than a clean match, degrading F1.
This is by design — the look-alike pair is meant to be hard enough to show up in failure
mode counts.

---

### 10. What's the single biggest weakness of the synthetic dataset and what would you fix in v2?

The dataset is a single company at one scale (13 people, 12 services, 10 decisions, 111
events). That makes it a correctness fixture, not a thoroughness one — it proves the
extraction and query logic is right on a carefully-designed set of hard cases, but it cannot
tell you whether F1 degrades at 1,000 events, whether the query engine slows on a 500-node
graph, or whether the alias resolver handles 200 aliases rather than 13. A second weakness
is that the planted cases are known to both the generator author and the evaluator, so
there is a risk of unconscious optimization toward the planted cases during prompt iteration
rather than against genuinely unseen hard cases. In v2, I would add a second fictional
company with its own independently-designed planted cases as a held-out test set, so the
prompt is tuned on Northwind Payments and scored against a company whose specific traps it
has never seen. I would also add at least two message types not currently in the corpus
(meeting transcripts and RFC-style long-form documents) to exercise the chunking path that
Phase 2B intentionally defers.

---

## Key Concepts to Whiteboard

These are the 5 concepts from Phase 2A you should be able to sketch or explain from memory
in under 5 minutes each.

1. **The dependency graph + depth-4 chain.** Draw the 12 services and 5 systems as nodes.
   Show the `DEPENDS_ON` edges. Highlight the depth-4 chain:
   `web-storefront → checkout-service → payments-api → auth-service → user-store(Sys)`.
   Mark the blast radius of `payments-api`: the 6 direct dependents (checkout-service,
   billing-v2, payouts-service, subscriptions-service, notifications-api, reporting-api) and
   4 transitive dependents (web-storefront, merchant-dashboard, invoicing-service,
   notification-worker). Explain that `auth-service`/`user-store` are downstream, not in the
   blast radius.

2. **The KQ1 traversal: Decision → System → Service → Team → Person.** Draw 5 nodes:
   `D-0006` (Decision) → `legacy-auth` (System) ← `payments-api` (Service) → `payments`
   (Team) → `diego-ramirez` (Person). Label each edge with its type (DEPRECATES, DEPENDS_ON,
   OWNED_BY, MEMBER_OF). Explain that the sources are split across four document types so no
   single event answers the query. Point to `subscriptions-service` as a secondary KQ1
   answer (also depends on `legacy-auth`, owned by `growth`/`priya-nair`).

3. **The KQ2 contradiction: active decision + recent discussion + no supersession.** Draw a
   timeline. Place `D-0005` (120 days ago, active): "new payment integrations stay on
   `legacy-auth` through year-end." Then place the recent Slack thread (~22 days ago):
   `@alice` and `@iris` explicitly say "new integrations must not use legacy-auth — it's
   deprecated." Draw a `CONTRADICTS` edge from the Message to the Decision. Show the gap:
   no formal superseding decision, no `valid_to` set on D-0005. The contradiction is real,
   detectable, and unresolved — that is what KQ2 surfaces.

4. **The alias-group structure for `ben-smith`.** Draw one canonical node (`ben-smith`) with
   four surface forms emanating from it: `Ben Smith` (org chart), `@bsmith` (D-0002 approval,
   ~300d ago), `@ben` (D-0007 approval, ~60d ago), `ben.smith@northwind.io` (email in
   decision record). Mark the bridging message as the evidence that connects `@bsmith` and
   `@ben` — without it, no resolver can merge them. Show that Phase 2B's extractor sees all
   four forms as separate nodes (alias_not_merged count = 10–13 per model); Phase 3B merges
   them onto `ben-smith`.

5. **The chronological decision timeline showing supersession.** Draw a horizontal timeline
   from 360 days ago to 25 days ago. Place all 10 decisions. Highlight the KQ4 window (≤90
   days): D-0006 (85d, DEPRECATES legacy-auth), D-0007 (60d, mTLS), D-0008 (45d, key
   rotation), D-0010 (25d, stateless JWT). Draw an arrow from D-0010 back to D-0004 labelled
   "supersedes" — D-0004 (150d, stateful session model) is now status=superseded, valid_to
   set. Explain that D-0005 (120d, stability freeze on legacy-auth) is still active and has
   no supersession, making it the KQ2 contradiction target.
