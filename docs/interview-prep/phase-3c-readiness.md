# Phase 3C — Frontend Interview Readiness

> **Status**: Locked in Phase 3C.
> Prerequisite reading: `docs/design/frontend-architecture.md`, `ADR 0020`.

---

## 10 Q&A pairs (≥80 words each)

---

### Q1: Why react-force-graph-2d over D3-from-scratch?

**A**: `react-force-graph-2d` wraps the same d3-force simulation engine that I would use
if writing from scratch, but it handles the React integration and re-render lifecycle. Writing
a force-graph component from D3 scratch requires ~400 lines of imperative code: manual
SVG/canvas setup, selecting nodes and links, binding simulation tick handlers to DOM updates,
managing zoom behaviour, and handling React's reconciliation against a mutable d3 simulation.
`react-force-graph-2d` gives me all of that with a declarative API and two escape hatches I
actually use: `nodeCanvasObject` for custom-painted circles with node-type colors, and
`linkCanvasObject` for overriding MERGE_INTO edges with dashed lines.

The thing I lose is fine-grained control over the simulation physics — but the demo graph
has ~150 nodes, so default force parameters with `cooldownTicks=100` settle it in 2–3
seconds. If I needed a custom layout algorithm (e.g., hierarchical for the Decision→System
traversal chain), I would add a custom force with `d3Force('hierarchy', ...)` through the
library's exposed simulation, which is still available.

---

### Q2: How does the "before/after entity resolution" toggle work?

**A**: The toggle switches the API request between `GET /api/graph?view=resolved` and
`GET /api/graph?view=fragmented`. The backend has two different Cypher queries behind those
views.

**Resolved view**: `MATCH (n) WHERE NOT (n:_Migration) AND coalesce(n.status, 'active') <> 'merged'`
— filters out tombstoned nodes. Edge query excludes `MERGE_INTO` edges entirely.

**Fragmented view**: `MATCH (n) WHERE NOT (n:_Migration)` — returns everything, including
nodes with `status='merged'`. The edge query includes MERGE_INTO edges, and each edge has
`is_merge_into: true` flagged in the response.

On the frontend, `linkCanvasObject` checks `link.is_merge_into` and draws those edges as
dashed gray lines — `ctx.setLineDash([4, 4])`, stroked separately. The sidebar shows
explanatory text: "dashed lines show MERGE_INTO edges — entity resolution collapsed these
fragments into canonical nodes." The punchline is the count: in the live run, 25 resolution
merges happened. The toggle makes that work visible as a structural before/after comparison,
not as a number in a stats grid.

---

### Q3: Why does the audit trail get its own page?

**A**: Entity resolution uses an LLM for Tier-2 adjudication — every close-but-not-obvious
pair goes to `claude-3.5-haiku` with a verbatim prompt and a `{contradicts: bool, confidence,
reasoning}` output. Without an audit trail, the claim "I built a knowledge graph with entity
resolution" has the same depth as "I used ChatGPT to clean the data." The audit page makes
the claim specific: here are the 25 pairs that were resolved, here are the 11 LLM merges with
their reasoning, here are the 6 LLM no-merges where the model said "these are different
services." An interviewer can filter to Tier-2 LLM merges and read exactly what the model
said about `notifications-api` vs `notification-worker` (different — one accepts requests, one
processes jobs) and about Alice's aliases (same person — same email domain, same team). That
is the difference between a system and a script, and the audit page is where you show it.

---

### Q4: How does provenance flow from Postgres → API → frontend display?

**A**: Every graph node carries `source_event_ids` — a list of Postgres `events` UUIDs that
the extraction pipeline wrote to Neo4j as part of the `MERGE` write. Every relationship
carries a `source_event_id` — the single event where that relationship was extracted.

The query engine collects these into a `QueryProvenance` object keyed by element handle
(e.g., `"edge:DEPRECATES:D-0006->legacy-auth"`) with the event UUIDs as values. The FastAPI
endpoint serialises the full `QueryResult[T]` — answer plus provenance — as JSON.

On the frontend, the `ProvenanceSection` component receives `data.provenance.all_event_ids`
(the flat de-duplicated list) and renders it as a collapsible section. Each event ID is a
`<button>` that opens an `EventModal`. The modal calls `GET /api/events/{event_id}`, which
queries Postgres and returns the full raw event row — the original Slack message or ADR text
that the extraction pipeline read when it produced that graph element. The user can go from
"Diego Ramirez owns payments-api" all the way back to the raw text that asserted the
`OWNED_BY` edge. That chain is unbreakable: `source_event_ids` is a write-time invariant
enforced by `graph_writer.py`, and the integration eval validates it end-to-end.

---

### Q5: How would you scale the graph view past 1000 nodes?

**A**: The current approach — return all nodes and edges, let the browser simulate them —
breaks down around 500–800 nodes for two reasons: (1) the force simulation runs in
JavaScript on the main thread, and (2) `react-force-graph-2d` renders every node every tick,
even off-screen ones.

The fixes, in order of implementation effort:

