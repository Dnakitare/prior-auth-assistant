"""Appeal generation endpoints. Authenticated + tenant-scoped."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import AuditAction, audit
from src.core.config import settings
from src.core.database import get_session
from src.core.models import AppealLetter, DenialExtraction, DenialReason, PatientContext
from src.core.quota import QuotaExceeded, check_and_reserve
from src.core.repositories import AppealRepository, decode_diagnosis_codes
from src.core.security import AuthenticatedUser, get_current_user
from src.core.upload_validation import UnsupportedFileType, detect_type, safe_filename
from src.core.services import AppealGenerationService
from src.core.webhooks import emit_appeal_event
from src.integrations.llm import (
    LLMBudgetExceeded,
    LLMError,
    LLMInputTooLarge,
    LLMRateLimitError,
    get_llm_client,
)
from src.integrations.ocr import OCRError, get_ocr_provider

router = APIRouter()
logger = structlog.get_logger()


class TextAppealRequest(BaseModel):
    denial_text: str = Field(..., min_length=50, max_length=100000)
    patient_name: str | None = Field(None, max_length=200)
    procedure_code: str | None = Field(None, max_length=20, pattern=r"^[0-9A-Za-z]+$")
    procedure_description: str | None = Field(None, max_length=500)
    diagnosis_codes: list[str] | None = Field(None, max_length=20)
    clinical_notes: str | None = Field(None, max_length=10000)
    prior_treatments: list[str] | None = None
    treating_physician: str | None = Field(None, max_length=200)

    @field_validator("diagnosis_codes", mode="before")
    @classmethod
    def _diag(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            return [c.strip() for c in v.split(",") if c.strip()]
        return v

    @field_validator("prior_treatments", mode="before")
    @classmethod
    def _pt(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            return [t.strip() for t in v.split(",") if t.strip()]
        return v


class AppealResponse(BaseModel):
    appeal_id: str
    appeal_letter: str
    denial_info: DenialExtraction
    required_documents: list[str]
    confidence_score: float
    created_at: datetime
    warnings: list[str] = []


class ErrorResponse(BaseModel):
    detail: str
    error_code: str | None = None


def get_appeal_service() -> AppealGenerationService:
    return AppealGenerationService(
        ocr_provider=get_ocr_provider(),
        llm_client=get_llm_client(),
    )


def _audit_context(request: Request) -> dict:
    return {
        "ip_address": getattr(request.state, "client_ip", None),
        "user_agent": request.headers.get("User-Agent"),
        "request_id": getattr(request.state, "request_id", None),
    }


def _build_warnings(appeal: AppealLetter) -> list[str]:
    warnings: list[str] = []
    if appeal.confidence_score < 0.5:
        warnings.append("Low confidence extraction. Please verify extracted information.")
    if not appeal.denial_extraction.payer_name:
        warnings.append("Could not identify payer. Please verify and add payer name.")
    deadline = appeal.denial_extraction.appeal_deadline
    if deadline and deadline < datetime.now():
        warnings.append("Appeal deadline may have passed. Verify deadline with payer.")
    return warnings


def _to_response(
    appeal: AppealLetter, warnings: list[str] | None = None
) -> AppealResponse:
    return AppealResponse(
        appeal_id=appeal.id,
        appeal_letter=appeal.letter_content,
        denial_info=appeal.denial_extraction,
        required_documents=appeal.required_attachments,
        confidence_score=appeal.confidence_score,
        created_at=datetime.now(timezone.utc),
        warnings=warnings or _build_warnings(appeal),
    )


async def _reserve_llm_budget(db: AsyncSession, org_id: str) -> None:
    """Reserve upper-bound tokens for this appeal against the org's daily budget."""
    estimate = settings.llm_max_tokens_extraction + settings.llm_max_tokens_generation
    try:
        await check_and_reserve(db, org_id=org_id, tokens=estimate)
    except QuotaExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Organization LLM token budget exceeded ({e.used}/{e.budget}). Retry after daily reset.",
            headers={"Retry-After": "3600"},
        )


def _require_org(user: AuthenticatedUser) -> str:
    if not user.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated principal has no organization; cannot access PHI.",
        )
    return user.org_id


