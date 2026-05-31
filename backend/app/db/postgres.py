"""Async Postgres client built on SQLAlchemy 2.x.

Installs the pgvector extension on startup and exposes a connectivity
probe for the health endpoint. Session management will be expanded in
Phase 1C when ORM models are introduced.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class PostgresClient:
    """Thin wrapper around a SQLAlchemy async engine."""

    def __init__(self, dsn: str) -> None:
        self.engine: AsyncEngine = create_async_engine(dsn, echo=False)
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    async def verify_connectivity(self) -> bool:
        """Return True if Postgres responds to SELECT 1, False otherwise."""
        try:
            async with self.engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def ensure_pgvector(self) -> None:
        """Install the pgvector extension if not already present."""
        async with self.engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
