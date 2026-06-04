# Company Brain — 3-Minute Demo Walkthrough

> A literal script. Each beat has a target time. Practice it twice before using it.
> Total: 3 minutes. Do not go over.

---

## Setup (before the demo starts)

1. `docker compose up -d` — bring up the full stack.
2. Run the pipeline: `docker compose exec backend python -m app.synthetic.seeder && docker compose exec backend python backend/scripts/extract_all.py` (if a fresh run is needed).
3. Open `http://localhost:3000` in Chrome. Ensure the tab is full-screen or near-full-screen.
4. Start at `/` — the landing page.

---

## Beat 1: The Problem Statement (0:00–0:30)

> "Company Brain ingests scattered company knowledge — Slack messages, architecture
> decisions, meeting notes — and builds a self-updating knowledge graph you can query with
> typed traversals. The reason it's a graph and not a document search is these four queries
> here — each one requires something RAG can't do: multi-hop traversal, temporal reasoning,
> structural reachability. Let me show you."

- Point to the landing page — four queries listed, each with a "Why RAG fails" note.
- Don't dwell. Click `/graph`.

---

## Beat 2: The Graph (0:30–1:00)

> "Here's the resolved graph — 153 nodes. You can see decisions in amber, services in blue,
> people in green, systems in gray. This is after entity resolution — the pipeline had about
> 180 nodes before, because the same person shows up as 'Alice Chen', '@alice', and
> 'alice.chen@northwind.io'. The resolver collapsed those.

> Watch what happens when I switch to the fragmented view."

- Click "fragmented" in the sidebar toggle.

> "Those dashed lines — those are MERGE_INTO edges. Each one represents a resolution
> decision: the system decided these two nodes refer to the same entity. 25 of those in this
> run. The fragmented view shows the work; the resolved view is what the queries see."

- Click "resolved" to switch back.
- Hover one node (e.g., a Decision node). Show the sidebar: node type, canonical ID, source
  event count.

> "Every node traces back to the raw event that asserted it. I'll show that in a moment."

---

## Beat 3: The Killer Query (1:00–2:00)

- Click `/queries`. KQ1 is selected by default.

> "This is the query that demonstrates the value proposition. 'Who owns the service that
> depends on the system deprecated by Decision D-0006?' — that's a 4-hop traversal:
> Decision → deprecated System → dependent Service → owning Team → lead Person. RAG can't
> do this because it retrieves semantically similar chunks, not typed graph edges."

- Click "Run query".

> "The answer is Diego Ramirez. The graph traversal that produced it:"

- Point to the chain visualization: `D-0006 → legacy-auth → payments-api → payments → diego-ramirez`.

> "And here's the provenance — every event ID that asserted each edge in this chain."

- Click "Source events" to expand.
- Click one event UUID.

> "This is the raw source text — the ADR where 'payments-api depends on legacy-auth' was
> stated. The answer is grounded all the way down."

- Close the modal.

---

## Beat 4: The Audit Trail (2:00–2:45)

- Click `/audit`.

> "Every AI decision is logged. There are 25 resolution merges and around 490 no-merges in
> this run. Let me filter to Tier-2 LLM merges — these are the close cases where the
> deterministic rules didn't fire and the model had to judge."

- Set tier to "Tier 2", decision to "LLM merge".

> "11 LLM merges. Let me expand one."

- Click "Expand" on a row with reasoning.

> "The model says: 'Both refer to the same person — same team, same email domain, 92%
> embedding similarity.' That's the reasoning that produced the merge edge you saw as a
> dashed line in the graph. I can defend every choice the system made."

---

## Beat 5: The Closer (2:45–3:00)

- Return to `/`.

> "Full stack: Neo4j for the graph, Postgres for the event log and audit trail, FastAPI,
> React with react-force-graph-2d for the visualisation. Extraction ran through three LLMs
> for comparison — haiku had the best F1. The whole pipeline runs end-to-end in one
> `docker compose up`. Happy to go deeper on any piece."

---

## Notes

- If the interviewer wants to see KQ3 (blast radius): `/queries → KQ3 → service: payments-api → Run`. Answer: 10 services, 4 people, 1 decision. The blast radius at depth 2.
- If they ask about KQ2 (contradictions): `/queries → KQ2 → Run`. Answer: Decision D-0005 ("new integrations stay on legacy-auth through year-end") is contradicted by a Slack thread 22 days ago where @alice and @iris said "new work goes on auth-service now." No superseding decision exists — the graph exposed an undocumented policy change.
- If they ask why not RAG: the answer is in the KQ "Why RAG fails" annotations on the landing page, plus the interview-prep doc has 80-word explanations for each.
