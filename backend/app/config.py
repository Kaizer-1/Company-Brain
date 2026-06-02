"""Application settings loaded from environment variables.

All env reads in the project are centralised here. No other module
may call os.environ directly.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings backed by .env or real environment variables.

    Field names map to uppercase env var names by default (neo4j_uri → NEO4J_URI).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # The shared .env also holds Postgres *container* credentials (POSTGRES_USER/DB,
        # consumed by docker-compose, not by the app). Ignore env vars we don't model
        # rather than crash on them — only matters when running locally with the .env
        # present (inside the image those vars aren't set).
        extra="ignore",
    )

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"

    # Postgres
    postgres_dsn: str = "postgresql+asyncpg://company_brain:password@localhost:5433/company_brain"

    # App
    app_name: str = "Company Brain"
    debug: bool = False

    # Extraction pipeline (Phase 2B). The graph is populated by an LLM extraction
    # pipeline that talks to many models through one API (OpenRouter); see
    # docs/decisions/0012-extraction-via-openrouter.md. The API key is read here
    # (never via os.environ elsewhere) and is empty by default so the rest of the
    # stack — and the test suite — runs without it; the real-API smoke test skips
    # when it is unset.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    extraction_model: str = "openai/gpt-4o-mini"  # default single-run model
    extraction_temperature: float = 0.0  # deterministic-ish: extraction is not creative writing
    extraction_max_tokens: int = 2000


settings = Settings()
