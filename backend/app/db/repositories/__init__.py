"""Repository layer for Company Brain's Postgres event store.

All SQL lives in repository classes; nothing outside this package touches
sessions directly.  Repository methods return Pydantic DTOs, not ORM instances.
"""

from app.db.repositories.embeddings import EventEmbeddingRepository
from app.db.repositories.events import EventRepository
from app.db.repositories.extraction import ExtractionRunRepository

__all__ = [
    "EventRepository",
    "EventEmbeddingRepository",
    "ExtractionRunRepository",
]
