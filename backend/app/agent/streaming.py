"""SSE event serialisation for the streaming ask endpoint (Phase 4B).

Every Server-Sent Event frame has the shape:

    event: <type>\\n
    data: <json>\\n
    \\n

The ``format_sse`` helper produces that exact string.  ``StreamEventType`` is the
closed set of event names defined in the Phase 4B locked Decision 1
(agent-streaming.md).  Event constants avoid spelling errors in the handler.
"""

from __future__ import annotations

import json
from typing import Any, Final, Literal

# ---------------------------------------------------------------------------
# Event type constants — the closed vocabulary for the streaming protocol.
# ---------------------------------------------------------------------------

EVT_ROUTE: Final = "route"
EVT_TOOL_START: Final = "tool_start"
EVT_TOOL_DONE: Final = "tool_done"
EVT_SYNTHESIS_START: Final = "synthesis_start"
EVT_SYNTHESIS_TOKEN: Final = "synthesis_token"
EVT_SYNTHESIS_DONE: Final = "synthesis_done"
EVT_VERIFY_START: Final = "verify_start"
EVT_VERIFY_DONE: Final = "verify_done"
EVT_COMPLETE: Final = "complete"
EVT_ERROR: Final = "error"

StreamEventType = Literal[
    "route",
    "tool_start",
    "tool_done",
    "synthesis_start",
    "synthesis_token",
    "synthesis_done",
    "verify_start",
    "verify_done",
    "complete",
    "error",
]


def format_sse(event_type: str, data: dict[str, Any]) -> str:
    """Serialise a dict payload as a single SSE frame (event + data + blank line)."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
