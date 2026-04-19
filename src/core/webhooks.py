"""Outbound webhook delivery with HMAC-signed payloads and retry.

Events are enqueued as `WebhookDeliveryRecord` rows. A background worker
picks up due rows (`next_attempt_at <= now`), POSTs to the endpoint with an
`X-Signature: sha256=<hex>` header (HMAC over the raw JSON body with the
endpoint's `signing_secret`), and updates the row based on the response.

Deliveries are retried with exponential backoff up to `max_attempts`.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import async_session_maker
from src.core.db_models import WebhookDeliveryRecord, WebhookEndpointRecord

logger = structlog.get_logger("webhooks")


SIGNATURE_HEADER = "X-Signature"
EVENT_HEADER = "X-Event-Type"
DELIVERY_HEADER = "X-Delivery-Id"


def sign_payload(secret: str, body: bytes) -> str:
    """Return `sha256=<hex>` HMAC signature. Receiver verifies with compare_digest."""
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


async def emit_appeal_event(
    db: AsyncSession,
    *,
    org_id: str,
    event_type: str,
    payload: dict,
) -> None:
    """Enqueue a delivery for each active endpoint in the org subscribed to the event.

    The caller provides an already-scrubbed payload (no PHI). The record is
    flushed in the caller's transaction; the delivery worker picks it up via
    its own session on the next poll.
    """
    result = await db.execute(
        select(WebhookEndpointRecord).where(
            and_(
                WebhookEndpointRecord.org_id == org_id,
                WebhookEndpointRecord.is_active.is_(True),
            )
        )
    )
    endpoints = list(result.scalars().all())
    for ep in endpoints:
        events = ep.events or []
        if events and event_type not in events:
            continue
        db.add(
            WebhookDeliveryRecord(
                id=str(uuid.uuid4()),
                endpoint_id=ep.id,
                org_id=org_id,
                event_type=event_type,
                payload_json=payload,
                next_attempt_at=datetime.now(timezone.utc),
                max_attempts=settings.webhook_max_attempts,
            )
        )
    await db.flush()


async def _pending_deliveries(db: AsyncSession, limit: int) -> list[WebhookDeliveryRecord]:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(WebhookDeliveryRecord)
        .where(
            and_(
                WebhookDeliveryRecord.delivered_at.is_(None),
                WebhookDeliveryRecord.next_attempt_at <= now,
                WebhookDeliveryRecord.attempts < WebhookDeliveryRecord.max_attempts,
            )
        )
        .order_by(WebhookDeliveryRecord.next_attempt_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


def _backoff(attempts: int) -> timedelta:
    """Exponential backoff: 5s, 10s, 30s, 2m, 10m, 30m, cap at 1h."""
    schedule = [5, 10, 30, 120, 600, 1800, 3600]
    i = min(attempts, len(schedule) - 1)
    return timedelta(seconds=schedule[i])


async def deliver_one(
    db: AsyncSession, delivery: WebhookDeliveryRecord, client: httpx.AsyncClient
) -> None:
    endpoint = await db.get(WebhookEndpointRecord, delivery.endpoint_id)
    if endpoint is None or not endpoint.is_active:
        # Endpoint was deleted/disabled mid-flight; mark delivered so we stop
        # trying. The event is still in structlog.
        delivery.delivered_at = datetime.now(timezone.utc)
        delivery.last_error = "endpoint inactive or deleted"
        return

    body = json.dumps(
        {
            "id": delivery.id,
            "event": delivery.event_type,
            "payload": delivery.payload_json or {},
        },
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    signature = sign_payload(endpoint.signing_secret, body)

    delivery.attempts += 1
    try:
        response = await client.post(
            endpoint.url,
            content=body,
            headers={
                "Content-Type": "application/json",
                SIGNATURE_HEADER: signature,
                EVENT_HEADER: delivery.event_type,
                DELIVERY_HEADER: delivery.id,
            },
            timeout=settings.webhook_delivery_timeout_seconds,
        )
        delivery.last_status = response.status_code
        endpoint.last_delivery_at = datetime.now(timezone.utc)
        endpoint.last_delivery_status = response.status_code
        if 200 <= response.status_code < 300:
            delivery.delivered_at = datetime.now(timezone.utc)
            delivery.last_error = None
        else:
            delivery.last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            delivery.next_attempt_at = datetime.now(timezone.utc) + _backoff(delivery.attempts)
    except Exception as e:
        delivery.last_status = None
        delivery.last_error = f"{type(e).__name__}: {str(e)[:200]}"
        delivery.next_attempt_at = datetime.now(timezone.utc) + _backoff(delivery.attempts)

    # If we've exhausted attempts, stop scheduling.
    if delivery.attempts >= delivery.max_attempts and delivery.delivered_at is None:
        delivery.next_attempt_at = None


class WebhookDeliveryWorker:
    """Background task that drains pending webhook deliveries."""

    def __init__(self, poll_interval_seconds: float = 5.0, batch: int = 50) -> None:
        self.poll_interval = poll_interval_seconds
        self.batch = batch
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="webhook_delivery_worker")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            await self._task

    async def _run(self) -> None:
        async with httpx.AsyncClient() as client:
            while not self._stopping.is_set():
                try:
                    await self._tick(client)
                except Exception as e:
                    logger.error("webhook_worker_tick_failed", error=str(e))
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=self.poll_interval
                    )
                except asyncio.TimeoutError:
                    continue

    async def _tick(self, client: httpx.AsyncClient) -> None:
        async with async_session_maker() as db:
            pending = await _pending_deliveries(db, self.batch)
            for delivery in pending:
                await deliver_one(db, delivery, client)
            await db.commit()


_worker: WebhookDeliveryWorker | None = None


async def start_webhook_worker() -> None:
    global _worker
    if _worker is not None:
        return
    _worker = WebhookDeliveryWorker()
    await _worker.start()


async def stop_webhook_worker() -> None:
    global _worker
    if _worker is not None:
        await _worker.stop()
        _worker = None
