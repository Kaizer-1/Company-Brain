"""Real-DB tests for the synthetic seeder using a testcontainers Postgres.

Skipped (not failed) when Docker is unavailable. The seeder flushes but does not commit,
so these run inside the rolled-back ``db_session`` transaction: flushed rows are visible
to in-transaction SELECTs, which is exactly what idempotency relies on.
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.events import EventRepository
from app.models.events import Event
from app.synthetic.company import REFERENCE_NOW
from app.synthetic.generator import SyntheticDataGenerator
from app.synthetic.seeder import seed_postgres


async def _row_count(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(Event))
    return result.scalar_one()


@pytest.mark.asyncio
async def test_seed_inserts_all_events(db_session: AsyncSession) -> None:
    events = SyntheticDataGenerator(seed=42).generate()
    repo = EventRepository(db_session)

    inserted = await seed_postgres(repo, events)

    assert inserted == len(events)
    assert await _row_count(db_session) == len(events)


@pytest.mark.asyncio
async def test_second_seed_is_a_noop(db_session: AsyncSession) -> None:
    events = SyntheticDataGenerator(seed=42).generate()
    repo = EventRepository(db_session)

    first = await seed_postgres(repo, events)
    count_after_first = await _row_count(db_session)

    second = await seed_postgres(repo, events)
    count_after_second = await _row_count(db_session)

    assert first == len(events)
    assert second == 0, "re-seeding the same corpus must insert nothing"
    assert count_after_first == count_after_second


@pytest.mark.asyncio
async def test_events_are_chronologically_spread(db_session: AsyncSession) -> None:
    events = SyntheticDataGenerator(seed=42).generate()
    repo = EventRepository(db_session)
    await seed_postgres(repo, events)

    result = await db_session.execute(select(Event.created_at).order_by(Event.created_at.asc()))
    timestamps = [row[0] for row in result.all()]

    assert len(timestamps) == len(events)
    # Ordering by created_at is monotonic non-decreasing.
    assert timestamps == sorted(timestamps)
    # The corpus genuinely spans the window: old history through a recent tail.
    assert timestamps[0] <= REFERENCE_NOW - timedelta(days=300)
    assert timestamps[-1] >= REFERENCE_NOW - timedelta(days=30)


@pytest.mark.asyncio
async def test_both_source_types_present_after_seed(db_session: AsyncSession) -> None:
    events = SyntheticDataGenerator(seed=42).generate()
    repo = EventRepository(db_session)
    await seed_postgres(repo, events)

    result = await db_session.execute(
        select(Event.source_type, func.count()).group_by(Event.source_type)
    )
    counts = {str(row[0]): row[1] for row in result.all()}
    assert len(counts) == 2  # doc + slack_message
    assert all(v > 0 for v in counts.values())
