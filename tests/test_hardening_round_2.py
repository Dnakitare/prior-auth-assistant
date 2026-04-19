"""Tests for the second-round hardening fixes.

Covers:
- Audit sequence retry under simulated concurrent writers
- Audit safe_log swallows DB errors but still emits structlog
- Body-size limit middleware rejects oversize requests
- Login lockout after repeated failures
- Admin API-key endpoints: create/list/revoke + tenant scoping
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient

from src.core.audit import AuditAction, audit
from src.core.database import async_session_maker
from src.core.db_models import ApiKeyRecord, AuditLogRecord
from src.core.lockout import LoginLockout
from src.core.repositories import ApiKeyRepository
from src.core.security import hash_api_key

from .conftest import TEST_API_KEY_ORG_A, TEST_PLAINTEXT_KEY_A


class TestAuditSequenceConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_writes_all_land(self):
        """N concurrent audit writes all commit. We don't call verify_chain
        here because the rest of the suite deliberately tampers with audit
        rows; instead we verify every row we just wrote has a unique
        sequence and non-null row_hmac.
        """
        N = 20
        marker = f"concurrent-{uuid.uuid4().hex}"

        async def one_write(i: int) -> None:
            async with async_session_maker() as db:
                await audit.log(
                    db=db,
                    action=AuditAction.APPEAL_READ,
                    user_id=f"{marker}-{i}",
                    resource_type="appeal",
                    resource_id=f"r{i}",
                )
                await db.commit()

        await asyncio.gather(*[one_write(i) for i in range(N)])

        from sqlalchemy import select, and_

        async with async_session_maker() as db:
            result = await db.execute(
                select(AuditLogRecord.sequence, AuditLogRecord.row_hmac).where(
                    AuditLogRecord.user_id.like(f"{marker}%")
                )
            )
            rows = list(result.all())

        assert len(rows) == N, f"expected {N} writes, got {len(rows)}"
        sequences = [r[0] for r in rows]
        assert len(set(sequences)) == N, "duplicate sequences — unique constraint broken"
        assert all(r[1] for r in rows), "some row_hmac values are null"


class TestAuditSafeLog:
    @pytest.mark.asyncio
    async def test_safe_log_swallows_errors(self, monkeypatch):
        """safe_log returns None on error but doesn't raise.

        audit.log now opens its own admin-context session for the write,
        so the `db` param is no longer the failure injection point. We
        patch the admin session maker to raise instead.
        """
        import src.core.audit as audit_mod

        def _broken_maker(*a, **kw):
            raise RuntimeError("simulated admin session failure")

        monkeypatch.setattr(audit_mod, "async_admin_session_maker", _broken_maker)

        result = await audit.safe_log(
            db=None,  # unused now
            action=AuditAction.APPEAL_READ,
            user_id="u",
            resource_id="r",
        )
        assert result is None


class TestBodySizeLimit:
    @pytest.mark.asyncio
    async def test_oversize_content_length_rejected(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        # Body-limit middleware checks declared Content-Length; we fake one
        # larger than the configured cap (2 × MAX_UPLOAD_SIZE_MB → 20 MB default).
        huge = 25 * 1024 * 1024
        response = await async_client.post(
            "/api/v1/appeals/text",
            content=b"x" * 100,  # actual body small — middleware trusts header too
            headers={
                **auth_headers,
                "Content-Type": "application/json",
                "Content-Length": str(huge),
            },
        )
        assert response.status_code == 413


class TestLoginLockout:
    @pytest_asyncio.fixture
    async def fresh_lockout(self):
        # Isolate from the module-level singleton that other tests may have touched.
        return LoginLockout(max_failures=3, window_seconds=60)

    @pytest.mark.asyncio
    async def test_locks_after_threshold(self, fresh_lockout):
        for _ in range(3):
            await fresh_lockout.record_failure("1.2.3.4")
        locked, retry = await fresh_lockout.is_locked("1.2.3.4")
        assert locked is True
        assert retry > 0

    @pytest.mark.asyncio
    async def test_reset_clears_counter(self, fresh_lockout):
        for _ in range(3):
            await fresh_lockout.record_failure("9.9.9.9")
        await fresh_lockout.reset("9.9.9.9")
        locked, _ = await fresh_lockout.is_locked("9.9.9.9")
        assert locked is False

    @pytest.mark.asyncio
    async def test_other_ips_not_affected(self, fresh_lockout):
        for _ in range(3):
            await fresh_lockout.record_failure("8.8.8.8")
        locked, _ = await fresh_lockout.is_locked("1.1.1.1")
        assert locked is False


class TestAdminApiKeyEndpoints:
    """Admin endpoints require the `admin` scope. Seed a dedicated admin key
    so we can exercise the full HTTP surface."""

    @pytest_asyncio.fixture
    async def admin_headers(self):
        import uuid as _uuid
        plaintext = f"pa_admin-{_uuid.uuid4().hex}"
        async with async_session_maker() as db:
            repo = ApiKeyRepository(db)
            await repo.create(
                plaintext=plaintext,
                org_id="",  # global admin (no org scoping)
                name="admin",
                scopes=["admin"],
            )
            await db.commit()
        return {"X-API-Key": plaintext}

    @pytest.mark.asyncio
    async def test_create_list_revoke_flow(
        self, async_client: AsyncClient, admin_headers: dict
    ):
        # create
        r = await async_client.post(
            "/api/v1/admin/api-keys",
            json={
                "org_id": "tenant-X",
                "name": "test-key",
                "scopes": ["appeals:read", "appeals:write"],
            },
            headers=admin_headers,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        key_id = body["key_id"]
        plaintext = body["plaintext_key"]
        assert plaintext.startswith("pa_")

        # list filter
        r = await async_client.get(
            "/api/v1/admin/api-keys?org_id=tenant-X", headers=admin_headers
        )
        assert r.status_code == 200
        assert any(item["key_id"] == key_id for item in r.json())

        # the newly-created key authenticates
        me = await async_client.get(
            f"/api/v1/appeals/{uuid.uuid4()}", headers={"X-API-Key": plaintext}
        )
        # Either 404 (auth ok, appeal not found) or 401 (if scopes matter).
        # Our endpoint doesn't enforce a scope, so 404 is expected.
        assert me.status_code == 404

        # revoke
        r = await async_client.delete(
            f"/api/v1/admin/api-keys/{key_id}", headers=admin_headers
        )
        assert r.status_code == 204

        # revoked key is rejected
        r = await async_client.get(
            f"/api/v1/appeals/{uuid.uuid4()}", headers={"X-API-Key": plaintext}
        )
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_non_admin_rejected(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        r = await async_client.post(
            "/api/v1/admin/api-keys",
            json={"org_id": "x", "name": "x", "scopes": []},
            headers=auth_headers,
        )
        assert r.status_code == 403
