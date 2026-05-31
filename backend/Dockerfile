# Build context: repo root (set via docker-compose `context: .`)
FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv==0.5.5

# Copy project manifest for layer caching; install runtime deps only
COPY pyproject.toml ./
RUN uv pip install --system --no-cache \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.32.0" \
    "pydantic-settings>=2.6.0" \
    "structlog>=24.1.0" \
    "neo4j>=5.26.0" \
    "sqlalchemy[asyncio]>=2.0.36" \
    "asyncpg>=0.30.0" \
    "pgvector>=0.3.6" \
    "alembic>=1.14.0"

# Copy application source
COPY backend/app/ ./app/
COPY backend/migrations/ ./migrations/
COPY backend/alembic/ ./alembic/
COPY backend/alembic.ini ./alembic.ini

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