**First**: Add viewport-based culling. `react-force-graph-2d` exposes `nodeVisibility` and
`linkVisibility` callbacks. Nodes outside the current viewport (with a margin) can return
`false` — they're skipped by the renderer. This keeps the simulation running globally but
only paints visible nodes. Effective up to ~2000 nodes.

**Second**: Change the API shape. Instead of returning all nodes, `GET /api/graph` returns
a summary (node counts by type, cluster membership). A second call expands a specific
cluster or starting node. This is the "ego graph" pattern: seed a node, return its N-hop
neighbourhood, let the user navigate by clicking through. The backend already has the
traversal infrastructure for this via the KQ3 blast-radius Cypher.

**Third**: For very large graphs (10K+ nodes), switch from force layout to a precomputed
layout (e.g., `d3-hierarchy` for the DAG structure, or UMAP projection of node embeddings).
The force simulation stops being useful at scale because it can't find a good layout in
finite time. A precomputed layout removes the ticking entirely.

**Never**: virtualize the canvas with a React list. The canvas is not a DOM list; culling is
done by not calling `ctx.draw*` for off-screen nodes, not by list virtualization.

---

### Q6: Why dark mode default? Why not light mode?

**A**: The project is a developer tool that will be demo'd in a browser, likely in a dark IDE
or terminal context. A light-mode-default with `#F8FAFC` backgrounds creates a jarring flash
when switching contexts. More practically: the graph canvas renders on a `#0C0E12` background
by `react-force-graph-2d`'s `backgroundColor` prop — that's a hard constraint. A
light-mode-first page with a dark canvas inset would look incoherent.

The deeper reason is the same one Linear, Vercel, and GitHub's code view use dark mode as
default: data-dense technical UIs read better on dark backgrounds because the eye is drawn
to the data (lighter text, colored badges, the graph nodes) rather than to the background.
Negative space in dark UI is actually negative space; in light UI, the background competes
with the content.

Light mode is technically supported (the CSS variables allow it) but is not in scope for the
demo. A production system would implement a system-preference toggle.

---

### Q7: Walk me through what happens when I click "Run query" for KQ1.

**A**: Starting from the UI state:

1. The user has selected KQ1 in the left sidebar and entered `D-0006` in the decision ID
   input. `triggered` state is `false`.

2. User clicks "Run query". The `handleRun` function sets `triggered = true`. This mounts the
   `<QueryResult>` component for the first time.

3. `<Kq1Result>` mounts and calls `useQuery({ queryKey: ['kq1', 'D-0006'], queryFn: () => fetchKq1('D-0006'), staleTime: 0 })`. TanStack Query sees no cached data for this key and fires the fetch.

4. `fetchKq1` calls `GET /api/queries/multihop-ownership?decision_id=D-0006`. In the Docker
   compose stack, this goes to nginx, which proxies it to `http://backend:8000/api/queries/multihop-ownership`.

5. FastAPI's `multihop_ownership` handler checks the Decision node exists, then calls
   `find_chain_owner(driver, decision_id='D-0006')`. This runs a 4-hop Cypher traversal over
   the resolved graph (nodes with `status != 'merged'`).

6. The Cypher returns rows for each chain. The Python code builds a `QueryResult[ChainOwnerAnswer]`
   with the owner people, the chain nodes, and provenance keyed by edge. FastAPI serializes
   this to JSON.

7. The frontend receives `{ value: { owner_people: ['diego-ramirez', 'hassan-mehta'], chains: [...] }, provenance: { all_event_ids: [...] } }`. TanStack Query caches it with key `['kq1', 'D-0006']`.

8. `<Kq1Result>` renders: the answer headline ("Owner: diego-ramirez, hassan-mehta"), the
   chain visualization (`D-0006 → legacy-auth → payments-api → payments → diego-ramirez`),
   and the collapsible provenance section. The chain viz is just a `flex` row of `<span>`
   badges separated by `<ChevronRight>` icons.

9. The user can click any event UUID in the provenance section to open the `EventModal`, which
   fetches the raw source text from `GET /api/events/{id}`.

Total time for a live backend with a warm graph: ~200–400ms.

---

### Q8: The `QueryResult[T]` type has generic provenance on every query. Why not make it optional?

**A**: The provenance is the thesis. The demo's claim isn't "the graph can answer questions";
it's "the graph can answer questions *and show you exactly what it's based on*." If provenance
is optional, it gets omitted when it's inconvenient — typically on the queries where it's
most load-bearing (KQ1's 4-hop chain, KQ4's approver attribution). Making it non-optional
in the Pydantic `QueryResult[T]` model (ADR 0018) means the integration eval can always
validate that every event ID in `all_event_ids` exists in Postgres. A missing event UUID is
a test failure, not a silent omission. This is the same discipline as the `evidence_quote`
field in the extraction output: if you make the grounding optional, you get an ungrounded
system.

---

### Q9: Why does the Audit page load all rows into Python and slice there, rather than pushing pagination into SQL?

**A**: The demo corpus has at most ~500 `merge_decisions` rows (25 resolution merges from
the live run, plus 490 below-threshold and no-merge records). Loading 500 small rows from
Postgres takes ~5ms. The benefit of loading all rows in Python is that the `total` count
in the `MergeDecisionPage` response is always the count for the *filtered* set — tier=2
with decision=llm_merge returns `total=11` not `total=525`. This matters for the UI: the
page indicator shows "1–11 of 11" not "1–11 of 525."

