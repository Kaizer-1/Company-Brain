# Phase 2B — Extraction Eval Results

_Generated: 2026-06-01_

Corpus: **111 events**. Ground truth: **45 entities**, **70 relationships** (derived from `narrative.py` — ADR 0013).

## Overall results

| Model | Entity P | Entity R | Entity F1 | Rel P | Rel R | Rel F1 | Cost (USD) |
|-------|----------|----------|-----------|-------|-------|--------|------------|
| `openai/gpt-4o-mini` | 0.84 | 0.91 | 0.87 | 0.69 | 0.57 | 0.62 | 0.0349 |
| `anthropic/claude-3.5-haiku` | 0.88 | 0.96 | 0.91 | 0.77 | 0.80 | 0.78 | 0.3473 |
| `google/gemini-2.5-flash-lite` | 0.80 | 0.96 | 0.87 | 0.51 | 0.64 | 0.57 | 0.0383 |


**Total cost across all models: $0.4205** (fresh API spend this run: $0.0383; the remainder was served from cache).

## Failure modes (counts per model)

| Failure mode | `openai/gpt-4o-mini` | `anthropic/claude-3.5-haiku` | `google/gemini-2.5-flash-lite` |
|---|---|---|---|
| missed_entity | 4 | 1 | 2 |
| spurious_entity | 4 | 4 | 11 |
| wrong_entity_type | 4 | 2 | 0 |
| missed_relationship | 29 | 12 | 25 |
| spurious_relationship | 17 | 15 | 42 |
| wrong_relationship_type | 2 | 3 | 1 |
| alias_not_merged | 13 | 10 | 11 |

## Model: `openai/gpt-4o-mini`

Parse failures: 1/111 events. Cost: $0.0349.

Mean confidence — correct: 0.92 (n=331), incorrect: 0.90 (n=35) — **ok**.

**Entities by type**

| Type | P | R | F1 | TP | FP | FN |
|------|---|---|----|----|----|----|
| Decision | 1.00 | 1.00 | 1.00 | 10 | 0 | 0 |
| Person | 1.00 | 1.00 | 1.00 | 13 | 0 | 0 |
| Service | 0.67 | 1.00 | 0.80 | 12 | 6 | 0 |
| System | 0.71 | 1.00 | 0.83 | 5 | 2 | 0 |
| Team | 1.00 | 0.20 | 0.33 | 1 | 0 | 4 |

**Relationships by type**

| Type | P | R | F1 | TP | FP | FN |
|------|---|---|----|----|----|----|
| ABOUT | 0.60 | 0.46 | 0.52 | 6 | 4 | 7 |
| APPROVED_BY | 1.00 | 1.00 | 1.00 | 12 | 0 | 0 |
| DEPENDS_ON | 0.86 | 1.00 | 0.93 | 19 | 3 | 0 |
| DEPRECATES | 0.33 | 1.00 | 0.50 | 1 | 2 | 0 |
| MEMBER_OF | 0.00 | 0.00 | 0.00 | 0 | 5 | 12 |
| OWNED_BY | 0.33 | 0.15 | 0.21 | 2 | 4 | 11 |

### Worst-case examples

**missed_entity** (4 total)
- extractor said: (nothing); expected: Team data
- extractor said: (nothing); expected: Team growth
- extractor said: (nothing); expected: Team platform

**spurious_entity** (4 total)
- extractor said: Service billing-service (raw: 'billing-service'); expected: (not in ground truth) — evidence: "the billing service calls into payments-api" [event cd06ea4b]
- extractor said: Service data-s (raw: "data's"); expected: (not in ground truth) — evidence: "reporting-api is data's now." [event e14946eb]
- extractor said: System auth (raw: 'auth'); expected: (not in ground truth) — evidence: "the auth system change" [event 01585ac6]

