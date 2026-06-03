"""Unit tests for the as_of / window helpers (Phase 3B; ADR 0016)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.queries.temporal import resolve_as_of, window_bounds
from app.synthetic.company import REFERENCE_NOW


def test_resolve_as_of_defaults_to_reference_now() -> None:
    assert resolve_as_of(None) == REFERENCE_NOW


def test_resolve_as_of_honours_override() -> None:
    custom = datetime(2030, 1, 1, tzinfo=UTC)
    assert resolve_as_of(custom) == custom


def test_window_bounds_uses_reference_now_by_default() -> None:
    start, end = window_bounds(None, timedelta(days=30))
    assert end == REFERENCE_NOW
    assert start == REFERENCE_NOW - timedelta(days=30)


def test_window_bounds_with_override() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    start, end = window_bounds(now, timedelta(days=90))
    assert end == now
    assert start == now - timedelta(days=90)
