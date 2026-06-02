# HANDOFF — Company Brain

> **This file is overwritten at the end of every subphase.**
> Structure: Subphase → What was built → Decisions made → Deviations → Open questions → DoD check → Codebase state → Next subphase.
> Future sessions: read `CLAUDE.md` first, then this file.

---

## Subphase

Phase 3A — Entity Resolution

## Date

2026-06-02

---

## What Was Built

### Design & decision docs

- **`docs/design/entity-resolution.md`** (~2700 words) — the full resolver rationale: the
  fragmentation problem with three concrete `ALIAS_GROUPS` examples, the three-tier decision
  logic (+ orchestrator pseudocode), O(n²) candidate generation and its blocking/ANN scaling
  path, the local-embedding strategy and per-type input formats, the Tier 1 rule list with
  per-rule false-positive risk, the Tier 2 adjudicator prompt (verbatim), the `MERGE_INTO` edge
  model, eval methodology, and honest limitations.
- **ADR 0014** — tiered-confidence resolution; `MERGE_INTO` over deletion; local
  sentence-transformers over a hosted embedding API; claude-3.5-haiku for adjudication.
- **ADR 0015** — every resolution attempt (merge *and* non-merge) recorded in a Postgres
  `merge_decisions` table; why Postgres not a Neo4j edge; seed for a Phase 6 review UI.

### Resolution module — `backend/app/resolution/` (8 files, mypy-strict clean)

- `models.py` — Pydantic DTOs (`ResolvableNode`, `CandidatePair`, `LLMVerdict`,
  `TypeBreakdown`, `ResolutionReport`) + `KEY_FIELD` map.
- `embeddings.py` — `BAAI/bge-small-en-v1.5` via sentence-transformers, lazy module-level
  singleton, `asyncio.to_thread`-friendly sync `embed_texts`; per-type `node_embedding_input`.
- `candidates.py` — `load_nodes` (reads non-merged nodes from Neo4j) + `generate_candidate_pairs`
  (O(n²) within type, cosine attached).
- `rules.py` — `AliasDictionary` (company + `ALIAS_GROUPS`, returns None on miss) and the Tier 1
  pure-function rules: `exact_email`, `exact_handle`, `exact_canonical_name`, `known_alias`,
  `former_name`.
- `adjudicator.py` — Tier 2 `Adjudicator` over the existing `OpenRouterClient`; verbatim prompt,
  `LLMVerdict` validation, safe no-merge fallback on any parse/call failure.
- `merger.py` — `pick_winner` (more `source_event_ids`; lexicographic tiebreak) + `Merger`:
  writes `MERGE_INTO`, unions provenance onto the winner (live-read Cypher so multi-merge
  winners accumulate correctly), tombstones the loser, records the audit row; `dry_run` writes
  nothing.
- `resolver.py` — `resolve_graph(driver, session, *, node_types, client, dry_run)` orchestrator;
  rule-match ⇒ Tier 1, else cosine ≥ 0.75 ⇒ Tier 2, else Tier 3.

### Database — `merge_decisions`

- `models/enums.py` — `NodeType`, `MergeDecisionType` enums. `models/resolution.py` — ORM model.
  `schemas/postgres.py` — `MergeDecisionCreate`/`MergeDecisionDTO`. `db/repositories/resolution.py`
  — append-only repo. Alembic `0002_merge_decisions` (idempotent enum + table + index;
  applied automatically by the backend lifespan — verified in Docker).

### Eval harness — `backend/app/eval/resolution_eval.py`

- `build_resolution_ground_truth()` from `ALIAS_GROUPS` (+ `LOOK_ALIKE_PAIRS` negatives);
  `seed_fragmented_graph` (deterministic, DB-only); `run_resolution_eval` (seed → resolve →
  union-find over `MERGE_INTO` → precision/recall/false-merge/missed-merge per type + tier
  breakdown); `render_resolution_report`.

### CLIs — `backend/scripts/`

- `resolve_entities.py` (`--node-type`, `--dry-run`) — resolves the live graph.
- `run_resolution_eval.py` (`--output`) — seeds, resolves, scores, writes the Markdown report.

### Tests — `backend/tests/resolution/` (38 new; **255 total pass**, 1 skipped)

