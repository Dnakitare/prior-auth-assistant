"""OpenTelemetry wiring.

Enabled when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Instruments FastAPI,
SQLAlchemy, and httpx. LLM calls get an explicit span in `integrations/llm.py`
via `trace_llm_call()`.

PHI safety: span attributes are opt-in per site. We never attach denial_text,
patient_name, etc. to spans — only operation name, duration, and
outcome/status. Exporter configuration is from env (standard OTLP vars).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import structlog

from src.core.config import settings

logger = structlog.get_logger("tracing")


def configure_tracing(app) -> None:
    """Install FastAPI/SQLAlchemy/httpx instrumentation. No-op when disabled."""
    if not settings.otel_exporter_otlp_endpoint:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "otel_libs_missing",
            message="OTel configured but opentelemetry packages not installed; skipping",
        )
        return

    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": "1.0.0",
            "deployment.environment": settings.app_env,
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,health/live,health/ready,metrics")
    HTTPXClientInstrumentor().instrument()
    # SQLAlchemy instrumentation needs the sync bind engine. Attach on the
    # async engine's `sync_engine` so spans cover the actual DB calls.
    from src.core.database import engine

    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    logger.info("otel_configured", endpoint=settings.otel_exporter_otlp_endpoint)


def _get_tracer():
    try:
        from opentelemetry import trace
        return trace.get_tracer(__name__)
    except ImportError:
        return None


@contextmanager
def trace_llm_call(operation: str) -> Iterator[None]:
    """Wrap an LLM call in a span. No-op when tracing isn't configured.

    Attributes intentionally omit anything PHI-adjacent.
    """
    tracer = _get_tracer()
    if tracer is None:
        yield
        return
    with tracer.start_as_current_span(f"llm.{operation}") as span:
        span.set_attribute("llm.operation", operation)
        span.set_attribute("llm.model", settings.llm_model)
        yield
