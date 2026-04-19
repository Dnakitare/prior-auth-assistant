"""Authentication and authorization.

Two mechanisms are supported and both resolve to AuthenticatedUser:
- API key (X-API-Key header), validated against hashed rows in api_keys.
- JWT bearer token, issued by /auth/login, tracked in user_sessions. Revoking
  the session row (revoked_at) invalidates the JWT before its exp claim.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import get_session
from src.core.db_models import ApiKeyRecord, UserSessionRecord

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


class TokenPayload(BaseModel):
    sub: str
    exp: datetime
    iat: datetime
    jti: str  # session id — maps to user_sessions.id
    scope: list[str] = []
    org_id: str | None = None


class AuthenticatedUser(BaseModel):
    user_id: str
    org_id: str | None = None
    scopes: list[str] = []
    auth_method: str  # "api_key" or "jwt"
    session_id: str | None = None  # only for jwt


# --- hashing helpers --------------------------------------------------------

def hash_api_key(api_key: str) -> str:
    """SHA-256 hash (hex). 128-char column for future algorithm swaps."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """Return (plaintext, hash). Plaintext shown once to operator."""
    key = f"pa_{secrets.token_urlsafe(32)}"
    return key, hash_api_key(key)


# --- JWT issuance / decode --------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


async def set_rls_context(
    session: AsyncSession,
    *,
    org_id: str | None,
    is_admin: bool,
    source: str = "request",
) -> None:
    """Set Postgres RLS GUCs for the remainder of the transaction.

    Policies installed by migration 005 check `app.org_id` and `app.is_admin`
    on every tenant-scoped row. This must be called once per request after
    the authenticated principal is known, and also by any system code that
    opens a session directly (bootstrap, workers).

    `source` labels the caller for forensic audit (request / bootstrap /
    webhook_worker / test). Admin-context activations increment a metric so
    anomalous spikes are alertable even when the app that set them is
    compromised — the metric is read from outside the process.

    No-op on non-Postgres dialects. Uses set_config() so the value is
    parameterized rather than string-interpolated.
    """
    dialect = session.bind.dialect.name if session.bind else None

    # Only count + log admin bypasses on the dialect where RLS actually
    # applies. On SQLite (dev/tests) the "bypass" doesn't bypass anything,
    # so counting it would drown out meaningful signal from production.
    if is_admin and dialect == "postgresql":
        try:
            from src.core.metrics import rls_admin_bypass_total
            rls_admin_bypass_total.labels(source=source).inc()
        except Exception:  # metrics must never break auth
            pass
        import structlog as _structlog
        _structlog.get_logger("rls").info(
            "rls_admin_bypass",
            source=source,
            org_id=org_id,
        )

    if dialect != "postgresql":
        return
    await session.execute(
        text("SELECT set_config('app.org_id', :v, true)"),
        {"v": org_id or ""},
    )
    await session.execute(
        text("SELECT set_config('app.is_admin', :v, true)"),
        {"v": "true" if is_admin else "false"},
    )


async def create_access_token(
    session: AsyncSession,
    subject: str,
    scopes: list[str] | None = None,
    org_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Issue a JWT and persist its session row for revocation tracking."""
    if expires_delta is None:
        expires_delta = timedelta(hours=settings.jwt_expiration_hours)

    now = _now()
    expire = now + expires_delta
    jti = str(uuid.uuid4())

    payload = {
        "sub": subject,
        "exp": expire,
        "iat": now,
        "jti": jti,
        "scope": scopes or [],
        "org_id": org_id,
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    session.add(
        UserSessionRecord(
            id=jti,
            token_hash=hash_token(token),
            user_id=subject,
            org_id=org_id,
            scopes=scopes or [],
            created_at=now,
            expires_at=expire,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    await session.flush()
    return token


async def revoke_session(session: AsyncSession, session_id: str) -> bool:
    row = await session.get(UserSessionRecord, session_id)
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = _now()
    await session.flush()
    return True


def _decode_jwt(token: str) -> TokenPayload:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
        return TokenPayload(**payload)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# --- DB-backed validation ---------------------------------------------------

# Debounce last_used_at writes to at most once per LAST_USED_DEBOUNCE_SECONDS
# per key, avoiding hot-row contention under high RPS against the same key.
LAST_USED_DEBOUNCE_SECONDS = 60


async def _validate_api_key(session: AsyncSession, api_key: str) -> ApiKeyRecord | None:
    """Look up API key by hash. Uses hmac.compare_digest for defence-in-depth
    constant-time compare.
    """
    key_hash = hash_api_key(api_key)
    result = await session.execute(
        select(ApiKeyRecord).where(ApiKeyRecord.key_hash == key_hash)
    )
    record = result.scalar_one_or_none()
    if record is None:
        return None
    if not hmac.compare_digest(record.key_hash, key_hash):
        return None
    if not record.is_active or record.revoked_at is not None:
        return None
    if record.expires_at and record.expires_at < _now():
        return None

    # Conditional UPDATE: only touch the row if last_used_at is stale. Most
    # requests skip the write entirely. Uses a core UPDATE so we don't dirty
    # the ORM identity map on every auth call.
    now = _now()
    threshold = now - timedelta(seconds=LAST_USED_DEBOUNCE_SECONDS)
    await session.execute(
        update(ApiKeyRecord)
        .where(ApiKeyRecord.id == record.id)
        .where(
            or_(
                ApiKeyRecord.last_used_at.is_(None),
                ApiKeyRecord.last_used_at < threshold,
            )
        )
        .values(last_used_at=now)
        # Skip ORM session synchronization: the row's in-memory copy doesn't
        # need updating and comparing naive vs aware datetimes (SQLite gives
        # naive back even for tz-aware columns) breaks the evaluator.
        .execution_options(synchronize_session=False)
    )
    return record


async def _validate_jwt(session: AsyncSession, token: str) -> tuple[TokenPayload, UserSessionRecord] | None:
    payload = _decode_jwt(token)
    session_row = await session.get(UserSessionRecord, payload.jti)
    if session_row is None:
        return None
    if session_row.revoked_at is not None:
        return None
    if session_row.expires_at < _now():
        return None
    expected_hash = hash_token(token)
    if not hmac.compare_digest(session_row.token_hash, expected_hash):
        return None
    return payload, session_row


# --- FastAPI dependencies ---------------------------------------------------

async def get_current_user(
    request: Request,
    api_key: Annotated[str | None, Security(api_key_header)] = None,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)] = None,
    db: Annotated[AsyncSession, Depends(get_session)] = None,  # type: ignore[assignment]
) -> AuthenticatedUser:
    """Authenticate via API key or JWT. Raises 401 on failure."""
    if api_key:
        record = await _validate_api_key(db, api_key)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )
        user = AuthenticatedUser(
            user_id=f"apikey:{record.id}",
            org_id=record.org_id,
            scopes=record.scopes or [],
            auth_method="api_key",
        )
        await set_rls_context(
            db, org_id=user.org_id, is_admin="admin" in user.scopes
        )
        return user

    if bearer:
        result = await _validate_jwt(db, bearer.credentials)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or revoked token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        payload, _row = result
        user = AuthenticatedUser(
            user_id=payload.sub,
            org_id=payload.org_id,
            scopes=payload.scope,
            auth_method="jwt",
            session_id=payload.jti,
        )
        await set_rls_context(
            db, org_id=user.org_id, is_admin="admin" in user.scopes
        )
        return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide X-API-Key header or Bearer token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_optional_user(
    request: Request,
    api_key: Annotated[str | None, Security(api_key_header)] = None,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)] = None,
    db: Annotated[AsyncSession, Depends(get_session)] = None,  # type: ignore[assignment]
) -> AuthenticatedUser | None:
    try:
        return await get_current_user(request, api_key, bearer, db)
    except HTTPException:
        return None


def require_scope(required_scope: str):
    async def scope_checker(
        user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    ) -> AuthenticatedUser:
        if required_scope not in user.scopes and "admin" not in user.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Scope '{required_scope}' required",
            )
        return user

    return scope_checker


RequireAppealsRead = Annotated[AuthenticatedUser, Depends(require_scope("appeals:read"))]
RequireAppealsWrite = Annotated[AuthenticatedUser, Depends(require_scope("appeals:write"))]
RequireAdmin = Annotated[AuthenticatedUser, Depends(require_scope("admin"))]
