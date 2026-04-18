"""Repository layer for database operations.

All PHI-touching queries require explicit user_id + org_id arguments. The
session-level ORM filters on org_id so a caller cannot accidentally read
another tenant's data.
"""

from __future__ import annotations

import hmac
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.db_models import (
    ApiKeyRecord,
    AppealRecord,
    PayerRecord,
    PayerRuleRecord,
    UserSessionRecord,
)
from src.core.models import AppealLetter, DenialReason
from src.core.security import hash_api_key


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AppealRepository:
    """Appeal records — scoped to (org_id, created_by)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(
        self,
        appeal: AppealLetter,
        *,
        created_by: str,
        org_id: str,
        patient_name: str | None = None,
        idempotency_key: str | None = None,
    ) -> AppealRecord:
        """Persist a new appeal. Caller is responsible for commit via session context."""
        # Idempotency: if a row already exists for (org_id, idempotency_key), return it.
        if idempotency_key:
            existing = await self._get_by_idempotency(org_id, idempotency_key)
            if existing is not None:
                return existing

        record = AppealRecord(
            id=appeal.id,
            created_by=created_by,
            org_id=org_id,
            idempotency_key=idempotency_key,
            patient_name=patient_name,
            member_id=appeal.denial_extraction.member_id,
            payer_name=appeal.denial_extraction.payer_name,
            denial_reason=appeal.denial_extraction.denial_reason,
            denial_reason_text=appeal.denial_extraction.denial_reason_text,
            denial_date=appeal.denial_extraction.denial_date,
            claim_number=appeal.denial_extraction.claim_number,
            procedure_codes=appeal.denial_extraction.procedure_codes,
            diagnosis_codes_encrypted=json.dumps(appeal.denial_extraction.diagnosis_codes),
            appeal_letter=appeal.letter_content,
            required_documents=appeal.required_attachments,
            confidence_score=appeal.confidence_score,
            denial_text=appeal.denial_extraction.raw_text,
            status="generated",
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def _get_by_idempotency(self, org_id: str, key: str) -> AppealRecord | None:
        result = await self.session.execute(
            select(AppealRecord).where(
                and_(AppealRecord.org_id == org_id, AppealRecord.idempotency_key == key)
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(
        self, appeal_id: str, *, org_id: str
    ) -> AppealRecord | None:
        """Retrieve by id, filtered by caller's org. Cross-tenant reads return None."""
        result = await self.session.execute(
            select(AppealRecord).where(
                and_(AppealRecord.id == appeal_id, AppealRecord.org_id == org_id)
            )
        )
        return result.scalar_one_or_none()

    async def list_recent(
        self, *, org_id: str, limit: int = 20
    ) -> list[AppealRecord]:
        result = await self.session.execute(
            select(AppealRecord)
            .where(AppealRecord.org_id == org_id)
            .order_by(AppealRecord.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_status(
        self, appeal_id: str, status: str, *, org_id: str
    ) -> AppealRecord | None:
        record = await self.get_by_id(appeal_id, org_id=org_id)
        if record:
            record.status = status
            await self.session.flush()
        return record


def decode_diagnosis_codes(record: AppealRecord) -> list[str]:
    """Decode the encrypted-JSON diagnosis_codes column back to a list."""
    if not record.diagnosis_codes_encrypted:
        return []
    try:
        value = json.loads(record.diagnosis_codes_encrypted)
        return value if isinstance(value, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


class ApiKeyRepository:
    """Persisted API keys (hashed)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        plaintext: str,
        org_id: str,
        name: str,
        scopes: list[str],
        expires_at: datetime | None = None,
    ) -> ApiKeyRecord:
        record = ApiKeyRecord(
            id=str(uuid.uuid4()),
            key_hash=hash_api_key(plaintext),
            org_id=org_id,
            name=name,
            scopes=scopes,
            expires_at=expires_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_by_hash(self, key_hash: str) -> ApiKeyRecord | None:
        result = await self.session.execute(
            select(ApiKeyRecord).where(ApiKeyRecord.key_hash == key_hash)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        # Defence-in-depth constant-time compare.
        return record if hmac.compare_digest(record.key_hash, key_hash) else None

    async def revoke(self, key_id: str) -> bool:
        record = await self.session.get(ApiKeyRecord, key_id)
        if record is None or record.revoked_at is not None:
            return False
        record.revoked_at = _utcnow()
        record.is_active = False
        await self.session.flush()
        return True


class SessionRepository:
    """JWT session tracking. Revocation by updating revoked_at."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, session_id: str) -> UserSessionRecord | None:
        return await self.session.get(UserSessionRecord, session_id)

    async def list_active_for_user(self, user_id: str) -> list[UserSessionRecord]:
        now = _utcnow()
        result = await self.session.execute(
            select(UserSessionRecord).where(
                and_(
                    UserSessionRecord.user_id == user_id,
                    UserSessionRecord.revoked_at.is_(None),
                    UserSessionRecord.expires_at > now,
                )
            )
        )
        return list(result.scalars().all())

    async def revoke_all_for_user(self, user_id: str) -> int:
        now = _utcnow()
        sessions = await self.list_active_for_user(user_id)
        for s in sessions:
            s.revoked_at = now
        await self.session.flush()
        return len(sessions)


class PayerRepository:
    """Payer records (non-PHI)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_name(self, name: str) -> PayerRecord | None:
        result = await self.session.execute(
            select(PayerRecord).where(PayerRecord.name.ilike(f"%{name}%"))
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, payer_id: str) -> PayerRecord | None:
        return await self.session.get(PayerRecord, payer_id)

    async def list_all(self) -> list[PayerRecord]:
        result = await self.session.execute(
            select(PayerRecord).order_by(PayerRecord.name)
        )
        return list(result.scalars().all())

    async def create(self, payer: PayerRecord) -> PayerRecord:
        self.session.add(payer)
        await self.session.flush()
        return payer

    async def increment_appeal_count(self, payer_id: str, successful: bool = False) -> None:
        payer = await self.get_by_id(payer_id)
        if payer:
            payer.total_appeals += 1
            if successful:
                payer.successful_appeals += 1
            await self.session.flush()


class PayerRuleRepository:
    """Payer-specific rules (non-PHI)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_matching_rules(
        self,
        payer_id: str,
        procedure_code: str | None = None,
        diagnosis_code: str | None = None,
        denial_reason: DenialReason | None = None,
    ) -> list[PayerRuleRecord]:
        query = select(PayerRuleRecord).where(PayerRuleRecord.payer_id == payer_id)
        if procedure_code:
            query = query.where(
                (PayerRuleRecord.procedure_code == procedure_code)
                | (PayerRuleRecord.procedure_code.is_(None))
            )
        if diagnosis_code:
            query = query.where(
                (PayerRuleRecord.diagnosis_code == diagnosis_code)
                | (PayerRuleRecord.diagnosis_code.is_(None))
            )
        if denial_reason:
            query = query.where(
                (PayerRuleRecord.denial_reason == denial_reason)
                | (PayerRuleRecord.denial_reason.is_(None))
            )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create(self, rule: PayerRuleRecord) -> PayerRuleRecord:
        self.session.add(rule)
        await self.session.flush()
        return rule


def generate_payer_seed_data() -> list[dict]:
    """Seed data for common payers. Unchanged from initial schema."""
    return [
        {
            "id": str(uuid.uuid4()),
            "name": "Blue Cross Blue Shield",
            "aliases": ["BCBS", "Blue Cross", "Blue Shield", "Anthem BCBS"],
            "appeals_phone": "1-800-555-0100",
            "appeal_deadline_days": 180,
            "medical_necessity_requirements": {
                "required_docs": [
                    "Letter of medical necessity from treating physician",
                    "Clinical notes from past 12 months",
                    "Lab results and imaging reports",
                    "Documentation of failed conservative treatments",
                ],
                "tips": [
                    "Reference BCBS clinical policy bulletins",
                    "Include peer-reviewed literature",
                    "Document functional impairment",
                ],
            },
        },
    ]
