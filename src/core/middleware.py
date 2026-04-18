"""FastAPI middleware: request context, rate limiting, security headers.

Rate limiter supports two backends:
- redis (required in production): atomic fixed-window via INCR + EXPIRE.
- memory (dev only): in-process sliding window. Not distributed-safe.

The per-request key is the authenticated subject if present (JWT sub / API
key id from the X-API-Key header's hash), else the client IP. X-Forwarded-For
is only honored when the immediate peer is in settings.trusted_proxies.
"""

from __future__ import annotations

import ipaddress
import time
import uuid
from collections import defaultdict
from typing import Callable

import structlog
from fastapi import HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.config import settings
from src.core.metrics import (
    http_request_duration_seconds,
    http_requests_total,
    rate_limit_exceeded_total,
)

logger = structlog.get_logger()


def _peer_trusted(request: Request) -> bool:
    """Return True if the immediate peer is in settings.trusted_proxies.

    Accepts both bare IPs and CIDRs in trusted_proxies.
    """
    if not settings.trusted_proxies:
        return False
    client = request.client.host if request.client else None
    if client is None:
        return False
    try:
        peer = ipaddress.ip_address(client)
    except ValueError:
        return False
    for entry in settings.trusted_proxies:
        try:
            if "/" in entry:
                if peer in ipaddress.ip_network(entry, strict=False):
                    return True
            else:
                if peer == ipaddress.ip_address(entry):
                    return True
        except ValueError:
            continue
    return False


def get_client_ip(request: Request) -> str:
    """Resolve the real client IP, honoring X-Forwarded-For only from trusted peers."""
    if _peer_trusted(request):
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Leftmost entry is the original client.
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Adds correlation id and timing to each request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        start_time = time.perf_counter()

        request.state.request_id = request_id
        request.state.start_time = start_time
        request.state.client_ip = get_client_ip(request)

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            client_ip=request.state.client_ip,
        )

        path_template = self._path_template(request)
        try:
            response = await call_next(request)
            process_time = time.perf_counter() - start_time
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time"] = f"{process_time:.4f}"
            http_requests_total.labels(
                method=request.method,
                path_template=path_template,
                status=str(response.status_code),
            ).inc()
            http_request_duration_seconds.labels(
                method=request.method, path_template=path_template
            ).observe(process_time)
            logger.info(
                "request_completed",
                status_code=response.status_code,
                duration_ms=round(process_time * 1000, 2),
            )
            return response
        except Exception as e:
            process_time = time.perf_counter() - start_time
            http_requests_total.labels(
                method=request.method, path_template=path_template, status="500"
            ).inc()
            logger.error(
                "request_failed",
                error=str(e),
                error_type=type(e).__name__,
                duration_ms=round(process_time * 1000, 2),
            )
            raise

    @staticmethod
    def _path_template(request: Request) -> str:
        """Resolve the route's path template to avoid high-cardinality labels
        (e.g., /api/v1/appeals/{id} rather than /api/v1/appeals/<uuid>).
        """
        route = request.scope.get("route")
        if route is not None and getattr(route, "path", None):
            return route.path
        return request.url.path


class _RateLimiterBackend:
    async def check(self, key: str, limit: int, window: int) -> tuple[bool, int, int]:
        """Return (allowed, remaining, retry_after_seconds)."""
        raise NotImplementedError


class _MemoryBackend(_RateLimiterBackend):
    """Per-process sliding window. Dev only."""

    def __init__(self) -> None:
        self._requests: dict[str, list[float]] = defaultdict(list)

    async def check(self, key: str, limit: int, window: int) -> tuple[bool, int, int]:
        now = time.time()
        window_start = now - window
        bucket = [ts for ts in self._requests[key] if ts > window_start]
        if len(bucket) >= limit:
            oldest = min(bucket)
            retry_after = max(int(oldest + window - now) + 1, 1)
            self._requests[key] = bucket
            return False, 0, retry_after
        bucket.append(now)
        self._requests[key] = bucket
        return True, limit - len(bucket), window


