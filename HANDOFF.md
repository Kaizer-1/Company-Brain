# HANDOFF — Company Brain

> **This file is overwritten at the end of every subphase.**
> Structure: Subphase → What was built → Decisions made → Deviations → Open questions → DoD check → Codebase state → Next subphase.
> Future sessions: read `CLAUDE.md` first, then this file.

---

## Subphase

Phase 6A — Demo Recording + README + Architecture Diagrams

## Date

2026-06-14

---

## What Was Built

Phase 6A is the packaging phase: converting completed engineering into artifacts a senior reviewer can evaluate in under two minutes.

### README.md — replaced entirely

The 79-line Phase-2B README is gone. The new README (~400 lines of prose + diagrams) has:
- One-sentence pitch + demo video placeholder (Loom link to fill in post-recording)
- Two Mermaid diagrams: architecture (component-level with subgraphs) + data flow (8-stage pipeline)
- "What it does" — 3 paragraphs explaining the thesis and the 4 killer queries
- "Capabilities" section with all headline numbers sourced to eval docs
- Screenshot gallery (4 images from `docs/screenshots/`)
- "How to run" with exact commands for a clean clone
- "Engineering artifacts" — catalog of all 35 ADRs, 13 design docs, 9 eval files, organised by phase
- "What this is not" — the honest limitations section naming 7 specific scope limits

### docs/diagrams/ — new directory

Created `docs/diagrams/README.md` explaining that diagrams are fenced Mermaid blocks in the README (GitHub renders natively) and how to export SVG with `mmdc` when available. `mmdc` was not available in this build environment; SVG export is deferred.

### .gitignore — updated

Added three entries (Decision 6.5):
- `docs/interview-prep/` — personal Q&A prep materials
- `HANDOFF.md` — internal phase-to-phase session notes
- `CLAUDE.md` — internal session memory

