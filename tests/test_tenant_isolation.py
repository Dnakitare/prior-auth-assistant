"""Cross-tenant data isolation tests.

Tenant A creates an appeal; Tenant B tries to read it. Must return 404,
not 200 and not leak the existence of the row.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

# Direct DB inspection in tests uses the ADMIN session maker: since
# migration 006 the runtime role has no RLS bypass, so an org-less
# session would see zero rows on the Postgres CI job. (On SQLite the
# two makers are the same object.)
from src.core.database import async_admin_session_maker as async_session_maker
from src.core.models import AppealLetter, DenialExtraction, DenialReason
from src.core.repositories import AppealRepository

from .conftest import TEST_API_KEY_ORG_A


def _fixture_appeal() -> AppealLetter:
    return AppealLetter(
        id=str(uuid.uuid4()),
        denial_extraction=DenialExtraction(
            payer_name="BCBS",
            denial_reason=DenialReason.MEDICAL_NECESSITY,
            procedure_codes=["99213"],
            diagnosis_codes=["M54.5"],
            member_id="MEM-ISO",
            claim_number="CLM-ISO",
            raw_text="Denial text for isolation test",
        ),
        letter_content="Generated letter",
        required_attachments=[],
        generated_at=datetime.now(timezone.utc),
        confidence_score=0.9,
    )


@pytest.mark.asyncio
async def test_cross_tenant_read_returns_404(
    async_client: AsyncClient, auth_headers_b: dict
):
    """Seed an appeal under tenant A, read it as tenant B → must be 404."""
    appeal = _fixture_appeal()
    async with async_session_maker() as db:
        repo = AppealRepository(db)
        await repo.save(
            appeal,
            created_by="user-A",
            org_id=TEST_API_KEY_ORG_A,
            patient_name="A-Patient",
        )
        await db.commit()

    # Tenant B asks for tenant A's appeal.
    response = await async_client.get(
        f"/api/v1/appeals/{appeal.id}", headers=auth_headers_b
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_same_tenant_read_succeeds(
    async_client: AsyncClient, auth_headers: dict
):
    appeal = _fixture_appeal()
    async with async_session_maker() as db:
        repo = AppealRepository(db)
        await repo.save(
            appeal,
            created_by="user-A",
            org_id=TEST_API_KEY_ORG_A,
            patient_name="A-Patient",
        )
        await db.commit()

    response = await async_client.get(
        f"/api/v1/appeals/{appeal.id}", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["appeal_id"] == appeal.id


@pytest.mark.asyncio
async def test_unauthenticated_read_rejected(async_client: AsyncClient):
    response = await async_client.get(f"/api/v1/appeals/{uuid.uuid4()}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_api_key_rejected(async_client: AsyncClient):
    response = await async_client.get(
        f"/api/v1/appeals/{uuid.uuid4()}",
        headers={"X-API-Key": "pa_not-a-real-key"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_idempotency_key_dedupes(
    async_client: AsyncClient, auth_headers: dict, sample_appeal_letter
):
    """Two writes with the same Idempotency-Key produce one row, second returns same appeal."""
    appeal = sample_appeal_letter
    idem = str(uuid.uuid4())

    async with async_session_maker() as db:
        repo = AppealRepository(db)
        r1 = await repo.save(
            appeal,
            created_by="user-A",
            org_id=TEST_API_KEY_ORG_A,
            idempotency_key=idem,
        )
        await db.commit()

    # Attempt to save a different-id appeal with the same idempotency key in the same org.
    appeal2 = _fixture_appeal()
    async with async_session_maker() as db:
        repo = AppealRepository(db)
        r2 = await repo.save(
            appeal2,
            created_by="user-A",
            org_id=TEST_API_KEY_ORG_A,
            idempotency_key=idem,
        )
        await db.commit()

    assert r1.id == r2.id, "idempotency key must dedupe across attempts"