- `test_rules`, `test_candidates`, `test_embeddings` (model-dependent tests skip gracefully),
  `test_adjudicator` (mock client + parse/fallback + real-API smoke that skips without a key),
  `test_resolution_eval` (ground-truth correctness + mock-perfect scores 1.0 + false-merge drops
  precision), `test_merger` (real Neo4j+Postgres), `test_resolver_integration` (real DBs; alias
  group collapses, audited, idempotent).

### Deps / docs

- `pyproject.toml` — `sentence-transformers>=3.0.0` (runtime); mypy override for
  `sentence_transformers.*`. Dockerfile unchanged (tomllib deps install picks it up; resolution
  dir sits under the already-copied `backend/app/`).
- CLAUDE.md (production-verification checklist + entity-resolution section + phase table +
  resequencing note), docs/README.md, interview-prep/phase-3a-readiness.md updated.

---

## Eval Results — the honest numbers

**Seeded eval** (`run_resolution_eval.py`; 25 nodes from `ALIAS_GROUPS` + `LOOK_ALIKE_PAIRS`):

| Scope | Precision | Recall | F1 | False-merge | Missed-merge |
|-------|-----------|--------|----|-------------|--------------|
| Overall | **1.00** | **1.00** | **1.00** | **0.00** | **0.00** |
| Person | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 |
| Service | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 |

33/33 true pairs recovered, all at Tier 1 (mean confidence 0.99). Tier 2 ran on 5 cross-group /
look-alike pairs and correctly declined all (`llm_no_merge`=5), incl. the
`notifications-api`/`notification-worker` look-alike. Tier 2 cost **$0.0031**; embeddings free.
Full report + hand-written Discussion: `docs/eval/phase-3a-resolution-results.md`.

**Honest caveat (in the report):** the `known_alias` dictionary is sourced from the same
`ALIAS_GROUPS` that defines ground truth, so this 1.00 proves the *machinery* is correct
end-to-end, not open-world alias discovery. The generalising recall lives in Tiers 2/3.

**Live-graph smoke** (`resolve_entities.py` on the real gemini-2.5-flash-lite extraction — 234
nodes): 627 candidate pairs → **39 merges** (28 Tier 1 auto + 11 Tier 2 LLM), 32 `llm_no_merge`,
556 `below_threshold`; 39 `MERGE_INTO` edges; 23 nodes tombstoned; $0.03. Confirms scale and
that Tier 2 carries weight once the dictionary stops covering everything (11/39 merges).

---

## Decisions Made

| ADR | Decision |
|-----|---------|
| [0014](docs/decisions/0014-entity-resolution-tiered-confidence.md) | Three-tier resolution; MERGE_INTO over deletion; local sentence-transformers over hosted embeddings; claude-3.5-haiku adjudicator |
| [0015](docs/decisions/0015-merge-decisions-audit-table.md) | Every resolution attempt recorded in Postgres `merge_decisions`; not a Neo4j edge |

Key in-code call: **a deterministic Tier 1 rule auto-merges regardless of cosine** (exact
identity is definitional; a 384-dim embedding does not get to veto a shared email or a curated
alias). Cosine only routes the *no-rule* pairs. This is a deliberate simplification of the
spec's "cosine ≥ 0.95 AND corroboration" — see Deviations.

---

## Deviations from Spec

1. **Phase numbering.** The prompt defined this subphase as "Phase 3A: Entity resolution," but
   the prior CLAUDE.md table had 3A = "Multi-hop Traversal" and HANDOFF's "next" said
   "second-source ingestion + temporal edges." Entity resolution was the right thing to build
   next (the 2B fragments block every killer-query traversal), so 3A is now **Entity Resolution**;
   the traversal/temporal work folds into **3B**. Recorded in CLAUDE.md's resequencing note.
2. **Tier 1 gate.** Spec phrased Tier 1 as "cosine ≥ 0.95 AND a corroborating signal." We
   auto-merge on **any exact rule match, independent of cosine**, because a nickname ("Al") can
   embed below 0.75 against "Alice Chen" and gating the definitional rule on similarity would
   wrongly demote it to the costly/fallible LLM tier. Cosine is recorded on every audit row and
   governs only the no-rule pairs (Tier 2 vs Tier 3 at the 0.75 floor). Documented in the design
   doc and ADR 0014.
3. **Eval seeds its own fragmented graph** (deterministic, from `ALIAS_GROUPS`) rather than
   resolving whatever a prior extraction left — same reproducibility rationale as 2B's
   generator-derived corpus (ADR 0013). The live extracted graph is exercised separately by the
   smoke.