These files exist on local disk and should be moved to a private location before the repo is made public. The git rm --cached step is intentionally deferred to the operator (it's a destructive repo operation that belongs with the public-push step).

### docs/design/*.md — polished (all 13 docs)

Every design doc received:
1. **"What this doc is" framer** — a 1-paragraph prose explanation for a reader with no project context. Added as a paragraph after the existing status blockquote for docs that had status-only openers (entity-resolution, postgres-schema, frontend-architecture, graph-schema, query-engine). Docs with descriptive openers already (agent-architecture, agent-streaming, incremental-reconciliation, observability, structural-tools, extraction-pipeline, semantic-search, synthetic-company) left as-is.
2. **"Related ADRs" footer** — a `---\n## Related ADRs` section at the end of every doc, linking to the relevant ADRs with one-line descriptions.

### Verification block findings (documented here for future sessions)

- README was 79 lines (stale); demo script was 246 lines (current).
- 35 ADRs confirmed (0001–0035); template.md is not an ADR.
- Design docs: 13. Eval docs: 9. Interview-prep: 14 (private; in .gitignore).
- Graph node counts at start of 6A (drifted from pristine): Person=27, Service=20, Message=94, Decision=10, System=7, Team=6. Pristine baseline: Person=13, Service=12.
- No Mermaid CLI available; diagrams live as fenced blocks.
- Screenshots exist in `docs/screenshots/` (6 PNGs: graph, ask, ingest, audit1, audit2, search). Captured at drifted state. Re-seed before recording the demo.
- No TODOs/FIXMEs in docs (template.md XXXX placeholder is not a real TODO).

---

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Mermaid fenced blocks in README, not SVG export | `mmdc` not available; GitHub renders Mermaid natively; deferred SVG export documented in `docs/diagrams/README.md` |
| .gitignore entries for interview-prep + HANDOFF + CLAUDE.md | Decision 6.5: these are personal preparation materials, not public documentation |
| git rm --cached deferred to operator | Destructive repo operation belongs with the public-push step, not the packaging phase |
| framer added to 5 docs, left as-is for 8 docs with existing good descriptions | Light-touch polish; docs with descriptive openers didn't need a second framer |

---

## Deviations from Spec

1. **README is ~400 lines, not 700–1000.** The target was 700–1000 including diagrams. The Mermaid diagrams are large and the prose is tight, putting it at ~400. This is shorter than the spec but reads better. The spec's "long for a README; appropriate for a portfolio project" guidance was taken seriously but the content justified by what existed was ~400 lines. Increasing line count with filler would violate the "no marketing voice / no bullet soup" anti-pattern.

2. **Screenshots not re-captured at pristine baseline.** The 6 existing screenshots in `docs/screenshots/` are used as-is in the README. The graph is drifted (Person=27, not 13). Screenshots should be re-captured after re-seeding before the demo recording. The README references them without quoting node counts from the screenshots.

3. **Demo not recorded yet.** Loom recording is the one deliverable that requires the operator (it requires screen capture + microphone). The README has a placeholder comment. The demo script (`docs/demo/3-minute-walkthrough.md`) is current and complete; no edits were needed.

4. **CONTRIBUTING.md and FOR-INTERVIEWERS.md not created.** These were "optional but high-leverage" per the spec. Deferring to 6B or to the operator's judgment before publishing.

---

## Open Questions

1. **Loom recording still needed.** Re-seed the graph to pristine baseline (Person=13), re-capture the 4 screenshots, then record the demo following `docs/demo/3-minute-walkthrough.md`. Replace the placeholder comment in README.md with the real Loom link.

2. **git rm --cached for interview-prep / HANDOFF / CLAUDE.md.** When ready to make the repo public:
   ```bash
   git rm --cached -r docs/interview-prep/ HANDOFF.md CLAUDE.md
   git commit -m "Remove private prep materials from repo history"
   ```
   These files will remain on local disk (the .gitignore entry preserves them).

3. **SVG diagram export.** Install `mmdc` and run:
   ```bash
   npm install -g @mermaid-js/mermaid-cli
   # Extract architecture diagram (the first mermaid block in README)
   mmdc -i README.md -o docs/diagrams/architecture.svg
   ```

4. **Demo baseline drift.** The graph carries 5B test ingestions. Restore with:
   ```bash
   docker compose exec backend python -m app.synthetic.seeder
   docker compose exec backend python -m app.synthetic.extract_all
   ```

---

## Definition of Done Check

- ✓ README.md replaced: pitch, diagram, data-flow diagram, capabilities with numbers, 4 screenshots, how-to-run, artifacts index, "what this is not"
- ✓ docs/diagrams/ created with README explaining the Mermaid/SVG situation
- ✓ .gitignore updated with interview-prep + HANDOFF + CLAUDE.md
- ✓ All 13 design docs have Related ADRs footer
- ✓ 5 design docs with status-only openers now have "What this doc is" framer
- ✗ 4 screenshots at pristine baseline — not re-captured (existing screenshots used; re-capture before recording)
- ✗ 3-minute Loom recorded — not done (operator task; requires screen + audio)
- ✗ CONTRIBUTING.md / FOR-INTERVIEWERS.md — deferred as optional

---

## State of the Codebase

**Docs changed:**
- `README.md` — completely replaced
- `.gitignore` — 3 entries added
- `docs/diagrams/README.md` — new file
- `docs/design/*.md` (all 13) — Related ADRs footer + framer for 5 docs

**No code changes** — Phase 6A is documentation-only.

**Reference commit (5B baseline):** `8d60c1d` (from 5B HANDOFF; unchanged by 6A).

---

## Next Subphase

**Phase 6B — Deployment (optional).** The natural next step is making the repo public and deploying the stack to a cloud environment so the demo runs without a local Docker setup. Candidate: Railway.app or Render (both support multi-container Compose deployments). The README's "how to run" section needs a live URL. Alternatively, 6A is the final subphase for a portfolio submission and 6B remains deferred.

**Immediate operator tasks before 6A is fully done:**
1. Re-seed → `python -m app.synthetic.seeder && python -m app.synthetic.extract_all`
2. Re-capture 4 screenshots at pristine baseline
3. Record the Loom (3 minutes, follow `docs/demo/3-minute-walkthrough.md`)
4. Update README.md placeholder comment with the real Loom URL
