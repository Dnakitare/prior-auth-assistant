"""Authentication endpoints: token issuance via API key exchange, logout.

We do not implement a username/password flow here — the intended principal
model is service-to-service (API key) with optional short-lived JWTs minted
from a valid API key. Extend later with an IdP (OIDC/SAML) when human users
are onboarded.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import AuditAction, audit
from src.core.config import settings
from src.core.database import get_session
from src.core.lockout import login_lockout
from src.core.repositories import ApiKeyRepository
from src.core.security import (
    AuthenticatedUser,
    create_access_token,
    get_current_user,
    hash_api_key,
    revoke_session,
)

router = APIRouter()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = Field(default="bearer")
    expires_in: int  # seconds


@router.post(
    "/auth/token",
    response_model=TokenResponse,
    responses={401: {"description": "Invalid API key"}},
)
async def exchange_api_key_for_token(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> TokenResponse:
    """Exchange an API key for a short-lived JWT.

    Rate-limited per-IP after repeated failures (see src/core/lockout.py).
    Successful exchanges clear the counter for that IP.
    """
    client_ip = getattr(request.state, "client_ip", None) or "unknown"
    locked, retry_after = await login_lockout.is_locked(client_ip)
    if locked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed authentication attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    if not x_api_key:
        await login_lockout.record_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="X-API-Key header required"
        )
    repo = ApiKeyRepository(db)
    record = await repo.get_by_hash(hash_api_key(x_api_key))
    if record is None or not record.is_active or record.revoked_at is not None:
        await login_lockout.record_failure(client_ip)
        await audit.safe_log(
            db=db,
            action=AuditAction.LOGIN_FAILURE,
            success=False,
            ip_address=client_ip,
            request_id=getattr(request.state, "request_id", None),
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    if record.expires_at and record.expires_at < datetime.now(timezone.utc):
        await login_lockout.record_failure(client_ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key expired")

    # Success — clear the IP's failure counter so retries aren't penalized later.
    await login_lockout.reset(client_ip)

    expires_in = timedelta(hours=settings.jwt_expiration_hours)
    token = await create_access_token(
        db,
        subject=f"apikey:{record.id}",
        scopes=record.scopes or [],
        org_id=record.org_id,
        ip_address=getattr(request.state, "client_ip", None),
        user_agent=request.headers.get("User-Agent"),
        expires_delta=expires_in,
    )
    await audit.safe_log(
        db=db,
        action=AuditAction.LOGIN_SUCCESS,
        user_id=f"apikey:{record.id}",
        org_id=record.org_id,
        ip_address=getattr(request.state, "client_ip", None),
        request_id=getattr(request.state, "request_id", None),
    )
    return TokenResponse(access_token=token, expires_in=int(expires_in.total_seconds()))


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Revoke the caller's current JWT session. No-op for API-key auth."""
    if user.auth_method != "jwt" or user.session_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Logout applies to JWT sessions only.",
        )
    await revoke_session(db, user.session_id)
    await audit.safe_log(
        db=db,
        action=AuditAction.LOGOUT,
        user_id=user.user_id,
        org_id=user.org_id,
        ip_address=getattr(request.state, "client_ip", None),
        request_id=getattr(request.state, "request_id", None),
    )
