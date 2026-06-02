# Build context: repo root (set via docker-compose `context: .`)
FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv==0.5.5

# Copy project manifest. pyproject.toml is the single source of truth for
# runtime deps; any drift between local development and the image is a bug.
COPY pyproject.toml ./

# Extract runtime deps from pyproject.toml's [project.dependencies] and install.
# tomllib is in stdlib on Python 3.11+, so no extra package needed.
# We deliberately avoid `uv pip install .` because hatchling would need the
# source code at this layer, which would invalidate the dependency cache on
# every source-code change.
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt && \
    cat /tmp/requirements.txt && \
    uv pip install --system --no-cache -r /tmp/requirements.txt

# Copy application source
COPY backend/app/ ./app/
COPY backend/migrations/ ./migrations/
COPY backend/alembic/ ./alembic/
COPY backend/alembic.ini ./alembic.ini
# Post-Phase-1B Docker-copy baseline: any backend dir must be copied into the image.
COPY backend/scripts/ ./scripts/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]