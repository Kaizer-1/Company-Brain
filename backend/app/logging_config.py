"""Structlog configuration for Company Brain.

Sets up structlog with stdlib integration so that uvicorn, SQLAlchemy,
and the Neo4j driver log through the same pipeline. In production
(debug=False) every log line is a JSON object. In debug mode, structlog's
ConsoleRenderer produces human-readable coloured output.

Call configure_logging() exactly once, at application startup, before any
log statements execute. main.py calls it at module level.
"""

import logging
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from structlog.types import Processor


def configure_logging(debug: bool = False) -> None:
    """Configure structlog + stdlib root logger.

    Shared processors run on every event before the renderer.
    The renderer is JSON in production and ConsoleRenderer when debug=True.
    """
    timestamper = structlog.processors.TimeStamper(fmt="iso")

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    renderer: Processor = (
        structlog.dev.ConsoleRenderer() if debug else structlog.processors.JSONRenderer()
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.INFO)
