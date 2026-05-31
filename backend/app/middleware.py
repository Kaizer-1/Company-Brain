"""Request-scoped middleware for Company Brain.

RequestIDMiddleware generates a UUID4 for every incoming request, binds
it to structlog's contextvars so every log line within the request
automatically carries request_id, and returns the ID to callers via the
X-Request-Id response header.

The structlog context is cleared at the start of each request so context
from a previous request never leaks into the next one.
"""

import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Inject a unique request ID into the structlog context and response headers."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Bind a fresh UUID to structlog context, then forward the request."""
        request_id = str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response
