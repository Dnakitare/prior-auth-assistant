"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.core.metrics import render_metrics

from src.api.routes import admin, appeals, auth, health, payers
from src.core.config import settings
from src.core.database import async_admin_session_maker
from src.core.middleware import (
    BodySizeLimitMiddleware,
    HttpsEnforcementMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    build_rate_limiter_backend,
)


def configure_logging() -> None:
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
            if settings.is_production
            else structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)


configure_logging()
logger = structlog.get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_migrations() -> None:
    """Run alembic upgrade head synchronously at startup."""
    cfg = AlembicConfig(str(_PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_PROJECT_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")


async def _seed_bootstrap_api_keys() -> None:
    """Seed bootstrap API keys from BOOTSTRAP_API_KEYS env on first run.

    Keys are upserted by hash; re-running is a no-op. Operators should unset
    the env var after the first successful boot.
    """
    if not settings.bootstrap_api_keys:
        return

    from src.core.db_models import ApiKeyRecord
    from src.core.security import hash_api_key
    from sqlalchemy import select
    import uuid

    async with async_admin_session_maker() as db:
        # System path: bypass RLS to seed keys across all orgs. Session
        # scope so the context persists across per-key commits. When this
        # code runs under a role with BYPASSRLS (the recommended prod
        # pattern via DATABASE_ADMIN_URL), RLS is bypassed regardless and
        # this is belt-and-braces.
        from src.core.security import set_rls_context
        await set_rls_context(
            db, org_id=None, is_admin=True, source="bootstrap", scope="session"
        )

        for raw_key in settings.bootstrap_api_keys:
            key_hash = hash_api_key(raw_key)
            existing = await db.execute(
                select(ApiKeyRecord).where(ApiKeyRecord.key_hash == key_hash)
            )
            if existing.scalar_one_or_none() is not None:
                continue
            db.add(
                ApiKeyRecord(
                    id=str(uuid.uuid4()),
                    key_hash=key_hash,
                    org_id=settings.bootstrap_api_key_org,
                    name="bootstrap",
                    scopes=["appeals:read", "appeals:write"],
                )
            )
            logger.info("bootstrap_api_key_seeded", org_id=settings.bootstrap_api_key_org)
        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "startup",
        app_name=settings.app_name,
        environment=settings.app_env,
        rate_limit_backend=settings.rate_limit_backend,
    )

    # Schema migrations. In multi-replica deployments these should run as a
    # separate init container or CI job (scripts/migrate.py) with
    # MIGRATE_ON_STARTUP=false to avoid multiple replicas racing.
    #
    # We dispatch the sync alembic command onto a worker thread because the
    # alembic env runs `asyncio.run(run_async_migrations())` internally, and
    # `asyncio.run()` cannot start a new event loop inside the one uvicorn
    # already runs the lifespan in. The worker thread has no live loop, so
    # alembic's nested run() works there.
    if settings.migrate_on_startup:
        try:
            await asyncio.to_thread(_run_migrations)
            logger.info("migrations_applied")
        except Exception as e:
            if settings.is_production:
                logger.error("migrations_failed", error=str(e))
                raise
            logger.warning("migrations_failed_dev_continuing", error=str(e))
    else:
        logger.info("migrations_skipped_at_startup")

    # Rate limiter backend.
    redis_client = None
    if settings.rate_limit_backend == "redis":
        import redis.asyncio as redis
        redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await redis_client.ping()
        except Exception as e:
            logger.error("redis_unavailable", error=str(e))
            raise
    app.state.rate_limit_backend = build_rate_limiter_backend(redis_client)
    app.state.redis_client = redis_client

    # Attach Redis to the login lockout so failure counts are shared across replicas.
    if redis_client is not None:
        from src.core.lockout import login_lockout
        login_lockout.attach_redis(redis_client)

    await _seed_bootstrap_api_keys()

    # Start the external audit sink worker if configured.
    from src.core.audit_sink import configure_audit_sink, shutdown_audit_sink
    await configure_audit_sink()

    # Start the webhook delivery worker.
    from src.core.webhooks import start_webhook_worker, stop_webhook_worker
    await start_webhook_worker()

    yield

    await stop_webhook_worker()
    await shutdown_audit_sink()
    if redis_client is not None:
        await redis_client.close()
    logger.info("shutdown")


app = FastAPI(
    title=settings.app_name,
    description="AI-powered prior authorization appeals automation.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
    openapi_url="/openapi.json" if settings.is_development else None,
)


# Rate limit middleware starts with an in-memory backend so it works before
# lifespan runs (tests, local scripts). Lifespan swaps in Redis when configured.
#
# The swap is done by assigning to `self.backend` on each dispatch. This is a
# single attribute assignment of an already-initialized object; under CPython
# the GIL makes this atomic, and both backends expose the same async
# `check()` contract so there's no consistency window where a partial update
# would misbehave. After lifespan completes, `app.state.rate_limit_backend`
# never changes again. Functional under concurrency; the pattern is ugly but
# correct. A cleaner alternative would be a callable-factory dependency.
class _RateLimitShim(RateLimitMiddleware):
    def __init__(self, app_):
        from src.core.middleware import _MemoryBackend
        super().__init__(
            app_,
            requests_per_window=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
            backend=_MemoryBackend(),
        )

    async def dispatch(self, request, call_next):
        backend = getattr(request.app.state, "rate_limit_backend", None)
        if backend is not None:
            self.backend = backend
        return await super().dispatch(request, call_next)


# Middleware order matters. `add_middleware` wraps so the LAST addition is
# the INNERMOST (dispatched first on the request). We want:
#   request in  →  RequestContext (bind request_id / client_ip / log timing)
#                  RateLimitShim
#                  BodySizeLimitMiddleware
#                  HttpsEnforcementMiddleware
#                  SecurityHeadersMiddleware (adds response headers)
#   response out
# RequestContextMiddleware must run before anything that reads
# `request.state.client_ip` (auth, admin audit). Keep it innermost.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(HttpsEnforcementMiddleware)
app.add_middleware(
    BodySizeLimitMiddleware,
    # Global ceiling: generous multiple of the configured upload ceiling so
    # JSON endpoints also get a cap. Individual endpoints (e.g., upload)
    # apply their own tighter check against settings.max_upload_size_mb.
    max_bytes=settings.max_upload_size_mb * 1024 * 1024 * 2,
)
app.add_middleware(_RateLimitShim)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-API-Key",
        "X-Request-ID",
        "Idempotency-Key",
        "X-User-Anthropic-Key",
    ],
    expose_headers=[
        "X-Request-ID",
        "X-Process-Time",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-Error-Code",
    ],
)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    # FastAPI's default HTTPException handler is registered more specifically
    # than this one, so HTTPExceptions from route handlers never reach here.
    # This handler is for truly unhandled exceptions only.
    logger.error(
        "unhandled_exception",
        error=str(exc),
        error_type=type(exc).__name__,
        path=request.url.path,
    )
    if settings.is_production:
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal error occurred. Please try again later."},
        )
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__},
    )


# Optional OpenTelemetry instrumentation.
from src.core.tracing import configure_tracing
configure_tracing(app)


app.include_router(health.router, tags=["Health"])
app.include_router(auth.router, prefix="/api/v1", tags=["Auth"])
app.include_router(appeals.router, prefix="/api/v1", tags=["Appeals"])
app.include_router(payers.router, prefix="/api/v1", tags=["Payers"])
app.include_router(admin.router, prefix="/api/v1", tags=["Admin"])


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus exposition endpoint.

    Not authenticated — expected to be reachable only from the internal
    monitoring network. Do NOT expose this publicly.
    """
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)


@app.get("/", include_in_schema=False)
async def root():
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "status": "operational",
        "docs": "/docs" if settings.is_development else None,
    }