@router.post(
    "/appeals/upload",
    response_model=AppealResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def generate_appeal_from_document(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    denial_letter: UploadFile = File(...),
    patient_name: str | None = Form(None),
    procedure_code: str | None = Form(None),
    procedure_description: str | None = Form(None),
    diagnosis_codes: str | None = Form(None),
    clinical_notes: str | None = Form(None),
    prior_treatments: str | None = Form(None),
    treating_physician: str | None = Form(None),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)] = None,
) -> AppealResponse:
    org_id = _require_org(user)
    ctx = _audit_context(request)
    log = logger.bind(user_id=user.user_id, org_id=org_id, **ctx)

    # Read with a hard byte ceiling so a malicious client cannot force us to
    # buffer arbitrary amounts before we reject.
    max_size = settings.max_upload_size_mb * 1024 * 1024
    content = await denial_letter.read(max_size + 1)
    if len(content) > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.max_upload_size_mb}MB",
        )

    # Magic-byte MIME detection. Client-declared Content-Type is not trusted.
    try:
        detected = detect_type(content)
    except UnsupportedFileType as e:
        log.warning(
            "rejected_upload_bad_magic",
            filename=safe_filename(denial_letter.filename),
            declared=denial_letter.content_type,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    log.info(
        "processing_denial_document",
        filename=safe_filename(denial_letter.filename),
        size=len(content),
        mime=detected.mime,
    )

    patient_context = _build_patient_context(
        patient_name=patient_name,
        procedure_code=procedure_code,
        procedure_description=procedure_description,
        diagnosis_codes=[c.strip() for c in diagnosis_codes.split(",")] if diagnosis_codes else [],
        clinical_notes=clinical_notes,
        prior_treatments=[t.strip() for t in prior_treatments.split(",")] if prior_treatments else [],
        treating_physician=treating_physician,
    )

    await _reserve_llm_budget(db, org_id)
    service = get_appeal_service()
    try:
        appeal = await service.process_denial(content, patient_context)
    except OCRError as e:
        log.error("ocr_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not extract text from document.",
        )
    except LLMInputTooLarge as e:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(e)
        )
    except LLMRateLimitError as e:
        log.warning("llm_rate_limit", retry_after=e.retry_after_seconds)
        headers = (
            {"Retry-After": str(e.retry_after_seconds)} if e.retry_after_seconds else {}
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="The AI service is rate-limiting requests right now. Wait a moment and try again.",
            headers=headers,
        )
    except LLMBudgetExceeded as e:
        log.warning("llm_budget_exceeded", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
            headers={"X-Error-Code": "BUDGET_EXHAUSTED"},
        )
    except LLMError as e:
        log.error("llm_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service temporarily unavailable. Please try again later.",
        )

    await _persist_and_audit(
        db=db,
        appeal=appeal,
        user=user,
        org_id=org_id,
        ctx=ctx,
        patient_name=patient_name,
        diagnosis_flag=bool(diagnosis_codes),
        idempotency_key=idempotency_key,
    )

    return _to_response(appeal)


@router.post(
    "/appeals/text",
    response_model=AppealResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def generate_appeal_from_text(
    request: Request,
    appeal_request: TextAppealRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)] = None,
) -> AppealResponse:
    org_id = _require_org(user)
    ctx = _audit_context(request)
    log = logger.bind(user_id=user.user_id, org_id=org_id, **ctx)

    patient_context = _build_patient_context(
        patient_name=appeal_request.patient_name,
        procedure_code=appeal_request.procedure_code,
        procedure_description=appeal_request.procedure_description,
        diagnosis_codes=appeal_request.diagnosis_codes or [],
        clinical_notes=appeal_request.clinical_notes,
        prior_treatments=appeal_request.prior_treatments or [],
        treating_physician=appeal_request.treating_physician,
    )

    await _reserve_llm_budget(db, org_id)
    service = get_appeal_service()
    try:
        appeal = await service.process_denial_from_text(
            appeal_request.denial_text, patient_context
        )
    except LLMInputTooLarge as e:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(e)
        )
    except LLMRateLimitError as e:
        log.warning("llm_rate_limit", retry_after=e.retry_after_seconds)
        headers = (
            {"Retry-After": str(e.retry_after_seconds)} if e.retry_after_seconds else {}
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="The AI service is rate-limiting requests right now. Wait a moment and try again.",
            headers=headers,
        )
    except LLMBudgetExceeded as e:
        log.warning("llm_budget_exceeded", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
            headers={"X-Error-Code": "BUDGET_EXHAUSTED"},
        )
    except LLMError as e:
        log.error("llm_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service temporarily unavailable. Please try again later.",
        )

    await _persist_and_audit(
        db=db,
        appeal=appeal,
        user=user,
        org_id=org_id,
        ctx=ctx,
        patient_name=appeal_request.patient_name,
        diagnosis_flag=bool(appeal_request.diagnosis_codes),
        idempotency_key=idempotency_key,
    )

    return _to_response(appeal)


