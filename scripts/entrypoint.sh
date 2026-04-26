#!/bin/sh
set -e

# Diagnostic banner so we can verify the container actually reached our code.
# If logs show nothing, the platform is not capturing stdout.
echo "[entrypoint] PORT=${PORT:-8000} WORKERS=${WORKERS:-1} APP_ENV=${APP_ENV:-?}"
echo "[entrypoint] python: $(python --version 2>&1)"
echo "[entrypoint] uvicorn: $(uvicorn --version 2>&1 || echo missing)"

exec uvicorn src.api.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers "${WORKERS:-1}"
