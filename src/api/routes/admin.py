"""Admin endpoints for API key lifecycle.

All endpoints require the `admin` scope. API keys are returned in plaintext
exactly once, at creation time — the server only stores the SHA-256 hash
and cannot recover the plaintext later.
"""

from __future__ import annotations

import secrets
import uuid as _uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import AuditAction, audit
from src.core.database import get_session
from src.core.db_models import ApiKeyRecord, WebhookEndpointRecord
from src.core.repositories import ApiKeyRepository
from src.core.security import (
    AuthenticatedUser,
    generate_api_key,
    require_scope,
)

router = APIRouter()


class ApiKeyCreateRequest(BaseModel):
    org_id: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    scopes: list[str] = Field(default_factory=list, max_length=32)
    expires_at: datetime | None = None


class ApiKeyCreateResponse(BaseModel):
    key_id: str
    plaintext_key: str = Field(
        ..., description="Shown once at creation. Store securely; cannot be recovered."
    )
    org_id: str
    name: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime | None = None


class ApiKeyListItem(BaseModel):
    key_id: str
    org_id: str
    name: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
    is_active: bool


@router.post(
    "/admin/api-keys",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    request: Request,
    payload: ApiKeyCreateRequest,
    admin: Annotated[AuthenticatedUser, Depends(require_scope("admin"))],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ApiKeyCreateResponse:
    plaintext, _ = generate_api_key()
    repo = ApiKeyRepository(db)
    record = await repo.create(
        plaintext=plaintext,
        org_id=payload.org_id,
        name=payload.name,
        scopes=payload.scopes,
        expires_at=payload.expires_at,
    )
    await audit.safe_log(
        db=db,
        action=AuditAction.API_KEY_CREATE,
        user_id=admin.user_id,
        org_id=payload.org_id,
        resource_type="api_key",
        resource_id=record.id,
        ip_address=getattr(request.state, "client_ip", None),
        request_id=getattr(request.state, "request_id", None),
        name=payload.name,
        scopes=payload.scopes,
    )
    return ApiKeyCreateResponse(
        key_id=record.id,
        plaintext_key=plaintext,
        org_id=record.org_id,
        name=record.name,
        scopes=record.scopes or [],
        created_at=record.created_at,
        expires_at=record.expires_at,
    )


@router.get(
    "/admin/api-keys",
    response_model=list[ApiKeyListItem],
)
async def list_api_keys(
    admin: Annotated[AuthenticatedUser, Depends(require_scope("admin"))],
    db: Annotated[AsyncSession, Depends(get_session)],
    org_id: str | None = None,
) -> list[ApiKeyListItem]:
    """List keys. Admins scoped to a specific org see only their org; global
    admins (no org_id on their principal) can filter by ?org_id=... or see all."""
    query = select(ApiKeyRecord).order_by(ApiKeyRecord.created_at.desc())
    if admin.org_id:
        # Org-scoped admin: filter to their own org regardless of query arg.
        query = query.where(ApiKeyRecord.org_id == admin.org_id)
    elif org_id:
        query = query.where(ApiKeyRecord.org_id == org_id)
    result = await db.execute(query)
    rows = result.scalars().all()
    return [
        ApiKeyListItem(
            key_id=r.id,
            org_id=r.org_id,
            name=r.name,
            scopes=r.scopes or [],
            created_at=r.created_at,
            expires_at=r.expires_at,
            revoked_at=r.revoked_at,
            last_used_at=r.last_used_at,
            is_active=r.is_active,
        )
        for r in rows
    ]


@router.delete(
    "/admin/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_api_key(
    request: Request,
    key_id: str,
    admin: Annotated[AuthenticatedUser, Depends(require_scope("admin"))],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    record = await db.get(ApiKeyRecord, key_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
        )
    # Org-scoped admins can only revoke keys in their own org.
    if admin.org_id and record.org_id != admin.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

    repo = ApiKeyRepository(db)
    ok = await repo.revoke(record.id)
    if not ok:
        # Already revoked; treat as idempotent success.
        return

    await audit.safe_log(
        db=db,
        action=AuditAction.API_KEY_REVOKE,
        user_id=admin.user_id,
        org_id=record.org_id,
        resource_type="api_key",
        resource_id=record.id,
        ip_address=getattr(request.state, "client_ip", None),
        request_id=getattr(request.state, "request_id", None),
    )


# -- Webhook endpoints -------------------------------------------------------


class WebhookCreateRequest(BaseModel):
    url: HttpUrl
    events: list[str] = Field(default_factory=list, max_length=32)
    org_id: str | None = Field(None, max_length=255)


class WebhookCreateResponse(BaseModel):
    id: str
    org_id: str
    url: str
    events: list[str]
    signing_secret: str = Field(..., description="Shown once. Persist securely.")


class WebhookListItem(BaseModel):
    id: str
    org_id: str
    url: str
    events: list[str]
    is_active: bool
    created_at: datetime
    last_delivery_at: datetime | None
    last_delivery_status: int | None


def _resolve_target_org(admin: AuthenticatedUser, requested: str | None) -> str:
    if admin.org_id:
        return admin.org_id
    if not requested:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="org_id is required for global admins",
        )
    return requested


@router.post(
    "/admin/webhooks",
    response_model=WebhookCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_webhook(
    request: Request,
    payload: WebhookCreateRequest,
    admin: Annotated[AuthenticatedUser, Depends(require_scope("admin"))],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> WebhookCreateResponse:
    target_org = _resolve_target_org(admin, payload.org_id)
    signing_secret = secrets.token_urlsafe(32)
    record = WebhookEndpointRecord(
        id=str(_uuid.uuid4()),
        org_id=target_org,
        url=str(payload.url),
        signing_secret=signing_secret,
        events=payload.events,
        is_active=True,
    )
    db.add(record)
    await db.flush()
    await audit.safe_log(
        db=db,
        action=AuditAction.SETTINGS_CHANGE,
        user_id=admin.user_id,
        org_id=target_org,
        resource_type="webhook",
        resource_id=record.id,
        ip_address=getattr(request.state, "client_ip", None),
        request_id=getattr(request.state, "request_id", None),
        url=str(payload.url),
        events=payload.events,
    )
    return WebhookCreateResponse(
        id=record.id,
        org_id=record.org_id,
        url=record.url,
        events=record.events or [],
        signing_secret=signing_secret,
    )


@router.get(
    "/admin/webhooks",
    response_model=list[WebhookListItem],
)
async def list_webhooks(
    admin: Annotated[AuthenticatedUser, Depends(require_scope("admin"))],
    db: Annotated[AsyncSession, Depends(get_session)],
    org_id: str | None = None,
) -> list[WebhookListItem]:
    query = select(WebhookEndpointRecord).order_by(WebhookEndpointRecord.created_at.desc())
    if admin.org_id:
        query = query.where(WebhookEndpointRecord.org_id == admin.org_id)
    elif org_id:
        query = query.where(WebhookEndpointRecord.org_id == org_id)
    result = await db.execute(query)
    return [
        WebhookListItem(
            id=r.id,
            org_id=r.org_id,
            url=r.url,
            events=r.events or [],
            is_active=r.is_active,
            created_at=r.created_at,
            last_delivery_at=r.last_delivery_at,
            last_delivery_status=r.last_delivery_status,
        )
        for r in result.scalars().all()
    ]


@router.delete(
    "/admin/webhooks/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_webhook(
    request: Request,
    webhook_id: str,
    admin: Annotated[AuthenticatedUser, Depends(require_scope("admin"))],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    record = await db.get(WebhookEndpointRecord, webhook_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    if admin.org_id and record.org_id != admin.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    record.is_active = False
    await audit.safe_log(
        db=db,
        action=AuditAction.SETTINGS_CHANGE,
        user_id=admin.user_id,
        org_id=record.org_id,
        resource_type="webhook",
        resource_id=record.id,
        ip_address=getattr(request.state, "client_ip", None),
        request_id=getattr(request.state, "request_id", None),
        deactivated=True,
    )
