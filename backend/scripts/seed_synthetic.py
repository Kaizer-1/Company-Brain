"""One-shot CLI to seed the synthetic corpus into Postgres.

This is NOT part of normal app startup — run it explicitly against a running database:

    uv run python backend/scripts/seed_synthetic.py

It reads the DSN from settings, builds an engine + session, generates the deterministic
seed=42 corpus, inserts it idempotently via ``EventRepository``, commits, and logs the
total count. Inside Docker the equivalent entrypoint is ``python -m app.synthetic.seeder``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make ``app`` importable when run as a loose script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import structlog  # noqa: E402  (after sys.path setup)

from app.config import settings  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.synthetic.seeder import main  # noqa: E402

log = structlog.get_logger(__name__)


if __name__ == "__main__":
    configure_logging(debug=settings.debug)
    inserted = asyncio.run(main())
    log.info("seed_synthetic_script_done", inserted=inserted)
