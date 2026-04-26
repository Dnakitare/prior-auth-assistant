#!/bin/sh
# Diagnostics first — write to BOTH streams in case one is being swallowed.
log() {
    printf '[entrypoint] %s\n' "$1"
    printf '[entrypoint] %s\n' "$1" >&2
}

log "BOOT $(date -u +%FT%TZ)"
log "PORT=${PORT:-unset} WORKERS=${WORKERS:-unset} APP_ENV=${APP_ENV:-unset}"
log "cwd=$(pwd) user=$(id -un):$(id -gn)"
log "python: $(python --version 2>&1)"
log "uvicorn: $(uvicorn --version 2>&1 || echo MISSING)"

log "testing app import..."
if python -c "import src.api.main; print('[entrypoint] import ok')" 2>&1; then
    log "import succeeded"
else
    log "IMPORT FAILED — see traceback above; exiting"
    exit 1
fi

log "exec uvicorn on 0.0.0.0:${PORT:-8000} workers=${WORKERS:-1}"
exec uvicorn src.api.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers "${WORKERS:-1}"
