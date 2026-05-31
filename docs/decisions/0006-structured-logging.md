# ADR 0006 — Structured Logging with structlog

## Status

Accepted

## Context

As the project gains more code paths (ingestion pipeline in Phase 2, query engine in Phase 3), we need log output that is:

1. **Machine-parseable in production** — log aggregation tools (Datadog, Grafana Loki, CloudWatch Logs Insights) work best with JSON lines. Free-text logs require fragile regex parsing.
2. **Request-correlated** — every log line emitted while handling a single HTTP request should carry the same `request_id` so that distributed traces can be reconstructed from logs alone.
3. **Framework-integrated** — uvicorn's access log, SQLAlchemy's query log, and the Neo4j driver's debug output all go through Python's stdlib `logging`. Whatever we choose must capture these too, so there is a single log stream with a consistent format.

A secondary constraint: in local development, JSON is unreadable at a glance. The solution must support human-readable output in debug mode without changing any call sites.

## Decision

**structlog 24.x** with:
- `JSONRenderer` in production (`DEBUG=false`)
- `ConsoleRenderer` in debug mode (`DEBUG=true`)
- stdlib integration (`ProcessorFormatter` on the root logger) to capture all third-party log output
- `contextvars` integration (`merge_contextvars` processor) for request-scoped field binding
- `RequestIDMiddleware` in Starlette that binds a UUID4 `request_id` to the structlog context at the start of every request and clears it at the end

## Alternatives Considered

### Option A — stdlib `logging` with `python-json-logger`

**What it is**: The standard library `logging` module with `pythonjsonlogger.jsonlogger.JsonFormatter` as the handler formatter. Produces JSON log lines from ordinary stdlib `logging` calls.

**Pros**:
- Near-zero dependency — `python-json-logger` is a tiny package
- Every Python developer already knows `logging.getLogger(__name__)`
- No new API to learn

**Cons**:
- **No context binding**: adding `request_id` to all log lines within a request requires either a `logging.Filter` that reads from a `ContextVar` manually, or passing the ID through every function call. There is no built-in mechanism like structlog's `bind_contextvars`
- **Keyword arguments in log calls become strings**: `log.info("health check neo4j=%s", neo4j_ok)` vs `log.info("health_check", neo4j=neo4j_ok)`. The latter is natively structured; the former requires post-hoc parsing
- **Switch to pretty-print for development**: requires changing the formatter configuration; structlog's ConsoleRenderer is a one-line conditional in `configure_logging`

### Option B — loguru

**What it is**: A third-party logging library designed to replace stdlib `logging`. Provides structured output, pretty terminal display, and a simpler API.

**Pros**:
- Excellent ergonomics: `logger.info("event", key=value)` just works
- Pretty, colour-coded console output by default
- Supports JSON serialisation via `sink` configuration

**Cons**:
- **Stdlib integration is awkward**: loguru is a competing system, not an extension of stdlib `logging`. Intercepting uvicorn and SQLAlchemy logs requires a custom `InterceptHandler` that bridges stdlib `logging.Handler` to loguru. This is documented but non-trivial
- **Context binding**: loguru supports `logger.bind(request_id=...)` but it creates a new bound logger instance rather than binding to a thread/coroutine context. In an async framework, request-scoped binding requires more manual plumbing than structlog's `contextvars`
- Smaller ecosystem than structlog; structlog is the de-facto standard in the FastAPI community

### Option C — OpenTelemetry Logging

**What it is**: The OpenTelemetry SDK's logging integration, which exports log records to an OTLP collector alongside traces and metrics.

**Pros**:
- The "right" answer for production observability: logs, traces, and metrics in one pipeline
- Automatic correlation with trace_id and span_id — stronger than a request_id UUID

**Cons**:
- Requires an OTel collector (Jaeger, Tempo, etc.) — another Docker service, another dependency
- Massive dependency surface (the OTel Python SDK + exporters)
- Over-engineered for a demo project that currently has zero metrics and zero tracing
- Not a named scope limitation — named "no observability" in CLAUDE.md Known Gaps

**When to reconsider**: If the project ever needs distributed tracing (e.g., tracing a query from agent → graph traversal → vector search), OpenTelemetry is the right upgrade path. structlog can be replaced or supplemented at that point.

### Option D — structlog 24.x (chosen)

**What it is**: A Python structured logging library that processes log events through a configurable chain of processors before rendering them. Integrates with stdlib `logging` so third-party libraries participate in the same pipeline.

**Pros**:
- **`contextvars` native**: `bind_contextvars(request_id=...)` in middleware automatically propagates `request_id` to every log call within the async request context — no extra plumbing
- **Mode switching is trivial**: `JSONRenderer` vs `ConsoleRenderer` is a one-line conditional; call sites are identical
- **Stdlib integration**: `ProcessorFormatter` on the root stdlib logger means uvicorn access logs, SQLAlchemy query logs, and Neo4j driver debug output all pass through the same JSON pipeline
- **Processor pipeline**: each log event passes through a list of processors (timestamper, log level adder, context merger, renderer). Adding cross-cutting concerns (e.g., adding service version to every log line) is one extra processor, zero changes to call sites
- **de-facto standard** in the FastAPI/async Python community; well-documented, actively maintained

**Cons**:
- Another dependency (though lightweight — pure Python, <200 KB)
- `structlog.get_logger()` returns a generic type that some mypy strict configurations treat as `Any` — call sites need a type annotation comment in strict configurations

## Implementation Notes

- `configure_logging(debug: bool)` is called at `main.py` module level so that lifespan startup logs are already structured
- `RequestIDMiddleware` calls `structlog.contextvars.clear_contextvars()` before each request to prevent context leakage between requests in a connection-pool scenario
- stdlib root logger handlers are cleared before adding the structlog handler, to prevent duplicate output from uvicorn's own handler setup
- `foreign_pre_chain` on `ProcessorFormatter` applies the shared processors to records that originate from stdlib loggers (not structlog), so they receive timestamps and log levels in the same format

## Consequences

**Enables**: Every log line is valid JSON in production. `request_id` appears on all logs within a request at zero cost to call sites. Third-party library logs share the format. Debug mode gives readable console output with colours.

**Constrains**: `structlog.configure()` must be called before any logging occurs. Tests that import modules with module-level loggers will trigger structlog initialisation — this is benign but means test logs also go through structlog.

**Locked into**: structlog's processor model and `contextvars`-based context binding. Migrating to OTel later means replacing the processor chain, not rewriting call sites (they stay as `log.info("event", key=value)`).

**At larger scale / in production**: Add a log shipper (Fluent Bit, Vector) to tail the JSON output and forward to Datadog, Loki, or CloudWatch. Add OpenTelemetry trace context propagation by inserting a `trace_id` processor that reads from the OTel context — structlog's pipeline makes this a one-line addition.

## Interview Defense

> "We chose structlog over stdlib+json-logger because the context binding story is dramatically better in async code. With structlog's contextvars integration, the middleware binds a request_id once and every log call in that request context automatically carries it — no function-threading required. The JSON/console switch is a one-liner. The stdlib integration means uvicorn and SQLAlchemy logs go through the same pipeline. The trade-off is another dependency, but it's lightweight and it's the de-facto standard in the FastAPI community."