A production system with millions of audit rows would push the total count into SQL
(`COUNT(*) OVER ()` window function or a separate `SELECT COUNT` with the same WHERE clause),
then do `LIMIT/OFFSET` in Postgres. The current approach names this limitation explicitly in
the code comment in `audit.py` rather than hiding it. For a 500-row table, the Python slice
is correct and simpler.

---

### Q10: What would you add if you had one more week on the frontend?

**A**: Three things in priority order.

**First, real-time graph updates**: the backend's ingestion pipeline is on-demand (run via
CLI), but the demo would be more compelling if you could watch the graph change as new events
are ingested. This would require either a WebSocket endpoint from the backend or a polling
`refetchInterval` in TanStack Query. The frontend architecture already supports this — the
`staleTime: 30_000` on the graph query could be reduced to 5s or replaced with a WebSocket
subscription. The backend would need a `POST /api/ingest` endpoint and a graph-change
notification channel.

**Second, the ego-graph navigation pattern**: clicking a node in the graph should offer
"expand neighbourhood" — fetch the N-hop subgraph from that node and highlight it. This
would let a demo viewer start at `payments-api`, click "expand 2 hops," and see exactly the
blast radius KQ3 returns, but interactively in the graph. The API would need a
`GET /api/graph/neighbourhood?node_id=X&hops=2` endpoint, which is a simple Cypher
parameterized query.

**Third, the `/graph` page on mobile**: the current force graph is desktop-only (canvas
sizing requires explicit dimensions). A responsive sidebar → bottom sheet pattern and
touch-based panning/zooming would make the demo accessible on a phone, which matters if
someone is browsing the portfolio on mobile.

---

## 5 Whiteboard concepts

### WB1: The entity-resolution data model (non-destructive merges)

Draw: two `Person` nodes (Alice, alice-alias) connected by a `MERGE_INTO` edge to a third
canonical `Person` node. Show `status='merged'` on the losers, `status='active'` on the
winner. The key points:
- Why non-destructive: the merger is reversible (a wrong merge can be undone by deleting the
  edge and clearing the status), and it keeps the audit trail — the loser nodes preserve their
  `source_event_ids`.
- Why `WHERE n.status <> 'merged'` in every KQ: the resolved view is a filter, not a
  different graph. The fragmented view drops the filter.
- The projection step: 3A's merger does not migrate schema edges from losers to winners. The
  `projection.py` cleanup copies them after resolution so the resolved view is edge-complete.

### WB2: The provenance chain for KQ1

Draw the full chain: `Decision(D-0006)` → `[DEPRECATES]` → `System(legacy-auth)` ← `[DEPENDS_ON]` ← `Service(payments-api)` → `[OWNED_BY]` → `Team(payments)` ← `[MEMBER_OF]` ← `Person(diego-ramirez)`. 
Each edge has a `source_event_id`. Show how the Cypher collects these into `dep_evt`, `dependson_evt`, `owned_evt`, `member_evt`, and how `QueryProvenance.add()` groups them by element key. The frontend receives `all_event_ids` as a flat list; clicking one fetches the raw event from Postgres.

### WB3: The contradiction detection data path

Draw the pipeline order: `seed → extract → resolve → consolidate → project → enrich temporal → ingest messages → detect contradictions → query`. 
Emphasize the ordering constraint: temporal enrichment must run before contradiction detection because the detector filters candidates on `d.status = 'active'`, and enrichment is what sets that status. The live run caught this: running detection before enrichment gave 0 contradictions (19 candidates with raw status instead of 23 with normalized). This is exactly the class of bug that unit tests miss (both layers correct; the seam is wrong) and end-to-end integration tests catch.

### WB4: The nginx proxy pattern for Docker compose

Draw: `Browser → localhost:3000 → nginx container → [static SPA] OR [proxy /api/* → backend:8000]`. 
The SPA uses empty `VITE_API_BASE`, so all fetch calls are relative: `fetch('/api/graph')`. In the Docker compose network, `backend` resolves to the backend container. In Vite dev mode, the `proxy` config in `vite.config.ts` does the same thing on `localhost:5173`. One `VITE_API_BASE=""` setting covers both environments.

### WB5: TanStack Query cache key design

Draw the key factory pattern:
```
queryKeys.graph('resolved')   → ['graph', 'resolved']
queryKeys.kq1('D-0006')       → ['kq1', 'D-0006']
queryKeys.audit({ tier: 2 })  → ['audit', { tier: 2 }]
```
Explain why this matters: `staleTime: 30_000` on graph means switching view triggers a
fresh fetch because `['graph', 'fragmented']` is a different key from `['graph', 'resolved']`.
`staleTime: 0` on query results means clicking "Run query" always refetches even if the same
decision_id was used before — intentional for a demo where the graph may have changed. `staleTime: Infinity` on events (immutable) means the event modal never re-fetches the same UUID. This is intentional cache-policy differentiation, not a default.