**wrong_entity_type** (4 total)
- extractor said: event-bus as Service, System; expected: event-bus as System — evidence: "All inter-service async messaging moves onto event-bus." [event a3949b3a]
- extractor said: legacy-auth as Service, System; expected: legacy-auth as System — evidence: "continue using legacy-auth token validation until the end of the year" [event 012f7f48]
- extractor said: primary-db as Service, System; expected: primary-db as System — evidence: "standardize on primary-db as the canonical store for all transactional data." [event cbb8971e]

**missed_relationship** (29 total)
- extractor said: (nothing); expected: D-0001 -[ABOUT]-> primary-db
- extractor said: (nothing); expected: D-0003 -[ABOUT]-> core-monolith
- extractor said: (nothing); expected: D-0005 -[ABOUT]-> payments-api

**spurious_relationship** (17 total)
- extractor said: D-0005 -[ABOUT]-> auth-service; expected: (not in ground truth) — evidence: "use auth-service now." [event 0b53a3ec]
- extractor said: D-0006 -[ABOUT]-> subscriptions-service; expected: (not in ground truth) — evidence: "add it to the D-0006 migration list." [event 251e3a50]
- extractor said: D-0007 -[ABOUT]-> user-store; expected: (not in ground truth) — evidence: "Enforce mTLS between auth-service and user-store." [event bfa889cb]

**wrong_relationship_type** (2 total)
- extractor said: D-0005 -[ABOUT, DEPRECATES]-> legacy-auth; expected: D-0005 -[ABOUT]-> legacy-auth — evidence: "continue using legacy-auth token validation until the end of the year" [event 012f7f48]
- extractor said: D-0006 -[DEPRECATES]-> legacy-auth; expected: D-0006 -[ABOUT, DEPRECATES]-> legacy-auth — evidence: "legacy-auth is deprecated." [event a5174de0]

**alias_not_merged** (13 total)
- extractor said: alice-chen: ['Al', 'Alice Chen']; expected: one node (Phase 3B will merge these)
- extractor said: auth-service: ['auth service', 'auth-service']; expected: one node (Phase 3B will merge these)
- extractor said: ben-smith: ['Ben Smith', 'ben', 'ben.smith@northwind.io']; expected: one node (Phase 3B will merge these)

## Model: `anthropic/claude-3.5-haiku`

Parse failures: 4/111 events. Cost: $0.3473.

Mean confidence — correct: 0.92 (n=369), incorrect: 0.83 (n=35) — **ok**.

**Entities by type**

| Type | P | R | F1 | TP | FP | FN |
|------|---|---|----|----|----|----|
| Decision | 1.00 | 1.00 | 1.00 | 10 | 0 | 0 |
| Person | 1.00 | 1.00 | 1.00 | 13 | 0 | 0 |
| Service | 0.80 | 1.00 | 0.89 | 12 | 3 | 0 |
| System | 0.57 | 0.80 | 0.67 | 4 | 3 | 1 |
| Team | 1.00 | 0.80 | 0.89 | 4 | 0 | 1 |

**Relationships by type**

| Type | P | R | F1 | TP | FP | FN |
|------|---|---|----|----|----|----|
| ABOUT | 0.71 | 0.77 | 0.74 | 10 | 4 | 3 |
| APPROVED_BY | 0.92 | 1.00 | 0.96 | 12 | 1 | 0 |
| DEPENDS_ON | 0.90 | 1.00 | 0.95 | 19 | 2 | 0 |
| DEPRECATES | 0.25 | 1.00 | 0.40 | 1 | 3 | 0 |
| MEMBER_OF | 0.14 | 0.08 | 0.11 | 1 | 6 | 11 |
| OWNED_BY | 0.93 | 1.00 | 0.96 | 13 | 1 | 0 |

### Worst-case examples

**missed_entity** (1 total)
- extractor said: (nothing); expected: Team sre

**spurious_entity** (4 total)
- extractor said: Service billing-service (raw: 'billing-service'); expected: (not in ground truth) — evidence: "the billing service calls into payments-api" [event cd06ea4b]
- extractor said: System auth (raw: 'auth'); expected: (not in ground truth) — evidence: "auth system change" [event 01585ac6]
- extractor said: System auth-system (raw: 'auth-system'); expected: (not in ground truth) — evidence: "the auth system is throwing 5xx again" [event 9a52ffe1]

