# ADR 0001 — Monorepo Structure

## Status

Accepted

## Context

Company Brain has three distinct layers: a Python backend (FastAPI + Neo4j + Postgres), a React frontend, and a documentation/infrastructure layer (Docker Compose, ADRs, concept docs). We needed to decide how to organise these layers in source control before writing a single line of code, because the choice affects CI design, how contributors navigate the codebase, and whether cross-layer changes can be made atomically.

The project is maintained by a single developer (portfolio piece), so coordination cost between repositories is pure overhead. The backend and frontend are tightly coupled at the API contract boundary — every schema change in Phase 1B will touch backend models, frontend queries, and API docs simultaneously.

## Decision

Single monorepo with a flat directory structure: `backend/`, `frontend/`, `docs/`, `scripts/` under one repo root.

## Alternatives Considered

### Option A — Polyrepo (one repo per service)

**What it is**: `company-brain-backend`, `company-brain-frontend`, `company-brain-infra` as separate GitHub repositories.

**Pros**:
- Clean access control: can grant a contractor access to only one service
- Independent CI pipelines — a frontend-only change doesn't trigger backend tests
- Independent versioning and release cycles

**Cons**:
- Cross-layer changes (e.g., adding a new graph relationship that touches backend schema, frontend visualisation, and an ADR) require coordinating 2–3 PRs across repos, with no atomic commit
- Developer experience degrades: `git log` across the system is impossible; `git bisect` on a bug that spans layers is extremely painful
- For a one-person portfolio project, the coordination overhead is 100% cost, 0% benefit

### Option B — Monorepo with uv workspaces / sub-packages

**What it is**: A proper Python workspace where `backend/` is its own installable package with its own `pyproject.toml`, and the root `pyproject.toml` references it as a workspace member.

**Pros**:
- Cleaner dependency isolation — frontend deps don't pollute the backend lockfile
- More scalable to a real multi-service architecture

**Cons**:
- Adds tooling complexity for no current benefit: we have one backend service and one frontend (not yet built)
- uv workspace support, while good, adds a layer of indirection that would need to be explained in every new-developer onboarding doc
- Premature: the right time to introduce workspaces is when we have two independently deployable services with genuinely different dependency graphs

### Option C — Monorepo, flat structure (chosen)

**What it is**: Single `pyproject.toml` at the root, `backend/` and `frontend/` as directories, `docs/` at the root.

**Pros**:
- Atomic cross-layer commits — one PR can update backend code, frontend component, and the relevant ADR together
- Single CI pipeline; path filters can scope test runs
- Zero onboarding overhead for the directory layout
- `docs/` lives at the root and is always adjacent to the code it documents

**Cons**:
- As the project grows, a single `pyproject.toml` risks mixing concerns (backend Python deps alongside frontend build config)
- No access control granularity — but this is a portfolio project, not a real org

## Consequences

**Enables**: Atomic commits spanning all layers. Simple CI (one pipeline, path-filtered). Docs always co-located with code.

**Constrains**: Cannot easily give partial access to the repo. All components share a Python version pin.

**Locked into**: Migrating to a workspace structure later is straightforward (add workspace tables to `pyproject.toml`, split lockfiles) — this is not a deep lock-in.

**At larger scale / in production**: A real company would use a monorepo with workspace tooling (Nx for TypeScript, uv workspaces for Python) and path-filtered CI to avoid running all tests on every push. The flat structure chosen here would be the starting point before that split.

## Interview Defense

> "We chose a flat monorepo because the backend, frontend, and docs change together — every schema change touches all three layers. For a single developer, the coordination overhead of polyrepo is pure cost. The trade-off is coarser access control, which doesn't matter here. At real-team scale, we'd introduce uv workspaces and path-filtered CI but keep the single repo."
