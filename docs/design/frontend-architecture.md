# Company Brain — Frontend Architecture (Phase 3C)

> **Status**: Locked in Phase 3C.
> ADR reference: [ADR 0020](../decisions/0020-frontend-design-philosophy.md) (design philosophy).
> Source: `frontend/`.

---

## 1. What this frontend is and what it is not

This is a **demo frontend** for a portfolio project. Its job is to make the backend's
capabilities visible in a 3-minute walkthrough, not to serve real users. There is no
authentication, no user management, no real-time features, and no production hardening.
These are named constraints, not deferred work.

The four pages exist to answer one question that every recruiter or interviewer has when
looking at a portfolio project: *so what?* The landing page states the claim. The graph
page makes entity-resolution work visible. The queries page proves the claim with a single
button press. The audit page proves the claim is defensible.

---

## 2. Technology stack

| Concern | Choice | Rationale |
|---------|--------|-----------|
| Bundler + dev server | Vite 6 | Fast HMR, first-class TypeScript, no config overhead |
| UI framework | React 18 (strict mode) | Industry standard; `react-force-graph-2d` has a React wrapper |
| Routing | React Router v6 | Lightweight, file-based routes without framework overhead |
| Data fetching | TanStack Query v5 | Declarative server state, `staleTime`, deduplication, devtools |
| Graph rendering | react-force-graph-2d | WebGL-accelerated 2D force simulation; canvas API for custom rendering |
| Styling | Tailwind CSS 3 (customized) | Utility-first, small production bundle; theme extension for project tokens |
| Testing | Vitest + React Testing Library | Fast, Jest-compatible; RTL tests components as users see them |
| Language | TypeScript strict | `noImplicitAny`, `strictNullChecks`, `noUnusedLocals` — same discipline as backend |

**Why not shadcn/ui?** See ADR 0020. Short version: unchanged shadcn is a visible AI tell at
this point. The primitives needed (Button, Badge, Skeleton, ProgressBar) are each under 30
lines of TSX; writing them proves the skill, using shadcn hides it.

**Why react-force-graph-2d not D3-from-scratch?** D3-from-scratch for a force layout with
custom rendering requires ~400 lines of imperative canvas code plus lifecycle management.
`react-force-graph-2d` wraps the same simulation engine behind a declarative API; the
`nodeCanvasObject` and `linkCanvasObject` escape hatches provide the control needed for
custom colors and dashed MERGE_INTO edges without the boilerplate. The result is smaller,
easier to reason about, and still shows force-simulation and custom canvas rendering skills.

---

## 3. The four pages and their jobs

### `/` — Landing

Single-column layout, `max-width: 720px`, left-aligned. Explains what Company Brain is in
three paragraphs, then lists the four killer queries as items with "Try it" links. No hero.
No stats grid. No marketing copy. The page exists so a recruiter has something to read; the
data pages are where they'll spend their time.

### `/graph` — Live graph

Full-page force graph canvas with a 320px right sidebar. The sidebar has:

- **View toggle**: resolved/fragmented. Resolved shows only canonical nodes
  (`status != 'merged'`), no MERGE_INTO edges. Fragmented shows everything, with MERGE_INTO
  edges rendered as dashed gray lines. This is the demo punchline for entity resolution —
  the system collapsed 25 pairs in the live run into canonical entities.
- **Counts by type**: monospace node counts per label.
- **Node detail on hover/click**: type, canonical_id, source event count; click-to-expand
  source events; click an event ID to open the source text modal.

The graph is the most expensive page (force simulation on canvas). `cooldownTicks=100`
and `warmupTicks=20` ensure it settles in 2–3 seconds without drifting.

### `/queries` — KQ explorer

Two-pane layout. Left sidebar lists the four killer queries; selecting one updates the right
pane. The right pane has:

1. The natural-language question.
2. Parameter inputs (defaults pre-filled: `D-0006` for KQ1, `payments-api` for KQ3, etc.).
3. A "Run query" button — real button, fires on click, disabled while loading.
4. The answer, prominently typeset.
5. A provenance chain visualization: `D-0006 → legacy-auth → payments-api → diego-ramirez`.
6. A collapsible "Source events" section with clickable event IDs.

Query results are `staleTime: 0` so they always refetch — the demo is interactive, not
cached. Graph data uses `staleTime: 30_000` since it changes only when the pipeline reruns.

### `/audit` — Merge-decision audit trail

Filterable table of `merge_decisions`. Columns: tier, decision badge, node type,
source→target node IDs, embedding similarity, expandable LLM reasoning, created timestamp.
Filter controls for tier (1/2/3), decision type, and node type.

