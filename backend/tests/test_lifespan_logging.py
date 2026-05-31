"""Test that the FastAPI lifespan emits structured JSON logs.

Regression guard for the Alembic fileConfig clobber (Phase 1C follow-up Bug 1):
the stock alembic.ini contains [loggers]/[handlers]/[formatters] sections that
cause Alembic's env.py to call logging.config.fileConfig(...) with
disable_existing_loggers=True, silently destroying structlog's handler chain.
After removing those sections and the fileConfig call, every log line produced
during startup must be valid JSON and the key lifecycle events must be present.

Neo4j is mocked so only a real Postgres container is required.

Implementation note: capsys cannot capture this test's logs because
logging.StreamHandler stores a reference to sys.stderr at configure_logging()
call time (module import), before capsys patches the stream.  caplog captures
at the Python logging layer instead, which is independent of stream handles.
"""

import json
import logging
from io import StringIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog
from fastapi.testclient import TestClient


def test_lifespan_logs_postgres_events_as_json(
    pg_test_dsn: str,
    run_migrations: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """After the alembic.ini fix, the lifespan must:
    1. Still have structlog's ProcessorFormatter handler after Alembic runs.
    2. Emit 'postgres_migrations_applied' and 'startup_complete'.
    3. Produce valid JSON when each record is formatted through structlog's chain.
    """
    import app.main as main_module

    mock_neo4j: Any = AsyncMock()
    mock_neo4j.verify_connectivity.return_value = True
    mock_neo4j.driver = MagicMock()
    mock_neo4j.close = AsyncMock()

    class _Settings:
        """Minimal settings shim pointing at the testcontainer Postgres."""

        postgres_dsn: str = pg_test_dsn
        neo4j_uri: str = "bolt://test-neo4j:7687"
        neo4j_user: str = "neo4j"
        neo4j_password: str = "test"
        debug: bool = False
        app_name: str = "company-brain-test"

    with caplog.at_level(logging.INFO):
        with (
            patch("app.main.Neo4jClient", return_value=mock_neo4j),
            patch("app.main.apply_migrations", return_value=[]),
            patch("app.main.settings", _Settings()),
        ):
            with TestClient(main_module.app):
                pass  # lifespan runs on __enter__ / __exit__

    # 1. The root logger must still have handlers after Alembic ran.
    #    Before the alembic.ini fix, fileConfig() with disable_existing_loggers=True
    #    would have cleared all handlers, making every subsequent log.info a no-op.
    root_logger = logging.getLogger()
    assert root_logger.handlers, (
        "Root logger has no handlers after Alembic ran — "
        "check that alembic.ini has no [loggers]/[handlers]/[formatters] sections "
        "and that env.py does not call fileConfig()."
    )

    # 2. The surviving handler must still be structlog's ProcessorFormatter.
    #    If Alembic had clobbered it, the handler would carry a plain Formatter instead.
    handler = root_logger.handlers[0]
    assert isinstance(handler.formatter, structlog.stdlib.ProcessorFormatter), (
        "structlog's ProcessorFormatter was replaced after Alembic ran — "
        "Alembic clobbered the handler chain."
    )

    # 3. The key lifecycle events must appear in the captured records.
    all_messages = " ".join(str(r.getMessage()) for r in caplog.records)
    assert "postgres_migrations_applied" in all_messages, (
        "'postgres_migrations_applied' not found in captured log records; "
        "structlog handler may have been silenced."
    )
    assert "startup_complete" in all_messages, (
        "'startup_complete' not found in captured log records."
    )

    # 4. Every record, when emitted through structlog's JSON formatter, must
    #    produce a valid JSON line.  This pins the full formatter chain end-to-end.
    buffer = StringIO()
    json_handler = logging.StreamHandler(buffer)
    json_handler.setFormatter(handler.formatter)
    for record in caplog.records:
        json_handler.emit(record)

    output = buffer.getvalue().strip()
    assert output, "structlog's formatter produced no output"
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            pytest.fail(
                f"Non-JSON output from structlog formatter "
                f"(Alembic may have clobbered the chain): {line!r} — {exc}"
            )
