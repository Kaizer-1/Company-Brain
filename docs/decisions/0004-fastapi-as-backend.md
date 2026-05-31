# ADR 0004 — FastAPI as Backend Framework

## Status

Accepted

## Context

We need an HTTP API framework for the Python 3.12 backend. The API will serve graph query results (multi-hop traversal responses), accept ingestion webhooks, and expose a health check. The framework must support async I/O natively: both the Neo4j Python driver (5.x async) and SQLAlchemy 2.x are built on asyncio, and we cannot block the event loop during database calls without defeating the purpose of the async stack.

Secondary requirements: Pydantic v2 integration for request/response validation (we use Pydantic everywhere), auto-generated OpenAPI docs, and testability via dependency injection.

## Decision

FastAPI 0.115+, over Flask and Django REST Framework.

## Alternatives Considered

### Option A — Flask

**What it is**: Minimal synchronous Python web framework with a large extension ecosystem.

**Pros**:
- Extremely simple mental model; minimal framework magic
- Huge community; most Python web developers already know it
- Flask extensions exist for almost everything

**Cons**:
- **Sync-first architecture**: Flask's request handlers run synchronously by default. Running async Neo4j and SQLAlchemy calls from a Flask handler requires either: (a) a thread pool executor (asyncio.run_until_complete in a sync context — messy), or (b) Flask's experimental async support via asgiref. Neither is as clean as a natively async framework
- **No native type hint integration**: request/response validation requires marshmallow or WTForms; there is no first-class Pydantic support. We would write duplicate schemas: one for Pydantic (used in DB layer) and one for Flask's validation layer
- **No auto-generated docs**: OpenAPI docs require flask-openapi3 or similar third-party extension; they are not derived from type annotations
- **Dependency injection is manual**: mocking database clients in tests requires patching module-level globals, which is fragile

**Verdict**: Flask is excellent for simple sync apps. It is the wrong choice for an async, type-annotated, DB-heavy API.

### Option B — Django REST Framework (DRF)

**What it is**: DRF adds a REST layer on top of Django's ORM-centric web framework.

**Pros**:
- Batteries-included: auth, ORM, admin UI, permissions, serialisers
- Very large community; mature ecosystem

**Cons**:
- **All batteries are wrong batteries**: we are not using Django ORM (we use SQLAlchemy 2.x async), we are not using Django auth (scope limitation), we have no use for Django admin. DRF's weight is overhead, not value
- **Sync-first**: Django's async support (`async def` views) is a bolt-on introduced in Django 3.1 and still has rough edges, particularly around middleware and the ORM. asyncio + asyncpg + Django is a supported but non-idiomatic combination
- **Serialiser duplication**: DRF serialisers are separate from Pydantic models; maintaining both is a maintenance burden
- **Complexity**: Django's settings.py, URL conf, apps system — all real overhead for an API that, at this phase, has one endpoint

### Option C — Litestar (formerly Starlite)

**What it is**: Async-first Python web framework; direct FastAPI competitor with arguably cleaner architecture.

**Pros**:
- Async-first, designed from scratch for asyncio
- Pydantic v2 native
- Dependency injection system is arguably more explicit and powerful than FastAPI's
- OpenAPI schema generation from type annotations
- Slightly more opinionated on security defaults

**Cons**:
- Smaller community than FastAPI — fewer Stack Overflow answers, fewer tutorials, fewer blog posts about debugging edge cases
- Fewer third-party integrations; library authors target FastAPI first
- For a portfolio project, FastAPI recognition is more valuable than Litestar's marginally better architectural decisions — interviewers will recognise FastAPI immediately

### Option D — FastAPI 0.115+ (chosen)

**What it is**: Async-first Python web framework built on Starlette, with Pydantic v2 as the native validation layer.

**Pros**:
- **Async-first by design**: request handlers are `async def`; the event loop is shared with the Neo4j driver and SQLAlchemy — no thread pool wrappers
- **Pydantic v2 as first-class citizen**: since FastAPI 0.100, Pydantic v2 is the default. Response models, request bodies, and query params are all typed Pydantic models — one schema, no duplication
- **Auto-generated OpenAPI docs**: all endpoint documentation is derived from type annotations and Pydantic models. Swagger UI and ReDoc are available at `/docs` and `/redoc` with zero additional code
- **`lifespan` context manager**: clean pattern for startup/shutdown — connects DB clients on startup, closes them on shutdown. No global state anti-patterns
- **Dependency injection**: `Depends()` makes database client injection and test mocking trivial — no module-level global patching
- **`app.state`**: clean place to attach shared state (DB clients) that request handlers access via `request.app.state`

**Cons**:
- Tied to Pydantic v2 model semantics — breaking changes in Pydantic v3 (hypothetical) would affect FastAPI simultaneously
- A small startup overhead for OpenAPI schema generation — negligible in practice
- The magic of auto-doc generation can obscure what's actually in the response unless you define explicit `response_model` on every endpoint

## Consequences

**Enables**: Async database calls without blocking the event loop. Auto-generated API documentation. Type-safe request/response handling with Pydantic v2. Clean startup/shutdown lifecycle.

**Constrains**: Committed to Pydantic v2 for all data models. ASGI-only — cannot run on a plain WSGI server.

**Locked into**: The FastAPI / Starlette / Pydantic v2 triad. Migrating to Litestar is feasible (similar concepts) but not trivial.

**At larger scale / in production**: FastAPI is used in production at enterprise scale (Uber, Microsoft, Netflix have published case studies). No framework changes are required at scale — horizontal scaling is handled at the infrastructure layer (multiple uvicorn workers behind a load balancer, or gunicorn with uvicorn workers).

## Interview Defense

> "FastAPI because the entire I/O layer is async — Neo4j driver, SQLAlchemy, asyncpg — and running async calls from a sync framework requires thread pool wrappers that are messy and defeat the purpose. FastAPI is async-first, ships Pydantic v2 natively so we have one schema everywhere, and generates OpenAPI docs for free. Flask would work but we'd write two schema layers and fight the event loop the whole time."
