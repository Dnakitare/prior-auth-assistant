"""Repository layer for database operations."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.db_models import AppealRecord, PayerRecord, PayerRuleRecord
from src.core.models import AppealLetter, DenialReason


class AppealRepository:
    """Repository for appeal records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, appeal: AppealLetter) -> AppealRecord:
        """Save an appeal to the database."""
        record = AppealRecord(
            id=appeal.id,
            patient_name=None,  # Set from context if available
            member_id=appeal.denial_extraction.member_id,
            payer_name=appeal.denial_extraction.payer_name,
            denial_reason=appeal.denial_extraction.denial_reason,
            denial_reason_text=appeal.denial_extraction.denial_reason_text,
            denial_date=appeal.denial_extraction.denial_date,
            claim_number=appeal.denial_extraction.claim_number,
            procedure_codes=appeal.denial_extraction.procedure_codes,
            diagnosis_codes=appeal.denial_extraction.diagnosis_codes,
            appeal_letter=appeal.letter_content,
            required_documents=appeal.required_attachments,
            confidence_score=appeal.confidence_score,
            denial_text=appeal.denial_extraction.raw_text,
            status="generated",
        )

        self.session.add(record)
        await self.session.flush()
        return record

    async def get_by_id(self, appeal_id: str) -> AppealRecord | None:
        """Retrieve an appeal by ID."""
        result = await self.session.execute(
            select(AppealRecord).where(AppealRecord.id == appeal_id)
        )
        return result.scalar_one_or_none()

    async def list_recent(self, limit: int = 20) -> list[AppealRecord]:
        """List recent appeals."""
        result = await self.session.execute(
            select(AppealRecord)
            .order_by(AppealRecord.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_status(self, appeal_id: str, status: str) -> AppealRecord | None:
        """Update appeal status."""
        record = await self.get_by_id(appeal_id)
        if record:
            record.status = status
            await self.session.flush()
        return record


class PayerRepository:
    """Repository for payer records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_name(self, name: str) -> PayerRecord | None:
        """Find payer by name or alias."""
        # First try exact match
        result = await self.session.execute(
            select(PayerRecord).where(PayerRecord.name.ilike(f"%{name}%"))
        )
        payer = result.scalar_one_or_none()
        if payer:
            return payer

        # TODO: Search aliases with JSON contains
        return None

    async def get_by_id(self, payer_id: str) -> PayerRecord | None:
        """Get payer by ID."""
        result = await self.session.execute(
            select(PayerRecord).where(PayerRecord.id == payer_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[PayerRecord]:
        """List all payers."""
        result = await self.session.execute(
            select(PayerRecord).order_by(PayerRecord.name)
        )
        return list(result.scalars().all())

    async def create(self, payer: PayerRecord) -> PayerRecord:
        """Create a new payer record."""
        self.session.add(payer)
        await self.session.flush()
        return payer

    async def increment_appeal_count(
        self, payer_id: str, successful: bool = False
    ) -> None:
        """Increment appeal statistics for a payer."""
        payer = await self.get_by_id(payer_id)
        if payer:
            payer.total_appeals += 1
            if successful:
                payer.successful_appeals += 1
            await self.session.flush()


class PayerRuleRepository:
    """Repository for payer-specific rules."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_matching_rules(
        self,
        payer_id: str,
        procedure_code: str | None = None,
        diagnosis_code: str | None = None,
        denial_reason: DenialReason | None = None,
    ) -> list[PayerRuleRecord]:
        """Find rules matching the given criteria."""
        query = select(PayerRuleRecord).where(PayerRuleRecord.payer_id == payer_id)

        # Add optional filters
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
        """Create a new payer rule."""
        self.session.add(rule)
        await self.session.flush()
        return rule

    async def increment_usage(self, rule_id: str, successful: bool = False) -> None:
        """Track rule usage."""
        result = await self.session.execute(
            select(PayerRuleRecord).where(PayerRuleRecord.id == rule_id)
        )
        rule = result.scalar_one_or_none()
        if rule:
            rule.times_used += 1
            if successful:
                rule.success_count += 1
            await self.session.flush()


def generate_payer_seed_data() -> list[dict]:
    """Generate seed data for common payers."""
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
        {
            "id": str(uuid.uuid4()),
            "name": "Aetna",
            "aliases": ["Aetna Health", "CVS Aetna"],
            "appeals_phone": "1-800-555-0101",
            "appeal_deadline_days": 180,
            "medical_necessity_requirements": {
                "required_docs": [
                    "Physician letter of medical necessity",
                    "Treatment history documentation",
                    "Current clinical status",
                ],
                "tips": [
                    "Reference Aetna Clinical Policy Bulletins (CPBs)",
                    "Include specific clinical criteria met",
                ],
            },
        },
        {
            "id": str(uuid.uuid4()),
            "name": "UnitedHealthcare",
            "aliases": ["United", "UHC", "United Health"],
            "appeals_phone": "1-800-555-0102",
            "appeal_deadline_days": 180,
            "medical_necessity_requirements": {
                "required_docs": [
                    "Letter of medical necessity",
                    "Clinical documentation",
                    "Evidence of medical appropriateness",
                ],
                "tips": [
                    "Reference UHC Medical Policies",
                    "Include InterQual or MCG criteria if applicable",
                ],
            },
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Cigna",
            "aliases": ["Cigna Healthcare", "Cigna Health"],
            "appeals_phone": "1-800-555-0103",
            "appeal_deadline_days": 180,
            "medical_necessity_requirements": {
                "required_docs": [
                    "Attending physician statement",
                    "Medical records",
                    "Test results",
                ],
                "tips": [
                    "Reference Cigna Coverage Policies",
                    "Include specific diagnosis and treatment rationale",
                ],
            },
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Humana",
            "aliases": ["Humana Health", "Humana Insurance"],
            "appeals_phone": "1-800-555-0104",
            "appeal_deadline_days": 180,
            "medical_necessity_requirements": {
                "required_docs": [
                    "Physician certification",
                    "Clinical documentation",
                    "Treatment plan",
                ],
                "tips": [
                    "Reference Humana Clinical Criteria",
                    "Include detailed treatment justification",
                ],
            },
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Kaiser Permanente",
            "aliases": ["Kaiser", "KP"],
            "appeals_phone": "1-800-555-0105",
            "appeal_deadline_days": 180,
            "medical_necessity_requirements": {
                "required_docs": [
                    "Provider recommendation",
                    "Medical records",
                    "Clinical justification",
                ],
                "tips": [
                    "Appeals handled internally",
                    "Request expedited review for urgent cases",
                ],
            },
        },
    ]
