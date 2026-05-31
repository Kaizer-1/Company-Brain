# ADR 0005 — uv for Package Management and Pydantic v2 for Data Validation

## Status

Accepted

## Context

Two tooling decisions are bundled here because they share a theme: choosing the modern, stricter Python tool over the established default. Both decisions affect developer experience on every work session.

**Package management**: we need repeatable installs across dev machines, CI, and Docker. The Python ecosystem has multiple options (pip, pip-tools, Poetry, uv), and the choice affects install speed, lockfile quality, and `pyproject.toml` standards compliance.

**Data validation**: every ingested entity, API request, and response passes through a validation layer. We need a library that catches data shape bugs early, integrates with FastAPI, and performs well in ingestion pipelines that may process thousands of extracted entities per run.

## Decision

**uv** for all package management, over pip/pip-tools and Poetry.
**Pydantic v2** for all data models, over Pydantic v1.

---

## Part A: uv vs pip / pip-tools / Poetry

### Option A1 — pip + pip-tools

**What it is**: pip for installation; pip-compile to generate a pinned `requirements.txt` lockfile from a `requirements.in` source file.

**Pros**:
- Zero additional tooling — pip ships with Python; pip-tools is a tiny addition
- Universally understood; any Python developer can onboard without learning a new tool
- Lockfile is a plain `requirements.txt` — readable, diffable, no custom format

**Cons**:
- Separate tool for each job: pip for install, pip-tools for lockfile, virtualenv for venv management, pyenv for Python version. Four tools where one (uv) does all four
- `pip-compile` is significantly slower than uv on large dependency trees — 30–60 seconds vs <1 second
- Non-standard split between `requirements.in` (source) and `requirements.txt` (pinned) is confusing to developers unfamiliar with the pattern
- No PEP 621 `[project]` table integration — dependencies are listed in `requirements.in`, not the standard `pyproject.toml`

### Option A2 — Poetry

**What it is**: Opinionated Python packaging and dependency management tool with its own lockfile format (`poetry.lock`).

**Pros**:
- Mature, widely adopted — Poetry is the current "standard" for teams that want pip-tools-quality lockfiles with better ergonomics
- `pyproject.toml`-based but uses `[tool.poetry]` table, which is a superset of PEP 621
- Good developer experience: `poetry add`, `poetry run`, `poetry shell` are intuitive
- Lockfile is comprehensive and deterministic

**Cons**:
- **Speed**: Poetry's dependency resolver is known to be slow on non-trivial dependency trees (10–30 seconds for a fresh resolve vs <1 second for uv)
- **Non-standard `[tool.poetry]` table**: Poetry uses its own `[tool.poetry.dependencies]` syntax rather than the standard `[project] dependencies` from PEP 621. This means the `pyproject.toml` is not portable — other tools (uv, pip, hatchling) cannot read the dependency list without Poetry
- **Resolver bugs**: Poetry has a history of resolver issues where valid dependency graphs are rejected. These are edge cases but they happen at the worst possible times (CI, demo day)
- **Installation**: Poetry itself must be installed separately; it is not bundled with Python

### Option A3 — uv (chosen)

**What it is**: A Rust-based Python package manager from Astral (the authors of ruff). Replaces pip, pip-tools, virtualenv, and partially replaces pyenv in a single binary.

**Pros**:
- **Speed**: 10–100× faster than pip and Poetry for dependency resolution and installation. Fresh virtual environment creation + install of this project's dependencies takes <3 seconds
- **Standard PEP 621 `[project]` table**: uv reads the standard `dependencies` key — the same `pyproject.toml` works with uv, pip, hatchling, and other compliant tools without modification
- **`uv.lock` lockfile**: deterministic, fully-pinned lockfile in a custom but transparent format. Reproducible installs across all platforms
- **All-in-one**: `uv venv`, `uv sync`, `uv run`, `uv pip install` — one binary for all Python environment management tasks
- **Drop-in pip compatibility**: `uv pip install <package>` is a direct replacement for `pip install`; no new mental model for simple cases

**Cons**:
- Newer tool — some edge cases are less battle-tested than pip/Poetry; community is smaller (though growing rapidly)
- `uv.lock` format is not human-readable in the same way as `requirements.txt` — slightly harder to audit manually

---

## Part B: Pydantic v2 vs Pydantic v1

### Option B1 — Pydantic v1

**What it is**: The pre-2.0 Pydantic, still widely used and supported via the `pydantic.v1` compatibility shim in FastAPI.

**Pros**:
- Stable, extremely well-documented, no breaking changes
- Every existing Pydantic tutorial and Stack Overflow answer applies
- No migration required from existing codebases

**Cons**:
- FastAPI 0.100+ ships Pydantic v2 by default; using v1 requires the `pydantic.v1` compatibility shim, which is a documented maintenance path, not a first-class path
- Performance: Pydantic v1 validation is ~5–50× slower than v2. For ingestion pipelines processing thousands of extracted entities, this is measurable
- Missing v2 features we want: `model_config = ConfigDict(strict=True)` for catch-all coercion prevention; `model_validator` / `field_validator` with better ergonomics; `pydantic-settings` v2 for typed environment config
- v1 is effectively legacy — it will eventually stop receiving fixes

### Option B2 — Pydantic v2 (chosen)

**What it is**: Complete rewrite of Pydantic with a Rust core. Breaks v1 APIs but provides significant performance and strictness improvements.

**Pros**:
- **Performance**: validation core in Rust; 5–50× faster than v1. Matters in Phase 2D (LLM entity extraction) and Phase 3D (embedding pipeline) where models validate thousands of objects per run
- **`model_config = ConfigDict(strict=True)`**: prevents silent coercion bugs. In strict mode, `int` will not accept `"42"` — it must be an integer. This catches the class of bug where upstream code passes the wrong type and Pydantic silently coerces it rather than raising
- **`pydantic-settings`**: the official settings library for v2, used in `app/config.py`. Reads env vars into typed settings with validation — no raw `os.environ` calls anywhere
- **FastAPI-native**: FastAPI 0.100+ uses v2 as the default; there is no compatibility overhead
- **Better `model_validator` ergonomics**: cross-field validators are cleaner and more predictable than v1's `@validator` / `@root_validator` distinction

**Cons**:
- Breaking changes from v1: `class Config:` replaced by `model_config = ConfigDict(...)`, some validator decorators renamed
- Third-party libraries that only support v1 may need `pydantic.v1` compatibility wrapper

## Consequences

**Enables**: Fast, reproducible installs via uv. Type-safe, fast data validation via Pydantic v2. Single `pyproject.toml` using PEP 621 standard tables. `ConfigDict(strict=True)` on models to catch coercion bugs in ingestion pipelines.

**Constrains**: uv must be installed on all developer machines and CI. Pydantic v1-only libraries (rare in 2025) cannot be used without a compatibility wrapper.

**Locked into**: uv's lockfile format. Pydantic v2's model semantics.

**At larger scale / in production**: No changes needed — both uv and Pydantic v2 are production-grade.

## Interview Defense

> "We chose uv because lockfile quality + install speed matters in CI and Docker, and uv gives us pip-tools-quality reproducibility at 100× the speed without Poetry's non-standard config format. We chose Pydantic v2 because FastAPI ships it by default now, and strict mode catches silent coercion bugs that would silently corrupt extracted entity data in the ingestion pipeline — the kind of bug that only shows up in production when an LLM starts returning strings where you expected integers."