_VALID_STATUSES = {"generated", "submitted", "approved", "denied", "withdrawn"}


class AppealStatusUpdate(BaseModel):
    status: str = Field(..., min_length=1, max_length=32)


@router.patch(
    "/appeals/{appeal_id}/status",
    response_model=AppealResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 400: {"model": ErrorResponse}},
)
async def update_appeal_status(
    request: Request,
    appeal_id: str,
    payload: AppealStatusUpdate,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> AppealResponse:
    """Transition an appeal's status. Scoped to caller's org. Emits
    appeal.status_changed webhook."""
    org_id = _require_org(user)
    ctx = _audit_context(request)
    log = logger.bind(user_id=user.user_id, org_id=org_id, appeal_id=appeal_id)

    if payload.status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status must be one of: {sorted(_VALID_STATUSES)}",
        )

    repo = AppealRepository(db)
    record = await repo.get_by_id(appeal_id, org_id=org_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Appeal not found"
        )
    previous = record.status
    if previous == payload.status:
        # Idempotent; no webhook for a no-op transition.
        log.info("appeal_status_unchanged", status=payload.status)
    else:
        record.status = payload.status
        await db.flush()
        await emit_appeal_event(
            db,
            org_id=org_id,
            event_type="appeal.status_changed",
            payload={
                "appeal_id": record.id,
                "previous_status": previous,
                "new_status": record.status,
                "changed_by": user.user_id,
                "changed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await audit.safe_log(
            db=db,
            action=AuditAction.APPEAL_UPDATE,
            user_id=user.user_id,
            org_id=org_id,
            resource_type="appeal",
            resource_id=appeal_id,
            ip_address=ctx.get("ip_address"),
            request_id=ctx.get("request_id"),
            contains_phi=False,
            previous_status=previous,
            new_status=payload.status,
        )

    denial_info = DenialExtraction(
        payer_name=record.payer_name,
        denial_date=record.denial_date,
        denial_reason=(
            record.denial_reason
            if isinstance(record.denial_reason, DenialReason)
            else DenialReason(record.denial_reason)
        ),
        denial_reason_text=record.denial_reason_text,
        procedure_codes=record.procedure_codes or [],
        diagnosis_codes=decode_diagnosis_codes(record),
        member_id=record.member_id,
        claim_number=record.claim_number,
        raw_text=record.denial_text,
    )
    return AppealResponse(
        appeal_id=record.id,
        appeal_letter=record.appeal_letter,
        denial_info=denial_info,
        required_documents=record.required_documents or [],
        confidence_score=record.confidence_score,
        created_at=(
            record.created_at.replace(tzinfo=timezone.utc)
            if record.created_at and record.created_at.tzinfo is None
            else (record.created_at or datetime.now(timezone.utc))
        ),
        warnings=[],
    )


@router.get(
    "/appeals/{appeal_id}",
    response_model=AppealResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_appeal(
    request: Request,
    appeal_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> AppealResponse:
    org_id = _require_org(user)
    ctx = _audit_context(request)
    log = logger.bind(user_id=user.user_id, org_id=org_id, appeal_id=appeal_id)

    repo = AppealRepository(db)
    record = await repo.get_by_id(appeal_id, org_id=org_id)

    if not record:
        log.info("appeal_not_found_or_forbidden")
        # Audit the failed access so enumeration attempts leave a trail.
        await audit.log(
            db=db,
            action=AuditAction.APPEAL_READ,
            user_id=user.user_id,
            org_id=org_id,
            resource_type="appeal",
            resource_id=appeal_id,
            ip_address=ctx.get("ip_address"),
            request_id=ctx.get("request_id"),
            success=False,
            error_message="not found or cross-tenant",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appeal not found or you don't have permission to access it",
        )

    await audit.safe_log(
        db=db,
        action=AuditAction.APPEAL_READ,
        user_id=user.user_id,
        org_id=org_id,
        resource_type="appeal",
        resource_id=appeal_id,
        ip_address=ctx.get("ip_address"),
        request_id=ctx.get("request_id"),
        contains_phi=True,
    )

    denial_info = DenialExtraction(
        payer_name=record.payer_name,
        denial_date=record.denial_date,
        denial_reason=(
            record.denial_reason
            if isinstance(record.denial_reason, DenialReason)
            else DenialReason(record.denial_reason)
        ),
        denial_reason_text=record.denial_reason_text,
        procedure_codes=record.procedure_codes or [],
        diagnosis_codes=decode_diagnosis_codes(record),
        member_id=record.member_id,
        claim_number=record.claim_number,
        raw_text=record.denial_text,
    )

    return AppealResponse(
        appeal_id=record.id,
        appeal_letter=record.appeal_letter,
        denial_info=denial_info,
        required_documents=record.required_documents or [],
        confidence_score=record.confidence_score,
        created_at=(
            record.created_at.replace(tzinfo=timezone.utc)
            if record.created_at and record.created_at.tzinfo is None
            else (record.created_at or datetime.now(timezone.utc))
        ),
        warnings=[],
    )


# --- helpers ----------------------------------------------------------------


def _build_patient_context(
    *,
    patient_name: str | None,
    procedure_code: str | None,
    procedure_description: str | None,
    diagnosis_codes: list[str],
    clinical_notes: str | None,
    prior_treatments: list[str],
    treating_physician: str | None,
) -> PatientContext | None:
    if not (patient_name or procedure_code):
        return None
    return PatientContext(
        patient_name=patient_name or "Unknown",
        procedure_code=procedure_code or "Unknown",
        procedure_description=procedure_description,
        diagnosis_codes=diagnosis_codes,
        clinical_notes=clinical_notes,
        prior_treatments=prior_treatments,
        treating_physician=treating_physician,
    )


async def _persist_and_audit(
    *,
    db: AsyncSession,
    appeal: AppealLetter,
    user: AuthenticatedUser,
    org_id: str,
    ctx: dict,
    patient_name: str | None,
    diagnosis_flag: bool,
    idempotency_key: str | None,
) -> None:
    """Persist the appeal and write the audit entry. Both failures are hard errors.

    Previously persistence failures were swallowed and the caller still got a
    200 with an un-saved appeal — which looks like success but leaves the data
    only in logs. We now return 500 so clients retry with the same
    Idempotency-Key and get deduplicated.
    """
    log = logger.bind(user_id=user.user_id, org_id=org_id, appeal_id=appeal.id, **ctx)
    repo = AppealRepository(db)
    try:
        await repo.save(
            appeal,
            created_by=user.user_id,
            org_id=org_id,
            patient_name=patient_name,
            idempotency_key=idempotency_key,
        )
    except Exception:
        log.exception("appeal_persistence_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist appeal. Retry with the same Idempotency-Key.",
        )

    await audit.safe_log(
        db=db,
        action=AuditAction.APPEAL_CREATE,
        user_id=user.user_id,
        org_id=org_id,
        resource_type="appeal",
        resource_id=appeal.id,
        ip_address=ctx.get("ip_address"),
        request_id=ctx.get("request_id"),
        contains_phi=True,
        phi_types=[
            *(["patient_name"] if patient_name else []),
            *(["diagnosis_codes"] if diagnosis_flag else []),
            *(["member_id"] if appeal.denial_extraction.member_id else []),
        ],
    )
    log.info("appeal_saved")
