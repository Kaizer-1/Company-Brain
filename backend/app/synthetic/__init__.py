"""Adversarial synthetic data generation for Company Brain (Phase 2A).

Composes the locked fictional company (``company.py``) and the hand-designed planted
cases (``narrative.py``) into deterministic raw ``events`` rows via ``generator.py``,
seeded into Postgres by ``seeder.py``. The graph stays empty after this phase —
extraction is Phase 2B. See ``docs/design/synthetic-company.md`` and ADR 0011.
"""
