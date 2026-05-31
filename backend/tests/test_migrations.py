"""Tests for the Cypher migration runner (backend/app/db/migrations.py).

The Neo4j async driver is mocked: a hand-rolled async context manager yields an
AsyncMock session whose ``run`` returns a result exposing async ``data`` and
``consume``. Tests assert the runner reads files in name order, skips
already-applied migrations, records new applications, and is idempotent.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.migrations import (
    _APPLIED_QUERY,
    _RECORD_QUERY,
    _split_statements,
    apply_migrations,
)


class _AsyncCM:
    """Minimal async context manager that yields a pre-built session."""

    def __init__(self, session: AsyncMock) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncMock:
        return self._session

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _make_driver(applied_rows: Iterable[dict[str, str]]) -> tuple[MagicMock, AsyncMock]:
    """Build a mock driver whose session returns ``applied_rows`` for the ledger query."""
    result = AsyncMock()
    result.data = AsyncMock(return_value=list(applied_rows))
    result.consume = AsyncMock(return_value=None)

    session = AsyncMock()
    session.run = AsyncMock(return_value=result)

    driver = MagicMock()
    driver.session = MagicMock(return_value=_AsyncCM(session))
    return driver, session


def _write_migrations(tmp_path: Path) -> Path:
    """Create a three-file migration set; return its directory."""
    migrations = tmp_path / "graph"
    migrations.mkdir()
    (migrations / "001_constraints.cypher").write_text(
        "// header comment\nCREATE CONSTRAINT c_one;\nCREATE CONSTRAINT c_two;\n",
        encoding="utf-8",
    )
    (migrations / "002_indexes.cypher").write_text("CREATE INDEX idx_one;\n", encoding="utf-8")
    # Comment-only file (mirrors 003 on Community Edition): zero statements.
    (migrations / "003_existence_constraints.cypher").write_text(
        "// existence constraints are Enterprise-only; intentionally empty\n",
        encoding="utf-8",
    )
    return migrations


def _executed_statements(session: AsyncMock) -> list[str]:
    """All non-ledger Cypher statements passed to session.run, in call order."""
    ledger = {_APPLIED_QUERY, _RECORD_QUERY}
    return [
        call.args[0]
        for call in session.run.call_args_list
        if call.args and call.args[0] not in ledger
    ]


def _recorded_names(session: AsyncMock) -> list[str]:
    """Migration names written to the ledger, in call order."""
    return [
        call.kwargs["name"]
        for call in session.run.call_args_list
        if call.args and call.args[0] == _RECORD_QUERY
    ]


# ---------------------------------------------------------------------------
# _split_statements
# ---------------------------------------------------------------------------


def test_split_statements_strips_comments_and_splits() -> None:
    text = "// a comment\nCREATE CONSTRAINT a;\n// another\nCREATE INDEX b;\n"
    assert _split_statements(text) == ["CREATE CONSTRAINT a", "CREATE INDEX b"]


def test_split_statements_comment_only_file_yields_nothing() -> None:
    assert _split_statements("// only comments\n// nothing to run\n") == []


# ---------------------------------------------------------------------------
# apply_migrations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_applies_all_on_fresh_db(tmp_path: Path) -> None:
    migrations = _write_migrations(tmp_path)
    driver, session = _make_driver(applied_rows=[])

    applied = await apply_migrations(driver, migrations_dir=migrations)

    # Returned in name order, all three files (incl. the comment-only one).
    assert applied == [
        "001_constraints.cypher",
        "002_indexes.cypher",
        "003_existence_constraints.cypher",
    ]
    # Each file recorded in the ledger exactly once, in order.
    assert _recorded_names(session) == applied
    # Real statements executed in order; the comment-only file contributes none.
    assert _executed_statements(session) == [
        "CREATE CONSTRAINT c_one",
        "CREATE CONSTRAINT c_two",
        "CREATE INDEX idx_one",
    ]


@pytest.mark.asyncio
async def test_skips_already_applied(tmp_path: Path) -> None:
    migrations = _write_migrations(tmp_path)
    driver, session = _make_driver(applied_rows=[{"name": "001_constraints.cypher"}])

    applied = await apply_migrations(driver, migrations_dir=migrations)

    # 001 is skipped; only 002 and 003 run.
    assert applied == ["002_indexes.cypher", "003_existence_constraints.cypher"]
    assert _recorded_names(session) == applied
    # 001's statements must NOT have been executed.
    executed = _executed_statements(session)
    assert "CREATE CONSTRAINT c_one" not in executed
    assert executed == ["CREATE INDEX idx_one"]


@pytest.mark.asyncio
async def test_idempotent_when_all_applied(tmp_path: Path) -> None:
    migrations = _write_migrations(tmp_path)
    driver, session = _make_driver(
        applied_rows=[
            {"name": "001_constraints.cypher"},
            {"name": "002_indexes.cypher"},
            {"name": "003_existence_constraints.cypher"},
        ]
    )

    applied = await apply_migrations(driver, migrations_dir=migrations)

    assert applied == []
    assert _recorded_names(session) == []  # nothing re-recorded
    assert _executed_statements(session) == []  # nothing re-run


@pytest.mark.asyncio
async def test_reads_files_in_name_order(tmp_path: Path) -> None:
    """Files created out of order are still applied in lexical name order."""
    migrations = tmp_path / "graph"
    migrations.mkdir()
    (migrations / "002_b.cypher").write_text("CREATE INDEX b;\n", encoding="utf-8")
    (migrations / "001_a.cypher").write_text("CREATE CONSTRAINT a;\n", encoding="utf-8")
    driver, session = _make_driver(applied_rows=[])

    applied = await apply_migrations(driver, migrations_dir=migrations)

    assert applied == ["001_a.cypher", "002_b.cypher"]
    assert _executed_statements(session) == ["CREATE CONSTRAINT a", "CREATE INDEX b"]


@pytest.mark.asyncio
async def test_queries_ledger_before_applying(tmp_path: Path) -> None:
    """The first thing the runner does is read the applied-migration ledger."""
    migrations = _write_migrations(tmp_path)
    driver, session = _make_driver(applied_rows=[])

    await apply_migrations(driver, migrations_dir=migrations)

    first_call: Any = session.run.call_args_list[0]
    assert first_call.args[0] == _APPLIED_QUERY

@pytest.mark.asyncio
async def test_apply_migrations_raises_when_directory_missing(tmp_path):
    """If the migrations directory doesn't exist, refuse to silently succeed."""
    from app.db.migrations import apply_migrations
    missing = tmp_path / "does-not-exist"
    with pytest.raises(RuntimeError, match="Migrations directory does not exist"):
        await apply_migrations(driver=None, migrations_dir=missing)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_apply_migrations_raises_when_directory_empty(tmp_path):
    """An empty migrations directory is almost certainly a packaging bug."""
    from app.db.migrations import apply_migrations
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(RuntimeError, match="No .cypher migration files found"):
        await apply_migrations(driver=None, migrations_dir=empty)  # type: ignore[arg-type]