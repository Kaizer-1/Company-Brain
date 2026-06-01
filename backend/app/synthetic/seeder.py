"""Seed generated synthetic events into the Postgres ``events`` table.

The seed is idempotent: an event whose ``(source_type, source_external_id)`` already
exists is skipped, so re-running is a no-op. ``seed_postgres`` flushes through the
repository but does NOT commit — the caller owns the transaction boundary (tests roll
back; the CLI commits once). A module entrypoint (``python -m app.synthetic.seeder``)
wires it to the real database via settings.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from app.config import settings
from app.db.repositories.events import EventRepository
from app.db.session import build_engine, build_session_factory
from app.synthetic.generator import SyntheticDataGenerator

if TYPE_CHECKING:
    from app.schemas.postgres import EventCreate

log = structlog.get_logger(__name__)


async def seed_postgres(repo: EventRepository, events: list[EventCreate]) -> int:
    """Insert ``events`` idempotently; return the number newly inserted.

    Skips any event whose ``(source_type, source_external_id)`` is already present
    (including rows flushed earlier in this same transaction), so a second pass over the
    same corpus inserts nothing. Does not commit.
    """
    inserted = 0
    for event in events:
        existing = await repo.get_by_source(event.source_type, event.source_external_id)
        if existing is not None:
            continue
        await repo.create(event)
        inserted += 1
    return inserted


async def main(seed: int = 42) -> int:
    """Generate the corpus and seed it into the configured Postgres, committing once.

    Returns the number of events inserted. Connects via ``settings.postgres_dsn``.
    """
    engine = build_engine(settings.postgres_dsn)
    try:
        factory = build_session_factory(engine)
        async with factory() as session:
            repo = EventRepository(session)
            events = SyntheticDataGenerator(seed=seed).generate()
            inserted = await seed_postgres(repo, events)
            await session.commit()
            log.info(
                "synthetic_seed_complete",
                generated=len(events),
                inserted=inserted,
                skipped=len(events) - inserted,
            )
            return inserted
    finally:
        await engine.dispose()


if __name__ == "__main__":
    from app.logging_config import configure_logging

    configure_logging(debug=settings.debug)
    asyncio.run(main())
