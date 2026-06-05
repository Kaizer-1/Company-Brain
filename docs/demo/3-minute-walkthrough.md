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

## Beat 4: Semantic Search (2:00–2:30)

- Click `/search`.

> "The killer queries answer questions whose shape you know in advance. But what about
> 'what was the discussion about billing last month?' For that, there's hybrid search."

- Type "decisions about auth migration signing keys" in the search box. Hit Enter.

> "Five results in about 200ms — the D-0008 key-rotation ADR ranked first, the Slack
> messages about signing keys in the auth migration channel ranked second and third. The
> score breakdown: 0.7 weight on semantic similarity, 0.3 on how many graph entities this
> event asserted. Both signals together."

- Click "view source" on one result.

> "Same event modal as before — search results are grounded in the same provenance system."

- Close the modal.

---

## Beat 5: The Audit Trail (2:30–2:50)

- Click `/audit`.

> "Every AI decision is logged — resolution merges, LLM adjudications. Let me filter to
> Tier-2 LLM merges."

- Set tier to "Tier 2", decision to "LLM merge".
- Click "Expand" on a row.

> "Full reasoning for every merge. The audit trail shows the system's work, not just its
> output. I can defend every node in the graph."

---

## Beat 6: The Closer (2:50–3:00)

- Return to `/`.

> "Full stack: Neo4j, Postgres + pgvector, FastAPI, React. Entity resolution, killer-query
> traversals, semantic search — all in one `docker compose up`. Happy to go deeper."

---

## Notes

- If the interviewer wants to see KQ3 (blast radius): `/queries → KQ3 → service: payments-api → Run`. Answer: 10 services, 4 people, 1 decision.
- If they ask about KQ2 (contradictions): `/queries → KQ2 → Run`. Answer: D-0005 contradicted by Slack thread 22 days ago — an undocumented policy change exposed by the graph.
- For search: try "legacy-auth stale guide deprecated" or "event-bus Kafka async". Both return highly relevant results within 200ms.
- If they ask why not RAG: KQ "Why RAG fails" notes on landing page + phase-3d-readiness.md Q8 has the 80-word answer.
- If they ask about search eval: Recall@10=0.942, MRR=0.910. `docs/eval/phase-3d-search-results.md` has the numbers.