---

## Open Questions

1. **Dictionary-independent recall is unmeasured.** Because `known_alias` is sourced from the
   ground-truth narrative, the eval cannot show recall on aliases the dictionary does not know.
   A future eval should hold out a fraction of surface forms from the dictionary and measure how
   many Tiers 2/3 recover.
2. **Tier 2 over-extraction on the live graph.** 11 LLM merges + 32 LLM no-merges on real data:
   spot-check these for correctness when 3B's traversals expose any wrong merges, and consider a
   confidence floor on `llm_merge` before it writes an edge.
3. **`ABOUT`/cross-type fuzziness untouched.** Service↔System resolution (is `legacy-auth` a
   System or a Service?) is still out of scope; revisit if 3B traversals trip over it.
4. **Transitive merges.** Multi-hop `MERGE_INTO` chains are recorded but not collapsed to a
   single canonical walk; union-find in the eval handles grouping, but query-time resolution in
   3B should decide whether to follow `MERGE_INTO` transitively or rely on `status<>'merged'`.

---

## Definition of Done Check

- ✓ `docs/design/entity-resolution.md` ~2700 words; all required sections; adjudicator prompt verbatim
- ✓ ADRs 0014 and 0015 written per template
- ✓ Alembic `0002_merge_decisions` table created (enum + index); applied by lifespan in Docker
- ✓ `backend/app/resolution/` — all 8 files; mypy strict clean (66 source files)
- ✓ Resolution runs from CLI; produces `MERGE_INTO` edges + `merge_decisions` rows (and `--dry-run`)
- ✓ Eval harness runs end-to-end; report generated with honest numbers + hand-written Discussion
- ✓ `uv run pytest` — **255 passed, 1 skipped** (217 prior + 38 new); incl. real Neo4j+Postgres testcontainers
- ✓ `uv run mypy backend/` strict, clean; `ruff check` clean on all new files
- ✓ Targets met: false-merge rate 0.00 (≤ target), recall 1.00 (≥ 0.80 target) on the seeded eval
- ✓ Interview-prep doc: 10 Q&A + 5 whiteboard concepts
- ✓ Production verification (clean Docker rebuild): deps (`sentence_transformers 5.5.1`,
  `torch 2.12.0`) ✓; dir `/app/app/resolution` ✓; env N/A; smoke (seed→extract→resolve →
  39 `MERGE_INTO`, `merge_decisions` rows for merges *and* below-threshold) ✓
- ✓ CLAUDE.md, HANDOFF.md, docs/README.md updated

---

## State of the Codebase

**Works**: 255 tests pass; mypy strict-clean; ruff-clean on new files. The resolver walks the
Neo4j graph, merges duplicates with reversible `MERGE_INTO` edges (provenance unioned onto the
winner, loser tombstoned `status='merged'`), and audits every decision in Postgres
`merge_decisions`. Three tiers: deterministic rules (free), claude-3.5-haiku adjudication
(ambiguous band only), no-merge. Local `bge-small` embeddings. Verified end-to-end against a
clean Docker rebuild (backend image includes PyTorch CPU, ~picked up automatically from
`pyproject.toml`).

**Resolution is on-demand** (`resolve_entities.py`), never at startup. It is post-merge this
phase; the module is built to be called from the at-write-time path in Phase 4.

**Does not exist yet**: query engine / killer-query Cypher (3B), temporal-edge population (3B),
blast radius (3C), semantic search (3D), agent layer (4), frontend (4B). At-write-time
resolution and a human-review UI over `merge_decisions` are deferred (Phase 4 / 6).

---

## Next Subphase

**Phase 3B — Query engine + temporal edges.** Implement the four killer queries as validated
Cypher over the now-resolved graph (filter `WHERE n.status <> "merged"`), starting with KQ1
multi-hop ownership and KQ3 blast radius (which need clean, merged nodes — now available). Carry
forward: populate the temporal edge properties (`valid_from`/`valid_to`/`deprecated_at`) the
schema reserves so KQ2/KQ4 have data to filter on; evaluate "last month"/"last quarter" windows
relative to `REFERENCE_NOW`; and chunk the mega-docs (still ~11 parse failures on the full
extraction) before relying on `MEMBER_OF`/`OWNED_BY` recall. Spot-check the live-graph Tier 2
merges (Open Question #2) as traversals expose any wrong merges.
