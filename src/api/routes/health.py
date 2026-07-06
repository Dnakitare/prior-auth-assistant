"""Comprehensive health check endpoints."""

from datetime import datetime, timezone
from enum import Enum

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

from src.core.config import settings

router = APIRouter()
logger = structlog.get_logger()


class HealthStatus(str, Enum):
    """Health check status values."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentHealth(BaseModel):
    """Health status of a component."""

    name: str
    status: HealthStatus
    latency_ms: float | None = None
    message: str | None = None


class HealthResponse(BaseModel):
    """Comprehensive health check response."""

    status: HealthStatus
    timestamp: datetime
    version: str
    environment: str
    components: list[ComponentHealth]


async def check_database() -> ComponentHealth:
    """Check database connectivity."""
    import time

    from sqlalchemy import text

    from src.core.database import async_session_maker

    start = time.perf_counter()
    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
        latency = (time.perf_counter() - start) * 1000
        return ComponentHealth(
            name="database",
            status=HealthStatus.HEALTHY,
            latency_ms=round(latency, 2),
        )
    except Exception as e:
        logger.warning("Database health check failed", error=str(e))
        return ComponentHealth(
            name="database",
            status=HealthStatus.UNHEALTHY,
            message=str(e) if settings.is_development else "Connection failed",
        )


async def check_redis() -> ComponentHealth:
    """Check Redis connectivity.

    Only meaningful when the deployment actually uses Redis. With the
    in-memory rate-limit backend there is nothing to probe — reporting
    "degraded" for an intentionally absent component made every healthy
    single-replica deployment look broken.
    """
    import time

    if settings.rate_limit_backend != "redis":
        return ComponentHealth(
            name="redis",
            status=HealthStatus.HEALTHY,
            message="Not in use (in-memory rate limiting)",
        )

    try:
        import redis.asyncio as redis

        start = time.perf_counter()
        client = redis.from_url(settings.redis_url)
        await client.ping()
        await client.close()
        latency = (time.perf_counter() - start) * 1000
        return ComponentHealth(
            name="redis",
            status=HealthStatus.HEALTHY,
            latency_ms=round(latency, 2),
        )
    except Exception as e:
        logger.warning("Redis health check failed", error=str(e))
        return ComponentHealth(
            name="redis",
            status=HealthStatus.DEGRADED,  # Redis is optional
            message=str(e) if settings.is_development else "Connection failed",
        )


async def check_llm() -> ComponentHealth:
    """Check LLM API availability.

    By default only validates that the key is present and has a plausible
    format (cheap). When HEALTH_CHECK_LLM_LIVE=true, performs a minimal
    countTokens call to confirm the upstream is actually reachable — this
    costs a trivial amount per health check and should be scheduled sparingly
    (e.g., from a cron, not from every k8s probe).
    """
    if not settings.anthropic_api_key:
        return ComponentHealth(
            name="llm",
            status=HealthStatus.UNHEALTHY,
            message="API key not configured",
        )

    if not settings.anthropic_api_key.startswith("sk-"):
        return ComponentHealth(
            name="llm",
            status=HealthStatus.DEGRADED,
            message="API key format may be invalid",
        )

    if not settings.health_check_llm_live:
        return ComponentHealth(
            name="llm",
            status=HealthStatus.HEALTHY,
            message="API key configured (live check disabled)",
        )

    # Live check — cheap count_tokens call. Only enable from a scheduled task,
    # not from every probe.
    import time as _time
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        start = _time.perf_counter()
        await client.messages.count_tokens(
            model=settings.llm_model,
            messages=[{"role": "user", "content": "ping"}],
        )
        latency = (_time.perf_counter() - start) * 1000
        return ComponentHealth(
            name="llm",
            status=HealthStatus.HEALTHY,
            latency_ms=round(latency, 2),
            message="Live ping ok",
        )
    except Exception as e:
        logger.warning("llm_live_probe_failed", error=str(e))
        return ComponentHealth(
            name="llm",
            status=HealthStatus.UNHEALTHY,
            message="Upstream unreachable" if settings.is_production else str(e),
        )


async def check_ocr() -> ComponentHealth:
    """Check OCR provider availability.

    OCR runs through Claude (same vendor as extraction/generation), so a
    configured ANTHROPIC_API_KEY means OCR is wired up. No key falls back
    to the mock provider.
    """
    if settings.anthropic_api_key:
        return ComponentHealth(
            name="ocr",
            status=HealthStatus.HEALTHY,
            message="Claude OCR configured",
        )

    return ComponentHealth(
        name="ocr",
        status=HealthStatus.DEGRADED,
        message="Using mock OCR provider (no Anthropic key configured)",
    )


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Comprehensive health check endpoint.

    Checks all service dependencies and returns overall status.
    Use this for monitoring and alerting.
    """
    components = [
        await check_database(),
        await check_redis(),
        await check_llm(),
        await check_ocr(),
    ]

    # Determine overall status
    if any(c.status == HealthStatus.UNHEALTHY for c in components):
        overall_status = HealthStatus.UNHEALTHY
    elif any(c.status == HealthStatus.DEGRADED for c in components):
        overall_status = HealthStatus.DEGRADED
    else:
        overall_status = HealthStatus.HEALTHY

    return HealthResponse(
        status=overall_status,
        timestamp=datetime.now(timezone.utc),
        version="1.0.0",
        environment=settings.app_env,
        components=components,
    )


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    """
    Kubernetes liveness probe endpoint.

    Returns 200 if the application is running.
    Use this for k8s liveness probes.
    """
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness() -> dict[str, str]:
    """
    Kubernetes readiness probe endpoint.

    Returns 200 if the application is ready to serve traffic.
    Checks critical dependencies only.
    """
    # Check database (critical)
    db_health = await check_database()
    if db_health.status == HealthStatus.UNHEALTHY:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="Database not ready")

    # Check LLM (critical for core functionality)
    llm_health = await check_llm()
    if llm_health.status == HealthStatus.UNHEALTHY:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="LLM service not ready")

    return {"status": "ready"}