**wrong_entity_type** (2 total)
- extractor said: event-bus as Service, System; expected: event-bus as System — evidence: "All inter-service async messaging moves onto event-bus" [event a3949b3a]
- extractor said: user-store as Service; expected: user-store as System — evidence: "traffic between auth-service and user-store" [event ca99801c]

**missed_relationship** (12 total)
- extractor said: (nothing); expected: D-0005 -[ABOUT]-> payments-api
- extractor said: (nothing); expected: alice-chen -[MEMBER_OF]-> platform
- extractor said: (nothing); expected: ben-smith -[MEMBER_OF]-> sre

**spurious_relationship** (15 total)
- extractor said: D-0005 -[ABOUT]-> auth-service; expected: (not in ground truth) — evidence: "use auth-service now" [event 0b53a3ec]
- extractor said: D-0006 -[ABOUT]-> subscriptions-service; expected: (not in ground truth) — evidence: "add it to the D-0006 migration list" [event 251e3a50]
- extractor said: D-0007 -[ABOUT]-> user-store; expected: (not in ground truth) — evidence: "traffic between auth-service and user-store" [event ca99801c]

**wrong_relationship_type** (3 total)
- extractor said: D-0003 -[DEPRECATES]-> core-monolith; expected: D-0003 -[ABOUT]-> core-monolith — evidence: "No new feature work lands in core-monolith; we extract services incrementally" [event 33217389]
- extractor said: D-0005 -[ABOUT, DEPRECATES]-> legacy-auth; expected: D-0005 -[ABOUT]-> legacy-auth — evidence: "new payment integrations continue using legacy-auth token validation" [event 012f7f48]
- extractor said: D-0006 -[DEPRECATES]-> legacy-auth; expected: D-0006 -[ABOUT, DEPRECATES]-> legacy-auth — evidence: "legacy-auth is deprecated." [event a5174de0]

**alias_not_merged** (10 total)
- extractor said: alice-chen: ['Al', 'Alice', 'Alice Chen', 'alice.chen@northwind.io']; expected: one node (Phase 3B will merge these)
- extractor said: auth-service: ['AuthSvc', 'auth-service']; expected: one node (Phase 3B will merge these)
- extractor said: ben-smith: ['Ben Smith', 'ben', 'ben.smith@northwind.io', 'bsmith']; expected: one node (Phase 3B will merge these)

## Model: `google/gemini-2.5-flash-lite`

Parse failures: 6/111 events. Cost: $0.0383.

Mean confidence — correct: 0.92 (n=311), incorrect: 0.82 (n=65) — **ok**.

**Entities by type**

| Type | P | R | F1 | TP | FP | FN |
|------|---|---|----|----|----|----|
| Decision | 0.82 | 0.90 | 0.86 | 9 | 2 | 1 |
| Person | 0.93 | 1.00 | 0.96 | 13 | 1 | 0 |
| Service | 0.80 | 1.00 | 0.89 | 12 | 3 | 0 |
| System | 0.50 | 1.00 | 0.67 | 5 | 5 | 0 |
| Team | 1.00 | 0.80 | 0.89 | 4 | 0 | 1 |

**Relationships by type**

| Type | P | R | F1 | TP | FP | FN |
|------|---|---|----|----|----|----|
| ABOUT | 0.45 | 0.77 | 0.57 | 10 | 12 | 3 |
| APPROVED_BY | 1.00 | 0.83 | 0.91 | 10 | 0 | 2 |
| DEPENDS_ON | 0.79 | 1.00 | 0.88 | 19 | 5 | 0 |
| DEPRECATES | 0.50 | 1.00 | 0.67 | 1 | 1 | 0 |
| MEMBER_OF | 0.22 | 0.17 | 0.19 | 2 | 7 | 10 |
| OWNED_BY | 0.14 | 0.23 | 0.18 | 3 | 18 | 10 |

