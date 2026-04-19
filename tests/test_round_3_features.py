"""Tests for the third-round launch-readiness features.

Covers:
- Per-org LLM quota enforcement (QuotaExceeded, daily rollover)
- Appeal status transitions (PATCH endpoint + webhook emission)
- Webhook admin endpoints (create, list, signed payload)
- Webhook signature format
- /metrics endpoint exposes Prometheus text
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient

from src.core.database import async_session_maker
from src.core.db_models import (
    AppealRecord,
    OrgQuotaRecord,
    WebhookDeliveryRecord,
    WebhookEndpointRecord,
)
from src.core.models import AppealLetter, DenialExtraction, DenialReason
from src.core.quota import QuotaExceeded, check_and_reserve
from src.core.repositories import AppealRepository, ApiKeyRepository
from src.core.webhooks import sign_payload

from .conftest import TEST_API_KEY_ORG_A


class TestQuota:
    @pytest.mark.asyncio
    async def test_reserve_within_budget(self):
        async with async_session_maker() as db:
            # Set a 1000-token daily budget for this test org.
            db.add(
                OrgQuotaRecord(
                    org_id="quota-ok",
                    daily_token_budget=1000,
                    tokens_used_today=0,
                    tokens_used_month=0,
                    day_window_start=datetime.now(timezone.utc),
                    month_window_start=datetime.now(timezone.utc),
                )
            )
            await db.commit()
            status = await check_and_reserve(db, org_id="quota-ok", tokens=500)
            await db.commit()
        assert status.used_today == 500
        assert status.remaining_today == 500

    @pytest.mark.asyncio
    async def test_budget_exceeded(self):
        async with async_session_maker() as db:
            db.add(
                OrgQuotaRecord(
                    org_id="quota-over",
                    daily_token_budget=100,
                    tokens_used_today=90,
                    tokens_used_month=90,
                    day_window_start=datetime.now(timezone.utc),
                    month_window_start=datetime.now(timezone.utc),
                )
            )
            await db.commit()
            with pytest.raises(QuotaExceeded):
                await check_and_reserve(db, org_id="quota-over", tokens=50)

    @pytest.mark.asyncio
    async def test_unlimited_budget(self):
        async with async_session_maker() as db:
            db.add(
                OrgQuotaRecord(
                    org_id="quota-unlimited",
                    daily_token_budget=0,
                    tokens_used_today=0,
                    tokens_used_month=0,
                    day_window_start=datetime.now(timezone.utc),
                    month_window_start=datetime.now(timezone.utc),
                )
            )
            await db.commit()
            status = await check_and_reserve(
                db, org_id="quota-unlimited", tokens=1_000_000
            )
        assert status.remaining_today == -1

    @pytest.mark.asyncio
    async def test_daily_window_rollover(self):
        async with async_session_maker() as db:
            yesterday = datetime.now(timezone.utc) - timedelta(days=2)
            db.add(
                OrgQuotaRecord(
                    org_id="quota-rollover",
                    daily_token_budget=100,
                    tokens_used_today=90,  # stale from prior day
                    tokens_used_month=90,
                    day_window_start=yesterday,
                    month_window_start=yesterday,
                )
            )
            await db.commit()
            status = await check_and_reserve(
                db, org_id="quota-rollover", tokens=50
            )
        # Rollover zeroed the daily counter, so 50 is within the 100 budget.
        assert status.used_today == 50


class TestAppealStatusTransition:
    @pytest_asyncio.fixture
    async def seeded_appeal(self) -> str:
        appeal = AppealLetter(
            id=str(uuid.uuid4()),
            denial_extraction=DenialExtraction(
                payer_name="BCBS",
                denial_reason=DenialReason.MEDICAL_NECESSITY,
                raw_text="denial raw",
            ),
            letter_content="letter content",
            required_attachments=[],
            generated_at=datetime.now(timezone.utc),
            confidence_score=0.8,
        )
        async with async_session_maker() as db:
            repo = AppealRepository(db)
            await repo.save(
                appeal, created_by="u", org_id=TEST_API_KEY_ORG_A, patient_name="P"
            )
            await db.commit()
        return appeal.id

    @pytest.mark.asyncio
    async def test_status_patch_succeeds(
        self, async_client: AsyncClient, auth_headers: dict, seeded_appeal: str
    ):
        r = await async_client.patch(
            f"/api/v1/appeals/{seeded_appeal}/status",
            json={"status": "submitted"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        async with async_session_maker() as db:
            record = await db.get(AppealRecord, seeded_appeal)
        assert record.status == "submitted"

    @pytest.mark.asyncio
    async def test_invalid_status_rejected(
        self, async_client: AsyncClient, auth_headers: dict, seeded_appeal: str
    ):
        r = await async_client.patch(
            f"/api/v1/appeals/{seeded_appeal}/status",
            json={"status": "completely-made-up"},
            headers=auth_headers,
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_cross_tenant_patch_returns_404(
        self, async_client: AsyncClient, auth_headers_b: dict, seeded_appeal: str
    ):
        r = await async_client.patch(
            f"/api/v1/appeals/{seeded_appeal}/status",
            json={"status": "submitted"},
            headers=auth_headers_b,
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_status_change_enqueues_webhook_delivery(
        self, async_client: AsyncClient, auth_headers: dict, seeded_appeal: str
    ):
        # Register a webhook endpoint subscribed to the event.
        async with async_session_maker() as db:
            db.add(
                WebhookEndpointRecord(
                    id=str(uuid.uuid4()),
                    org_id=TEST_API_KEY_ORG_A,
                    url="https://example.invalid/hook",
                    signing_secret="test-secret",
                    events=["appeal.status_changed"],
                    is_active=True,
                )
            )
            await db.commit()

        r = await async_client.patch(
            f"/api/v1/appeals/{seeded_appeal}/status",
            json={"status": "approved"},
            headers=auth_headers,
        )
        assert r.status_code == 200

        async with async_session_maker() as db:
            from sqlalchemy import select

            result = await db.execute(
                select(WebhookDeliveryRecord).where(
                    WebhookDeliveryRecord.org_id == TEST_API_KEY_ORG_A
                )
            )
            deliveries = list(result.scalars().all())
        assert any(
            d.event_type == "appeal.status_changed"
            and d.payload_json.get("appeal_id") == seeded_appeal
            for d in deliveries
        )


class TestWebhookSignature:
    def test_signature_format_and_determinism(self):
        body = b'{"event":"appeal.status_changed"}'
        sig1 = sign_payload("secret", body)
        sig2 = sign_payload("secret", body)
        assert sig1 == sig2
        assert sig1.startswith("sha256=")

    def test_signature_differs_by_secret(self):
        body = b"same body"
        assert sign_payload("a", body) != sign_payload("b", body)


class TestWebhookAdmin:
    @pytest_asyncio.fixture
    async def admin_headers(self):
        plaintext = f"pa_admin-wh-{uuid.uuid4().hex}"
        async with async_session_maker() as db:
            repo = ApiKeyRepository(db)
            await repo.create(
                plaintext=plaintext,
                org_id="",  # global admin
                name="admin",
                scopes=["admin"],
            )
            await db.commit()
        return {"X-API-Key": plaintext}

    @pytest.mark.asyncio
    async def test_create_lists_then_delete(
        self, async_client: AsyncClient, admin_headers: dict
    ):
        r = await async_client.post(
            "/api/v1/admin/webhooks",
            json={
                "url": "https://example.invalid/hooks/x",
                "events": ["appeal.status_changed"],
                "org_id": "wh-test-org",
            },
            headers=admin_headers,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["signing_secret"]
        wid = body["id"]

        r = await async_client.get(
            "/api/v1/admin/webhooks?org_id=wh-test-org", headers=admin_headers
        )
        assert r.status_code == 200
        assert any(item["id"] == wid for item in r.json())

        r = await async_client.delete(
            f"/api/v1/admin/webhooks/{wid}", headers=admin_headers
        )
        assert r.status_code == 204


class TestMetricsEndpoint:
    @pytest.mark.asyncio
    async def test_metrics_returns_prometheus_text(self, async_client: AsyncClient):
        # Trigger something that increments a counter first.
        await async_client.get("/")
        r = await async_client.get("/metrics")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")
        body = r.text
        # The metric names declared in src/core/metrics.py should be present.
        for metric in (
            "http_requests_total",
            "http_request_duration_seconds",
            "llm_calls_total",
            "rate_limit_exceeded_total",
        ):
            assert metric in body
