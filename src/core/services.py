"""Core services for appeal generation pipeline."""

import uuid
from datetime import datetime

import structlog

from src.core.models import AppealLetter, DenialExtraction, PatientContext
from src.integrations.llm import LLMClient
from src.integrations.ocr import OCRProvider

logger = structlog.get_logger()


class AppealGenerationService:
    """Orchestrates the denial → extraction → appeal pipeline."""

    def __init__(self, ocr_provider: OCRProvider, llm_client: LLMClient) -> None:
        self.ocr = ocr_provider
        self.llm = llm_client

    async def process_denial(
        self,
        document_bytes: bytes,
        patient_context: PatientContext | None = None,
    ) -> AppealLetter:
        """
        Process a denial letter and generate an appeal.

        Pipeline:
        1. OCR: Extract text from denial document
        2. Extract: Parse denial reason, codes, deadlines
        3. Generate: Create appeal letter with medical necessity justification
        """
        log = logger.bind(has_patient_context=patient_context is not None)

        # Step 1: OCR extraction
        log.info("Starting OCR extraction")
        denial_text = await self.ocr.extract_text(document_bytes)
        log.info("OCR complete", text_length=len(denial_text))

        # Step 2: Structured extraction
        log.info("Extracting denial information")
        denial_info = await self.llm.extract_denial_info(denial_text)
        log.info(
            "Denial extracted",
            payer=denial_info.payer_name,
            reason=denial_info.denial_reason.value,
        )

        # Step 3: Generate appeal
        log.info("Generating appeal letter")
        appeal_content = await self.llm.generate_appeal(denial_info, patient_context)

        # Determine required attachments based on denial reason
        required_docs = self._get_required_documents(denial_info)

        appeal = AppealLetter(
            id=str(uuid.uuid4()),
            denial_extraction=denial_info,
            letter_content=appeal_content,
            required_attachments=required_docs,
            generated_at=datetime.utcnow(),
            confidence_score=self._calculate_confidence(denial_info),
        )

        log.info("Appeal generated", appeal_id=appeal.id)
        return appeal

    async def process_denial_from_text(
        self,
        denial_text: str,
        patient_context: PatientContext | None = None,
    ) -> AppealLetter:
        """
        Process a denial from pre-extracted text (skip OCR step).

        Useful for testing or when text is already available.
        """
        log = logger.bind(has_patient_context=patient_context is not None)

        # Step 1: Structured extraction
        log.info("Extracting denial information from text")
        denial_info = await self.llm.extract_denial_info(denial_text)

        # Step 2: Generate appeal
        log.info("Generating appeal letter")
        appeal_content = await self.llm.generate_appeal(denial_info, patient_context)

        required_docs = self._get_required_documents(denial_info)

        appeal = AppealLetter(
            id=str(uuid.uuid4()),
            denial_extraction=denial_info,
            letter_content=appeal_content,
            required_attachments=required_docs,
            generated_at=datetime.utcnow(),
            confidence_score=self._calculate_confidence(denial_info),
        )

        return appeal

    def _get_required_documents(self, denial: DenialExtraction) -> list[str]:
        """Determine required supporting documents based on denial reason."""
        base_docs = [
            "Copy of denial letter",
            "Patient insurance card (front and back)",
        ]

        reason_specific: dict[str, list[str]] = {
            "medical_necessity": [
                "Physician letter of medical necessity",
                "Relevant clinical notes and history",
                "Lab results and diagnostic imaging",
                "Peer-reviewed literature supporting treatment",
            ],
            "not_covered": [
                "Evidence of coverage under plan",
                "Summary of Benefits and Coverage (SBC)",
                "Prior authorization approval (if applicable)",
            ],
            "missing_information": [
                "All previously submitted documentation",
                "Additional requested documentation",
                "Updated patient information form",
            ],
            "step_therapy_required": [
                "Documentation of prior treatments tried",
                "Clinical notes showing treatment failures",
                "Adverse reaction documentation (if applicable)",
            ],
            "experimental_treatment": [
                "FDA approval documentation",
                "Clinical trial results",
                "Peer-reviewed studies supporting efficacy",
                "Letters from specialists",
            ],
            "out_of_network": [
                "Documentation of in-network unavailability",
                "Specialist referral",
                "Urgency documentation",
            ],
            "quantity_limit": [
                "Physician justification for quantity",
                "Treatment protocol documentation",
                "Prior authorization for increased quantity",
            ],
        }

        denial_reason = denial.denial_reason.value
        specific_docs = reason_specific.get(denial_reason, [])

        return base_docs + specific_docs

    def _calculate_confidence(self, denial: DenialExtraction) -> float:
        """
        Calculate confidence score based on extraction completeness.

        Higher scores indicate more complete information extraction.
        """
        score = 0.0
        max_score = 8.0

        if denial.payer_name:
            score += 1.0
        if denial.denial_date:
            score += 1.0
        if denial.denial_reason.value != "other":
            score += 1.5
        if denial.denial_reason_text:
            score += 1.0
        if denial.procedure_codes:
            score += 1.0
        if denial.diagnosis_codes:
            score += 1.0
        if denial.claim_number:
            score += 0.5
        if denial.appeal_deadline:
            score += 1.0

        return round(score / max_score, 2)
