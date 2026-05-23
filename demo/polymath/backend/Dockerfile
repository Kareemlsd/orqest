# Polymath backend — Phase 0 walking skeleton.
#
# Build context is `./backend`. Orqest source is *not* in the context; it's
# mounted by docker-compose at /orqest and installed at container start by
# entrypoint.sh. Polymath itself is installed normally at build time.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Minimal system deps. psycopg binary wheels suffice; build-essential kept
# for native wheels we may want in later phases (pyarrow, etc.).
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      curl \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install polymath's declared deps first for better Docker cache reuse on
# source edits.
COPY pyproject.toml README.md /app/
RUN pip install --no-cache-dir \
      "fastapi>=0.115" \
      "uvicorn[standard]>=0.30" \
      "pydantic-ai>=1.37" \
      "sqlmodel>=0.0.22" \
      "psycopg[binary]>=3.2" \
      "asyncpg>=0.29" \
      "docker>=7.1" \
      "httpx>=0.27" \
      "python-multipart>=0.0.9" \
      "alembic>=1.13"

# Copy polymath source and install in editable mode (no-deps; deps already above).
# Tests are excluded by .dockerignore — they run in dev venvs, not the image.
COPY polymath /app/polymath
RUN pip install --no-cache-dir --no-deps -e .

# Entrypoint handles the runtime orqest install from the volume mount.
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

CMD ["/entrypoint.sh"]
