"""Generic repository base class.

All SQL lives in repository classes; no other layer touches sessions directly.
Repository methods accept and return Pydantic DTOs at the API boundary — never
raw SQLAlchemy ORM instances.  This prevents accidental lazy-loading in async
contexts and enforces a clean separation between the DB layer and service layer.

Convention: all public methods are async and accept/return typed Pydantic models.
"""

from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class Repository(Generic[ModelT]):
    """Thin base class that carries the session and model type.

    Subclasses receive an ``AsyncSession`` at construction time.  All queries
    run against this session; the session lifecycle is managed by the caller
    (FastAPI dependency or test fixture).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
