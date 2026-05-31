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
    )

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"

    # Postgres
    postgres_dsn: str = "postgresql+asyncpg://company_brain:password@localhost:5432/company_brain"

    # App
    app_name: str = "Company Brain"
    debug: bool = False


settings = Settings()