class _RedisBackend(_RateLimiterBackend):
    """Fixed-window via INCR + EXPIRE. Atomic and distributed-safe."""

    def __init__(self, client) -> None:
        self._client = client

    async def check(self, key: str, limit: int, window: int) -> tuple[bool, int, int]:
        # Bucket by window-aligned epoch so INCR is atomic per-window.
        bucket = int(time.time() // window)
        redis_key = f"ratelimit:{key}:{bucket}"
        pipe = self._client.pipeline()
        pipe.incr(redis_key, 1)
        pipe.expire(redis_key, window)
        count, _ = await pipe.execute()
        count = int(count)
        if count > limit:
            # Retry-after is the remaining time in this bucket.
            retry_after = window - int(time.time()) % window
            return False, 0, max(retry_after, 1)
        return True, limit - count, window


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limit per authenticated subject (or IP fallback)."""

    def __init__(
        self,
        app,
        requests_per_window: int,
        window_seconds: int,
        backend: _RateLimiterBackend,
    ):
        super().__init__(app)
        self.limit = requests_per_window
        self.window = window_seconds
        self.backend = backend

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in {"/health", "/health/ready", "/health/live"}:
            return await call_next(request)

        key = self._identity_key(request)
        allowed, remaining, retry_after = await self.backend.check(key, self.limit, self.window)

        if not allowed:
            logger.warning("rate_limit_exceeded", key=key)
            rate_limit_exceeded_total.inc()
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded. Please slow down."},
                headers={"Retry-After": str(retry_after)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

    def _identity_key(self, request: Request) -> str:
        """Prefer user identity over IP. Falls back to IP when unauthenticated."""
        api_key = request.headers.get("X-API-Key")
        if api_key:
            # Hashed to avoid using the secret as a key in Redis.
            import hashlib
            return "apikey:" + hashlib.sha256(api_key.encode()).hexdigest()[:32]
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            import hashlib
            return "bearer:" + hashlib.sha256(auth[7:].encode()).hexdigest()[:32]
        return "ip:" + get_client_ip(request)


def build_rate_limiter_backend(redis_client=None) -> _RateLimiterBackend:
    """Build the configured rate limiter backend. Caller provides Redis client in redis mode."""
    if settings.rate_limit_backend == "redis":
        if redis_client is None:
            raise RuntimeError(
                "RATE_LIMIT_BACKEND=redis requires a Redis client at startup. "
                "Wire one via main.py lifespan."
            )
        return _RedisBackend(redis_client)
    return _MemoryBackend()


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose body exceeds max_bytes.

    Checks Content-Length when the client provides it; streams and tallies
    otherwise so chunked uploads cannot sneak past by omitting the header.
    Runs ahead of Pydantic so we never buffer multi-GB bodies into RAM.
    """

    def __init__(self, app, max_bytes: int):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        declared = request.headers.get("content-length")
        if declared:
            try:
                declared_int = int(declared)
            except ValueError:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"detail": "Invalid Content-Length header"},
                )
            if declared_int > self.max_bytes:
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={"detail": f"Request body exceeds {self.max_bytes} bytes"},
                )

        # Defense against missing / lying Content-Length: wrap receive().
        # Count bytes as they stream in; abort once the cap is hit.
        max_bytes = self.max_bytes
        original_receive = request.receive
        seen = 0
        exceeded = False

        async def counting_receive():
            nonlocal seen, exceeded
            message = await original_receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                seen += len(body)
                if seen > max_bytes:
                    exceeded = True
                    # Drain quietly; the dispatch will return 413 below.
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        request = Request(request.scope, counting_receive, request._send)
        response = await call_next(request)
        if exceeded:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={"detail": f"Request body exceeds {max_bytes} bytes"},
            )
        return response


class HttpsEnforcementMiddleware(BaseHTTPMiddleware):
    """Reject plain-HTTP requests when settings.require_https is true.

    Honors X-Forwarded-Proto only when the immediate peer is in trusted_proxies.
    Health endpoints are exempt so liveness/readiness probes from the platform
    don't need TLS.
    """

    _EXEMPT_PATHS = {"/health", "/health/live", "/health/ready"}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not settings.require_https:
            return await call_next(request)
        if request.url.path in self._EXEMPT_PATHS:
            return await call_next(request)

        scheme = request.url.scheme
        if _peer_trusted(request):
            forwarded = request.headers.get("X-Forwarded-Proto")
            if forwarded:
                scheme = forwarded.split(",")[0].strip().lower()

        if scheme != "https":
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": "HTTPS is required for this endpoint."},
            )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """OWASP-recommended security headers. Tighter than the previous version."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()"
        )
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"

        # Content Security Policy.
        # script-src is strict — no 'unsafe-inline', no 'unsafe-eval'.
        # style-src permits 'unsafe-inline' only because React's style={{...}}
        # pattern (used for dynamic widths, progress bars, etc.) generates
        # inline attribute styles that CSP would otherwise block. A nonce-based
        # approach is a future improvement and requires middleware wiring.
        # img-src 'self' + blob: supports upload previews; data: is excluded.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' blob:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )

        if settings.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )

        return response
