"""Async session management for Company Brain's Postgres store.

The engine and session factory are created once in the FastAPI lifespan (not at
module import time) so that tests can substitute a test-container DSN without
patching module-level globals.  The ``get_session`` FastAPI dependency yields a
session that is automatically closed after the request.
"""

from collections.abc import AsyncIterator
from typing import Any

from pgvector.vector import Vector as PGVector
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


async def _register_pgvector_codec(conn: Any) -> None:
    """Register a text-format pgvector codec on an asyncpg connection.

    asyncpg ships with no knowledge of the ``vector`` type, so raw-SQL queries
    return the embedding column as a plain string ``"[0.1,0.2,...]"`` by
    default.  Registering this codec makes asyncpg decode ``vector`` columns
    into ``numpy.ndarray`` automatically.

    Text format (not binary) is used deliberately: SQLAlchemy's ``Vector``
    TypeDecorator serialises Python values to the text representation
    ``"[1.0,...]"`` before they reach asyncpg.  A binary-format encoder would
    receive that string and fail because it expects a ``numpy.ndarray``.  With
    text format the encoder simply passes the string through, so ORM inserts
    and parameterised queries continue to work without modification.
    """
    import numpy as np

    def _encode(value: object) -> str:
        if isinstance(value, str):
            return value  # already text representation from SQLAlchemy TypeDecorator
        return str(PGVector(value).to_text())

    def _decode(value: str) -> Any:
        return PGVector.from_text(value).to_numpy().astype(np.float32)

    await conn.set_type_codec(
        "vector",
        schema="public",
        encoder=_encode,
        decoder=_decode,
        format="text",
    )


def build_engine(dsn: str) -> AsyncEngine:
    """Create an async SQLAlchemy engine for the given DSN.

    Called once in the FastAPI lifespan.  The engine is stored on
    ``app.state`` and passed to ``build_session_factory``.

    The pgvector type codec is registered on every new asyncpg connection so
    that raw-SQL queries return ``numpy.ndarray`` rather than the unparsed text
    string ``"[0.1,0.2,...]"``.  ``run_async`` is SQLAlchemy's documented
    escape hatch for running an awaitable inside a synchronous pool-event
    handler (see :ref:`asyncio_events_run_async`).
    """
    engine = create_async_engine(dsn, echo=False, pool_pre_ping=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection: object, _connection_record: object) -> None:
        # run_async dispatches the coroutine through SQLAlchemy's greenlet
        # bridge so it executes inside the already-running event loop without
        # needing a second call to run_until_complete.
        dbapi_connection.run_async(_register_pgvector_codec)  # type: ignore[attr-defined]

    return engine


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create the session factory bound to the given engine.

    ``expire_on_commit=False`` prevents SQLAlchemy from expiring ORM objects
    after commit, which would trigger lazy loads in async contexts and raise
    ``MissingGreenlet``.
    """
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a session and closes it after the request.

    Usage::

        from fastapi import Depends
        from app.db.session import get_session

        @router.get("/events/{event_id}")
        async def get_event(
            event_id: UUID,
            session: AsyncSession = Depends(get_session),
        ) -> EventDTO: ...

    In practice the session factory is injected via a partial or a closure that
    reads ``request.app.state.session_factory``.
    """
    async with session_factory() as session:
        yield session
