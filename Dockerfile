# syntax=docker/dockerfile:1.6
#
# Multi-stage build. Final image runs as non-root user 1000:1000 and contains
# only the runtime Python deps, not the build toolchain.

# ---- build stage ----------------------------------------------------------
FROM python:3.11-slim AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# ---- runtime stage --------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/usr/local/bin:${PATH}"

WORKDIR /app

# Runtime libs only (libpq for asyncpg/psycopg connectivity, curl for healthcheck).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /install /usr/local

COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./alembic.ini
# Whole scripts dir so `python -m scripts.migrate` and `scripts.seed_demo`
# resolve at runtime (Railway preDeployCommand and post-deploy seeding both
# need this).
COPY scripts/ ./scripts/

RUN chmod +x ./scripts/entrypoint.sh \
    && groupadd --system --gid 1000 appuser \
    && useradd --system --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/health/live" || exit 1

# Exec'd script bypasses sh -c quoting/buffering quirks and gives a
# diagnostic banner before uvicorn boots. Tune --workers via WORKERS env.
CMD ["/app/scripts/entrypoint.sh"]