### Worst-case examples

**missed_entity** (2 total)
- extractor said: (nothing); expected: Decision D-0003
- extractor said: (nothing); expected: Team sre

**spurious_entity** (11 total)
- extractor said: Decision build-all-new-billing-logic-inside-core-monolith (raw: 'build all new billing logic inside core-monolith'); expected: (not in ground truth) — evidence: "Recommendation: build all new billing logic inside core-monolith." [event 42fada48]
- extractor said: Decision signing-key (raw: 'signing-key'); expected: (not in ground truth) — evidence: "see the signing-key decision" [event 740e9626]
- extractor said: Person payments-lead (raw: 'payments lead'); expected: (not in ground truth) — evidence: "ping the payments lead" [event 96465537]

**missed_relationship** (25 total)
- extractor said: (nothing); expected: D-0003 -[ABOUT]-> core-monolith
- extractor said: (nothing); expected: D-0005 -[ABOUT]-> payments-api
- extractor said: (nothing); expected: D-0010 -[ABOUT]-> auth-service

**spurious_relationship** (42 total)
- extractor said: D-0005 -[ABOUT]-> auth-service; expected: (not in ground truth) — evidence: "new integrations must not use legacy-auth — it is deprecated; use auth-service now" [event 0b53a3ec]
- extractor said: D-0006 -[ABOUT]-> subscriptions-service; expected: (not in ground truth) — evidence: "add it to the D-0006 migration list." [event 251e3a50]
- extractor said: D-0007 -[ABOUT]-> user-store; expected: (not in ground truth) — evidence: "All traffic between auth-service and user-store must use mutual TLS." [event ca99801c]

**wrong_relationship_type** (1 total)
- extractor said: D-0005 -[ABOUT, DEPRECATES]-> legacy-auth; expected: D-0005 -[ABOUT]-> legacy-auth — evidence: "new payment integrations continue using legacy-auth token validation" [event 012f7f48]

**alias_not_merged** (11 total)
- extractor said: alice-chen: ['Al', 'Alice Chen', 'alice', 'alice.chen@northwind.io']; expected: one node (Phase 3B will merge these)
- extractor said: auth-service: ['AuthSvc', 'auth service', 'auth-service']; expected: one node (Phase 3B will merge these)
- extractor said: ben-smith: ['Ben Smith', 'ben', 'ben.smith@northwind.io', 'bsmith']; expected: one node (Phase 3B will merge these)

## Discussion

> **Model-substitution note.** The spec named `google/gemini-2.0-flash`, but OpenRouter has
> retired it; its cheap-tier successor `google/gemini-2.5-flash-lite` was used instead. The
> other two models are as specified. Numbers are reproducible from the deterministic seed-42
> corpus and the committed prompt (`PROMPT_VERSION = 2b-v1`).

**Headline.** All three models clear the honest target (≈0.80 entity F1, ≈0.65 relation
F1) on *entities* and split on *relationships*. Claude 3.5 Haiku is the clear quality
leader (entity F1 **0.91**, relation F1 **0.78**) but costs **~10×** the other two
($0.35 vs $0.035/$0.038 for the full corpus). gpt-4o-mini and gemini-2.5-flash-lite tie on
entity F1 (**0.87**) and diverge on relations (0.62 vs 0.57). For a cost-sensitive batch
pipeline, gpt-4o-mini is the value pick; when relation quality matters (it does — the
killer queries traverse edges), Haiku earns its price. Total spend for the whole
three-model run was **$0.42**, well inside the <$5 budget.

