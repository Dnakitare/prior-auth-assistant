"""Domain models for Prior Authorization."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class DenialReason(str, Enum):
    """Common prior authorization denial reasons."""

    MEDICAL_NECESSITY = "medical_necessity"
    NOT_COVERED = "not_covered"
    OUT_OF_NETWORK = "out_of_network"
    MISSING_INFO = "missing_information"
    EXPERIMENTAL = "experimental_treatment"
    STEP_THERAPY = "step_therapy_required"
    QUANTITY_LIMIT = "quantity_limit"
    PRIOR_AUTH_REQUIRED = "prior_auth_required"
    OTHER = "other"


class DenialExtraction(BaseModel):
    """Extracted information from a denial letter."""

    payer_name: str | None = None
    denial_date: datetime | None = None
    denial_reason: DenialReason = DenialReason.OTHER
    denial_reason_text: str | None = None
    procedure_codes: list[str] = []
    diagnosis_codes: list[str] = []
    member_id: str | None = None
    claim_number: str | None = None
    appeal_deadline: datetime | None = None
    raw_text: str = ""


class AppealLetter(BaseModel):
    """Generated appeal letter with metadata."""

    id: str
    denial_extraction: DenialExtraction
    letter_content: str
    required_attachments: list[str]
    generated_at: datetime
    confidence_score: float


class PatientContext(BaseModel):
    """Additional patient context for appeal generation."""

    patient_name: str
    date_of_birth: str | None = None
    member_id: str | None = None
    procedure_code: str
    procedure_description: str | None = None
    diagnosis_codes: list[str] = []
    treating_physician: str | None = None
    clinical_notes: str | None = None
    prior_treatments: list[str] = []
