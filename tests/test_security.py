"""Tests for security.py: API key auth, JWT issuance + revocation, timing safety."""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import pytest_asyncio

from src.core.config import settings
from src.core.database import async_session_maker
from src.core.db_models import ApiKeyRecord, UserSessionRecord
from src.core.repositories import ApiKeyRepository, SessionRepository
from src.core.security import (
    AuthenticatedUser,
    create_access_token,
    hash_api_key,
    revoke_session,
    _validate_api_key,
    _validate_jwt,
)


class TestApiKeyValidation:
    @pytest_asyncio.fixture
    async def seeded_key(self):
        import uuid
        plaintext = f"pa_unit-test-{uuid.uuid4().hex}"
        async with async_session_maker() as db:
            repo = ApiKeyRepository(db)
            record = await repo.create(
                plaintext=plaintext,
                org_id="unit-org",
                name="unit",
                scopes=["appeals:read"],
            )
            await db.commit()
            return plaintext, record.id

    @pytest.mark.asyncio
    async def test_valid_key_resolves(self, seeded_key):
        plaintext, _ = seeded_key
        async with async_session_maker() as db:
            record = await _validate_api_key(db, plaintext)
        assert record is not None
        assert record.org_id == "unit-org"

    @pytest.mark.asyncio
    async def test_unknown_key_rejected(self):
        async with async_session_maker() as db:
            record = await _validate_api_key(db, "pa_does-not-exist")
        assert record is None

    @pytest.mark.asyncio
    async def test_empty_key_rejected(self):
        async with async_session_maker() as db:
            record = await _validate_api_key(db, "")
        assert record is None

    @pytest.mark.asyncio
    async def test_revoked_key_rejected(self, seeded_key):
        plaintext, key_id = seeded_key
        async with async_session_maker() as db:
            repo = ApiKeyRepository(db)
            await repo.revoke(key_id)
            await db.commit()
            record = await _validate_api_key(db, plaintext)
        assert record is None

    def test_hash_is_deterministic(self):
        assert hash_api_key("same-input") == hash_api_key("same-input")
        assert hash_api_key("a") != hash_api_key("b")

    def test_hash_is_constant_length(self):
        # SHA-256 hex is always 64 chars — lets us compare_digest safely.
        assert len(hash_api_key("x")) == 64
        assert len(hash_api_key("x" * 10000)) == 64


class TestJWTLifecycle:
    @pytest.mark.asyncio
    async def test_token_persists_session_row(self):
        async with async_session_maker() as db:
            token = await create_access_token(
                db, subject="user-1", scopes=["appeals:read"], org_id="org-1"
            )
            await db.commit()

        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
        assert payload["sub"] == "user-1"
        assert "appeals:read" in payload["scope"]
        async with async_session_maker() as db:
            row = await db.get(UserSessionRecord, payload["jti"])
        assert row is not None
        assert row.revoked_at is None

    @pytest.mark.asyncio
    async def test_revoked_session_rejects_token(self):
        async with async_session_maker() as db:
            token = await create_access_token(db, subject="user-revoke")
            await db.commit()

        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        async with async_session_maker() as db:
            ok = await revoke_session(db, payload["jti"])
            await db.commit()
        assert ok is True

        async with async_session_maker() as db:
            result = await _validate_jwt(db, token)
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_token_rejected(self):
        async with async_session_maker() as db:
            token = await create_access_token(
                db, subject="user-exp", expires_delta=timedelta(seconds=-1)
            )
            await db.commit()

        async with async_session_maker() as db:
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc:
                await _validate_jwt(db, token)
            assert exc.value.status_code == 401


class TestAuthenticatedUser:
    def test_user_creation(self):
        user = AuthenticatedUser(
            user_id="u", org_id="o", scopes=["a:r"], auth_method="jwt", session_id="s"
        )
        assert user.user_id == "u"
        assert user.session_id == "s"

    def test_session_id_optional_for_api_key(self):
        user = AuthenticatedUser(user_id="u", auth_method="api_key")
        assert user.session_id is None