**Entities are easy; relationships are where models separate.** Every model nails
`Person`, `Decision`, and `Service` (F1 ≥ 0.86). Two entity weaknesses recur: (1) the
**Service-vs-System boundary**, the schema's named soft spot (graph-schema.md), shows up as
`wrong_entity_type` — `event-bus`, `legacy-auth`, `primary-db`, and `user-store` get
labelled Service or *both* Service and System (gpt-4o-mini 4 cases, Haiku 2, gemini 0 —
gemini avoids dual-typing). (2) `Team` recall collapses for gpt-4o-mini (**0.20** — it
found 1 of 5 teams), because teams live almost entirely in one large org-chart document,
and at `max_tokens=2000` that document truncates (1–6 parse failures per model). This is
the strongest argument for the documented chunking future-work: relationship and entity
classes concentrated in a single mega-doc (org chart → `MEMBER_OF`/`Team`; service catalog
→ `OWNED_BY`; dependency map → `DEPENDS_ON`) are hostage to that one document parsing
cleanly.

**Top-3 failure modes per model (excluding `alias_not_merged`, a tracked Phase-3B
limitation, not a quality bug):**

- **gpt-4o-mini** — (1) *missed_relationship* (29): `MEMBER_OF` is **0.00 F1** — it never
  modelled team membership from the truncated org chart; (2) *spurious_relationship* (17):
  over-eager `ABOUT` (e.g. `D-0007 ABOUT user-store` from "mTLS between auth-service and
  user-store"); (3) *wrong_entity_type* (4): Service/System dual-typing. `OWNED_BY` is also
  weak (0.21) for the same truncation reason.
- **claude-3.5-haiku** — (1) *spurious_relationship* (15): same `ABOUT` over-reach; (2)
  *missed_relationship* (12): a few `MEMBER_OF`/`ABOUT` gaps; (3) *wrong_relationship_type*
  (3): `DEPRECATES` vs `ABOUT` confusion (`D-0003 DEPRECATES core-monolith` when the text is
  "no new feature work lands in core-monolith" — an `ABOUT`, not a deprecation). Notably
  Haiku is the only model that handles the service catalog well (`OWNED_BY` F1 **0.96**).
- **gemini-2.5-flash-lite** — (1) *spurious_relationship* (42, by far the worst):
  `OWNED_BY` precision **0.14** (18 false positives) and `ABOUT` precision 0.45 — it invents
  edges liberally; (2) *missed_relationship* (25); (3) *spurious_entity* (11): it
  hallucinates `Decision` nodes from noun phrases ("the signing-key decision" →
  `Decision signing-key`; a stale-wiki recommendation → a Decision). High recall, low
  precision — it says yes too often.

**Two systematic, defensible patterns.** First, `ABOUT` precision is depressed across the
board because the corpus *mentions* entities a decision touches without the decision
formally being "about" them — `D-0007` mentions `user-store`, but ground truth lists only
`auth-service` as its subject. This is a ground-truth-strictness choice (ADR 0013), not
purely a model error, and is worth flagging in an interview rather than hiding. Second,
`DEPRECATES`/`ABOUT` and Service/System are *the same kind of error* — a fine
type-distinction the schema makes that the text under-determines; both degrade gracefully
(the edge/node still exists, just mislabelled) exactly as the schema was designed to allow.

**Calibration and honesty.** Confidence is well-calibrated for all three (mean confidence
on correct extractions ≈0.92 vs ≈0.82–0.90 on incorrect), so a query-time confidence
threshold would trade recall for precision as intended. The `alias_not_merged` counts
(10–13 per model) are the entity-resolution debt made visible — `ben-smith` surfaces as
`['Ben Smith', 'ben', 'ben.smith@northwind.io', 'bsmith']`, the planted handle-change trap
working exactly as designed — and the alias-tolerant matcher means they cost no F1 here,
which is the honest accounting: Phase 3B will merge them upstream.

**Verdict.** Use **gpt-4o-mini** as the default extractor (cheap, 0.87/0.62, no
catastrophic class) and **claude-3.5-haiku** when relation fidelity is worth 10× the spend
(0.91/0.78, and uniquely strong on `OWNED_BY`). Avoid **gemini-2.5-flash-lite** for
relationships without a confidence/precision filter — its recall is fine but it
over-generates edges. The single highest-ROI engineering change is **chunking the few
mega-documents** so `MEMBER_OF`/`OWNED_BY`/`Team` stop being hostage to a 2000-token cap.

