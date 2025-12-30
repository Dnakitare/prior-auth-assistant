"""SQLAlchemy database models."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.core.models import DenialReason


class AppealRecord(Base):
    """Persisted appeal record."""

    __tablename__ = "appeals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Patient info
    patient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    member_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Denial info
    payer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payer_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("payers.id"), nullable=True
    )
    denial_reason: Mapped[str] = mapped_column(
        Enum(DenialReason), default=DenialReason.OTHER, nullable=False
    )
    denial_reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    denial_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    claim_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Procedure info
    procedure_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    diagnosis_codes: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Generated appeal
    appeal_letter: Mapped[str] = mapped_column(Text, nullable=False)
    required_documents: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Raw data
    denial_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(50), default="generated", nullable=False
    )  # generated, submitted, approved, denied

    # Relationships
    payer: Mapped["PayerRecord | None"] = relationship(back_populates="appeals")


class PayerRecord(Base):
    """Insurance payer information and rules."""

    __tablename__ = "payers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)  # Alternative names

    # Contact info
    appeals_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    appeals_fax: Mapped[str | None] = mapped_column(String(20), nullable=True)
    appeals_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    appeals_portal_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Timing
    appeal_deadline_days: Mapped[int] = mapped_column(default=180)
    expedited_review_available: Mapped[bool] = mapped_column(default=True)

    # Rules and requirements (JSON for flexibility)
    medical_necessity_requirements: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )
    step_therapy_requirements: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )
    documentation_requirements: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )

    # Statistics (updated over time)
    total_appeals: Mapped[int] = mapped_column(default=0)
    successful_appeals: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    appeals: Mapped[list["AppealRecord"]] = relationship(back_populates="payer")
    rules: Mapped[list["PayerRuleRecord"]] = relationship(back_populates="payer")


class PayerRuleRecord(Base):
    """Specific payer rules for procedures/diagnoses."""

    __tablename__ = "payer_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    payer_id: Mapped[str] = mapped_column(String(36), ForeignKey("payers.id"))

    # Rule applicability
    procedure_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    diagnosis_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    denial_reason: Mapped[str | None] = mapped_column(
        Enum(DenialReason), nullable=True
    )

    # Rule content
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_documentation: Mapped[list[str]] = mapped_column(JSON, default=list)
    appeal_tips: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Effectiveness tracking
    times_used: Mapped[int] = mapped_column(default=0)
    success_count: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Relationships
    payer: Mapped["PayerRecord"] = relationship(back_populates="rules")
