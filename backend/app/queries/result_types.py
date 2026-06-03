"""The uniform annotated-result envelope for every killer query (Phase 3B; ADR 0018).

Every query returns a ``QueryResult[T]``: the strongly-typed answer (``value``) plus a
``QueryProvenance`` mapping each graph element that contributed to the answer to the Postgres
``events`` UUIDs that asserted it. Provenance is a *structural* part of the result, not an
optional field — the project's thesis is grounded answers, and the integration eval validates
that every event id behind an answer exists in Postgres.

These are Pydantic models (not bare dataclasses) so the FastAPI endpoints serialise them — and
the generic ``QueryResult[T]`` — to JSON without extra glue.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class QueryProvenance(BaseModel):
    """Source-event provenance for one query answer.

    ``by_element`` keys are stable, human-readable element handles — ``"node:Decision:D-0006"``
    or ``"edge:DEPRECATES:D-0006->legacy-auth"`` — each mapping to the list of Postgres event
    UUIDs (as strings) that justified that node/edge. ``all_event_ids`` is the flat, de-duplicated
    union used for the demo and for the eval's "every id exists in Postgres" check.
    """

    by_element: dict[str, list[str]] = Field(default_factory=dict)

    def add(self, element_key: str, event_ids: list[str] | tuple[str, ...]) -> None:
        """Record the event ids that justify ``element_key`` (de-duplicated, order-stable)."""
        bucket = self.by_element.setdefault(element_key, [])
        for raw in event_ids:
            if raw and raw not in bucket:
                bucket.append(raw)

    @property
    def all_event_ids(self) -> list[str]:
        """Every distinct event id across all elements, sorted for stable output."""
        seen: set[str] = set()
        for ids in self.by_element.values():
            seen.update(ids)
        return sorted(seen)


class QueryResult[T](BaseModel):
    """A query's answer plus its provenance. The single return shape for all four KQs."""

    model_config = ConfigDict(frozen=True)

    value: T
    provenance: QueryProvenance = Field(default_factory=QueryProvenance)
