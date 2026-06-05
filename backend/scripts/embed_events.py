"""Embed all un-embedded events into event_embeddings.

    uv run python backend/scripts/embed_events.py

One-shot idempotent script that calls embed_events() against the live stack.
Also used as a standalone step if the full query-eval pipeline is not being run.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import structlog  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.session import build_engine, build_session_factory  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.search.indexer import embed_events  # noqa: E402

log = structlog.get_logger(__name__)


async def _run() -> None:
    engine = build_engine(settings.postgres_dsn)
    session_factory = build_session_factory(engine)
    try:
        async with session_factory() as session:
            written = await embed_events(session)
        print(f"embed_events complete: {written} new embeddings written.")  # noqa: T201
    finally:
        await engine.dispose()


def main() -> None:
    configure_logging(debug=settings.debug)
    asyncio.run(_run())


if __name__ == "__main__":
    main()
