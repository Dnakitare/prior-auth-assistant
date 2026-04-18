"""SQLAlchemy database models.

PHI fields (patient_name, member_id, denial_text, appeal_letter, diagnosis_codes)
are stored via EncryptedText / EncryptedString type decorators. Non-PHI
identifiers (org_id, created_by, payer_name) remain plaintext for indexing/filtering.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.core.encryption import EncryptedString, EncryptedText
from src.core.models import DenialReason


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AppealRecord(Base):
    """Persisted appeal record. PHI columns are encrypted at rest."""

    __tablename__ = "appeals"
    __table_args__ = (
        UniqueConstraint("org_id", "idempotency_key", name="uq_appeals_org_idem"),
        Index("ix_appeals_org_created", "org_id", "created_at"),
        Index("ix_appeals_created_by", "created_by"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # Tenant / ownership (NOT encrypted; needed for query filtering)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    org_id: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Patient info (encrypted)
    patient_name: Mapped[str | None] = mapped_column(EncryptedText(), nullable=True)
    member_id: Mapped[str | None] = mapped_column(EncryptedText(), nullable=True)

    # Payer info (plaintext — operational metadata, not PHI)
    payer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payer_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("payers.id"), nullable=True, index=True
    )
    denial_reason: Mapped[str] = mapped_column(
        Enum(DenialReason), default=DenialReason.OTHER, nullable=False
    )
    denial_reason_text: Mapped[str | None] = mapped_column(EncryptedText(), nullable=True)
    denial_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_number: Mapped[str | None] = mapped_column(EncryptedText(), nullable=True)

    # Procedure / diagnosis codes — encrypted as JSON blob string.
    # (Codes alone aren't PHI, but combined with member_id and dates they can be.)
    procedure_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    diagnosis_codes_encrypted: Mapped[str | None] = mapped_column(EncryptedText(), nullable=True)

    # Generated appeal (encrypted — contains PHI)
    appeal_letter: Mapped[str] = mapped_column(EncryptedText(), nullable=False)
    required_documents: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Raw denial text (encrypted — contains PHI)
    denial_text: Mapped[str | None] = mapped_column(EncryptedText(), nullable=True)

    # Status tracking
    status: Mapped[str] = mapped_column(String(50), default="generated", nullable=False, index=True)

    # Relationships
    payer: Mapped["PayerRecord | None"] = relationship(back_populates="appeals")


class PayerRecord(Base):
    """Insurance payer information and rules. No PHI."""

    __tablename__ = "payers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)

    appeals_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    appeals_fax: Mapped[str | None] = mapped_column(String(20), nullable=True)
    appeals_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    appeals_portal_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    appeal_deadline_days: Mapped[int] = mapped_column(Integer, default=180)
    expedited_review_available: Mapped[bool] = mapped_column(Boolean, default=True)

    medical_necessity_requirements: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    step_therapy_requirements: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    documentation_requirements: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    total_appeals: Mapped[int] = mapped_column(Integer, default=0)
    successful_appeals: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    appeals: Mapped[list["AppealRecord"]] = relationship(back_populates="payer")
    rules: Mapped[list["PayerRuleRecord"]] = relationship(back_populates="payer")


class PayerRuleRecord(Base):
    """Specific payer rules for procedures/diagnoses. No PHI."""

    __tablename__ = "payer_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    payer_id: Mapped[str] = mapped_column(String(36), ForeignKey("payers.id"), index=True)

    procedure_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    diagnosis_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    denial_reason: Mapped[str | None] = mapped_column(Enum(DenialReason), nullable=True)

    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_documentation: Mapped[list[str]] = mapped_column(JSON, default=list)
    appeal_tips: Mapped[list[str]] = mapped_column(JSON, default=list)

    times_used: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    payer: Mapped["PayerRecord"] = relationship(back_populates="rules")


class ApiKeyRecord(Base):
    """Hashed API key entries. Never stores the plaintext key."""

    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_org_active", "org_id", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    org_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class UserSessionRecord(Base):
    """Issued JWT sessions. Token revocation via revoked_at."""

    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_sessions_user", "user_id"),
        Index("ix_sessions_expires", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    org_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLogRecord(Base):
    """Append-only tamper-evident audit log.

    Each row's row_hmac is HMAC-SHA256 over (prev_hmac || serialized_event),
    forming a hash chain. Breaking the chain proves tampering.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_user_time", "user_id", "timestamp"),
        Index("ix_audit_resource", "resource_type", "resource_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    org_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    contains_phi: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    phi_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    prev_hmac: Mapped[str | None] = mapped_column(String(64), nullable=True)
    row_hmac: Mapped[str] = mapped_column(String(64), nullable=False)
