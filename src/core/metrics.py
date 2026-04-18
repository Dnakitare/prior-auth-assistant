"""Prometheus metrics.

Emits a small set of high-value counters and histograms. Kept minimal so the
/metrics endpoint is cheap and doesn't leak high-cardinality labels.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest

REGISTRY = CollectorRegistry()

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path_template", "status"],
    registry=REGISTRY,
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path_template"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
    registry=REGISTRY,
)

llm_calls_total = Counter(
    "llm_calls_total",
    "LLM API calls",
    ["operation", "outcome"],  # operation: extract|generate; outcome: ok|error|rate_limit
    registry=REGISTRY,
)

llm_call_duration_seconds = Histogram(
    "llm_call_duration_seconds",
    "LLM API call duration",
    ["operation"],
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60),
    registry=REGISTRY,
)

rate_limit_exceeded_total = Counter(
    "rate_limit_exceeded_total",
    "Rate limit rejections",
    registry=REGISTRY,
)

auth_failures_total = Counter(
    "auth_failures_total",
    "Authentication failures",
    ["kind"],  # kind: api_key|jwt|lockout
    registry=REGISTRY,
)

audit_write_failures_total = Counter(
    "audit_write_failures_total",
    "Audit-log DB write failures (still captured in structlog)",
    registry=REGISTRY,
)


def render_metrics() -> tuple[bytes, str]:
    """Return (body, content-type) suitable for an HTTP response."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
