"""Shared temporal helpers for the killer queries (Phase 3B; ADR 0016).

KQ2/KQ4 windows are relative to *now*, but the synthetic corpus is anchored to a fixed
``REFERENCE_NOW``. Evaluating against wall-clock ``datetime.now()`` would slide the window past
the data and break the eval forever. So every temporal query takes ``as_of`` and defaults it to
``REFERENCE_NOW`` for dev/eval; production passes the real now.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.synthetic.company import REFERENCE_NOW

if TYPE_CHECKING:
    from datetime import datetime, timedelta


def resolve_as_of(as_of: datetime | None) -> datetime:
    """Return the effective evaluation time: the caller's ``as_of`` or ``REFERENCE_NOW``.

    Centralising the fallback means a single, documented place defines what "now" means for
    every temporal query, and tests can assert it.
    """
    return as_of if as_of is not None else REFERENCE_NOW


def window_bounds(as_of: datetime | None, window: timedelta) -> tuple[datetime, datetime]:
    """Return ``(window_start, effective_as_of)`` for a look-back ``window`` ending at now."""
    effective = resolve_as_of(as_of)
    return effective - window, effective