The purpose of this page is to make the claim "every AI decision is logged and auditable"
visually real. An interviewer can filter to Tier-2 LLM merges, read the reasoning, and see
which pairs were merged vs rejected.

---

## 4. Data-fetching strategy

All API calls go through TanStack Query. The key shape:

```typescript
queryKey: queryKeys.graph(view)        // ['graph', 'resolved']
queryFn:  () => fetchGraph(view)
staleTime: 30_000                       // graph doesn't change in a demo session
```

For query results:
```typescript
queryKey: queryKeys.kq1(decisionId)   // ['kq1', 'D-0006']
queryFn:  () => fetchKq1(decisionId)
staleTime: 0                           // always fresh
```

Loading states are communicated with a thin 2px progress bar at the top of the page (not
spinners — the convention established by GitHub, Linear, and similar tools for non-blocking
loads). Skeleton blocks fill structural space while graph and query panels load.

Error states display the actual API error (status code + message), not a generic "something
went wrong." The user is technical; they can act on a real error message.

---

## 5. Styling conventions

The design follows the **software-tools aesthetic** (Linear, Vercel dashboard, Retool): dark
mode by default, neutral palette, monospace where it earns the slot, information-dense without
being cluttered. See ADR 0020 for the full rationale.

**Color palette** — 7 design colors, all in `tailwind.config.js`:

| Token | Hex | Usage |
|-------|-----|-------|
| `bg` | `#0C0E12` | Page background |
| `surface` | `#131720` | Panel/card backgrounds |
| `s2` | `#1B2131` | Hover/active states |
| `border` | `#252D3D` | Dividers |
| `txt` | `#E2E8F0` | Primary text |
| `txt-muted` | `#64748B` | Labels, secondary text |
| `accent` | `#3B82F6` | Action color (links, buttons, focus rings) |

Node colors are additional tokens under `node.*` — desaturated and accessible on dark
backgrounds (amber for Decision, blue for Service, gray for System, green for Person,
lavender for Team, slate for Message).

**Typography** — Inter (sans) + JetBrains Mono (monospace). The base font size is 14px
(`text-base`), smaller than Tailwind's default 16px, consistent with the density of tools
like Linear. Monospace is used only for: IDs, timestamps, event UUIDs, code-like data.
Never for prose.

**No gradient backgrounds, no glass morphism, no centered hero sections.** These anti-patterns
are explicit violations documented in ADR 0020.

---

## 6. How the frontend talks to the backend

In development (Vite dev server), a proxy rule in `vite.config.ts` forwards `/api/*` to
`http://localhost:8000`. In the Docker compose stack, nginx proxies `/api/*` to
`http://backend:8000` using the Docker Compose internal network. The SPA always uses
relative paths (`/api/...`), so `VITE_API_BASE` is empty in both modes.

**API surface consumed:**

| Endpoint | Page | Stale time |
|----------|------|-----------|
| `GET /api/graph?view=resolved\|fragmented` | /graph | 30s |
| `GET /api/queries/multihop-ownership` | /queries KQ1 | 0 |
| `GET /api/queries/contradictions` | /queries KQ2 | 0 |
| `GET /api/queries/blast-radius` | /queries KQ3 | 0 |
| `GET /api/queries/change-tracking` | /queries KQ4 | 0 |
| `GET /api/events/{id}` | event modals (all pages) | ∞ (immutable) |
| `GET /api/audit/merge-decisions` | /audit | 30s |

---

## 7. What would change for a production version

This is a demo frontend against a synthetic dataset. A production version would need:

1. **Authentication** — JWT or session auth, protecting all API routes. The current CORS
   config allows only `localhost:3000` and `localhost:5173`; a production deployment would
   lock it to the real origin.

2. **Real-time updates** — The graph and query results are manually fetched. A production
   system with live ingestion would add WebSocket or SSE notifications so the graph
   auto-updates when new events arrive. TanStack Query's `refetchInterval` is the first step;
   a WebSocket subscription is the proper solution.

3. **Pagination for the graph** — The current `/api/graph` endpoint returns all nodes and
   edges. At >1000 nodes the force simulation degrades. A production graph view would need
   either progressive loading (expand from a seed node) or a different visualisation strategy
   (cluster/aggregate view at low zoom, detail at high zoom). `react-force-graph-2d`'s
   `nodeVisibility` and `linkVisibility` callbacks enable viewport-based culling.

4. **Multi-tenancy** — Each team or organization would have its own graph. The current backend
   has no tenant concept; all nodes are in one Neo4j database.

5. **Error boundaries** — The current pages have inline error states but no React error
   boundaries for unexpected runtime exceptions. A production app needs `ErrorBoundary`
   components around each major panel.
