"""External audit sink: ships audit events to CloudWatch Logs.

The in-DB HMAC chain detects local tampering. For tamper-evidence under
application-layer RCE you need an external witness whose write interface the
application cannot rewrite after the fact. AWS CloudWatch Logs with a
retention policy + "retention lock" (or a Log Group backed by a destination
that uses S3 Object Lock) gives us that: the application can *append*, but
cannot mutate or delete existing entries within the retention window.

Design:
- A background task drains an asyncio.Queue of pending audit events.
- Events are posted in batches to the configured log group / stream.
- Enqueue never blocks the caller; on backpressure we drop (with a metric) —
  the DB + structlog copies remain authoritative. The external sink is an
  additional witness, not the primary record.
- Failures do not raise into HTTP handlers.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from typing import Any

import structlog

from src.core.config import settings
from src.core.metrics import audit_write_failures_total

logger = structlog.get_logger("audit_sink")


class _NoopSink:
    async def ship(self, event: dict[str, Any]) -> None:
        return

    async def close(self) -> None:
        return


class CloudWatchAuditSink:
    """Batches audit events into CloudWatch Logs.

    Uses boto3's sync client under a thread executor to avoid pulling in a
    second async AWS SDK. Batches flush every flush_interval_seconds or when
    the batch reaches max_batch_size, whichever comes first.
    """

    def __init__(
        self,
        log_group: str,
        log_stream: str | None = None,
        region: str | None = None,
        queue_maxsize: int = 10_000,
        max_batch_size: int = 500,
        flush_interval_seconds: float = 2.0,
    ) -> None:
        self.log_group = log_group
        # Per-instance stream so replicas don't serialize on the same stream
        # sequence token. Include host+pid for uniqueness.
        self.log_stream = log_stream or f"{socket.gethostname()}-{os.getpid()}"
        self.region = region
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_maxsize)
        self._max_batch_size = max_batch_size
        self._flush_interval = flush_interval_seconds
        self._client = None  # type: ignore[assignment]
        self._sequence_token: str | None = None
        self._worker: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    def _get_client(self):
        if self._client is None:
            import boto3  # lazy import so unit tests without AWS deps still run
            kwargs = {}
            if self.region:
                kwargs["region_name"] = self.region
            self._client = boto3.client("logs", **kwargs)
        return self._client

    async def start(self) -> None:
        """Create the log group/stream if missing, then kick off the worker."""
        await asyncio.to_thread(self._ensure_group_and_stream)
        self._worker = asyncio.create_task(self._run(), name="audit_sink_worker")
        logger.info("audit_sink_started", log_group=self.log_group, log_stream=self.log_stream)

    def _ensure_group_and_stream(self) -> None:
        client = self._get_client()
        try:
            client.create_log_group(logGroupName=self.log_group)
        except client.exceptions.ResourceAlreadyExistsException:
            pass
        try:
            client.create_log_stream(logGroupName=self.log_group, logStreamName=self.log_stream)
        except client.exceptions.ResourceAlreadyExistsException:
            pass

    async def ship(self, event: dict[str, Any]) -> None:
        """Enqueue an event. Never blocks; drops (with a metric) on backpressure."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            audit_write_failures_total.inc()
            logger.warning("audit_sink_backpressure_drop")

    async def close(self) -> None:
        self._stopping.set()
        if self._worker is not None:
            await self._worker

    async def _run(self) -> None:
        while not self._stopping.is_set():
            batch = await self._collect_batch()
            if not batch:
                continue
            try:
                await asyncio.to_thread(self._put_batch, batch)
            except Exception as e:
                audit_write_failures_total.inc()
                logger.error(
                    "audit_sink_put_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    batch_size=len(batch),
                )

    async def _collect_batch(self) -> list[dict[str, Any]]:
        """Collect up to max_batch_size events or wait flush_interval seconds."""
        try:
            first = await asyncio.wait_for(self._queue.get(), timeout=self._flush_interval)
        except asyncio.TimeoutError:
            return []
        batch = [first]
        while len(batch) < self._max_batch_size:
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch

    def _put_batch(self, batch: list[dict[str, Any]]) -> None:
        client = self._get_client()
        events = [
            {"timestamp": int(time.time() * 1000), "message": json.dumps(e, default=str)}
            for e in batch
        ]
        kwargs = dict(
            logGroupName=self.log_group,
            logStreamName=self.log_stream,
            logEvents=events,
        )
        if self._sequence_token:
            kwargs["sequenceToken"] = self._sequence_token
        try:
            resp = client.put_log_events(**kwargs)
            self._sequence_token = resp.get("nextSequenceToken")
        except client.exceptions.InvalidSequenceTokenException as e:
            # Recover the expected token from the exception message and retry once.
            self._sequence_token = e.response["expectedSequenceToken"]
            kwargs["sequenceToken"] = self._sequence_token
            resp = client.put_log_events(**kwargs)
            self._sequence_token = resp.get("nextSequenceToken")


_audit_sink: CloudWatchAuditSink | _NoopSink = _NoopSink()


def get_audit_sink() -> CloudWatchAuditSink | _NoopSink:
    return _audit_sink


async def configure_audit_sink() -> None:
    """Wire the audit sink from settings. Idempotent.

    When AUDIT_SINK_CLOUDWATCH_GROUP is set, create the CloudWatch sink and
    start its worker. Otherwise remain the no-op sink.
    """
    global _audit_sink
    if not settings.audit_sink_cloudwatch_group:
        return
    sink = CloudWatchAuditSink(
        log_group=settings.audit_sink_cloudwatch_group,
        region=settings.aws_region or None,
    )
    try:
        await sink.start()
    except Exception as e:
        logger.error("audit_sink_start_failed", error=str(e))
        # Leave the no-op sink in place so audits still land in DB + structlog.
        return
    _audit_sink = sink


async def shutdown_audit_sink() -> None:
    global _audit_sink
    sink = _audit_sink
    _audit_sink = _NoopSink()
    await sink.close()
