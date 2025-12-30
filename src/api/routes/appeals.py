"""Appeal generation endpoints."""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from src.core.models import AppealLetter, DenialExtraction, PatientContext
from src.core.services import AppealGenerationService
from src.integrations.llm import get_llm_client
from src.integrations.ocr import get_ocr_provider

router = APIRouter()


class AppealResponse(BaseModel):
    """Response model for generated appeal."""

    appeal_id: str
    appeal_letter: str
    denial_info: DenialExtraction
    required_documents: list[str]
    confidence_score: float


class TextAppealRequest(BaseModel):
    """Request for appeal generation from text input."""

    denial_text: str
    patient_name: str | None = None
    procedure_code: str | None = None
    procedure_description: str | None = None
    diagnosis_codes: list[str] | None = None
    clinical_notes: str | None = None
    prior_treatments: list[str] | None = None
    treating_physician: str | None = None


def get_appeal_service() -> AppealGenerationService:
    """Create appeal service with dependencies."""
    return AppealGenerationService(
        ocr_provider=get_ocr_provider(),
        llm_client=get_llm_client(),
    )


@router.post("/appeals/upload", response_model=AppealResponse)
async def generate_appeal_from_document(
    denial_letter: UploadFile = File(..., description="PDF or image of denial letter"),
    patient_name: str | None = Form(None),
    procedure_code: str | None = Form(None),
    procedure_description: str | None = Form(None),
    diagnosis_codes: str | None = Form(None, description="Comma-separated ICD-10 codes"),
    clinical_notes: str | None = Form(None),
    prior_treatments: str | None = Form(None, description="Comma-separated list"),
    treating_physician: str | None = Form(None),
) -> AppealResponse:
    """
    Generate an appeal letter from an uploaded denial document.

    Accepts PDF or image files. OCR extracts the text, then the pipeline
    analyzes the denial and generates an appeal letter.
    """
    # Validate file type
    if denial_letter.content_type not in [
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/tiff",
    ]:
        raise HTTPException(
            status_code=400,
            detail="File must be PDF, PNG, JPEG, or TIFF",
        )

    # Read file content
    content = await denial_letter.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    # Build patient context if provided
    patient_context = None
    if patient_name or procedure_code:
        patient_context = PatientContext(
            patient_name=patient_name or "Unknown",
            procedure_code=procedure_code or "Unknown",
            procedure_description=procedure_description,
            diagnosis_codes=diagnosis_codes.split(",") if diagnosis_codes else [],
            clinical_notes=clinical_notes,
            prior_treatments=prior_treatments.split(",") if prior_treatments else [],
            treating_physician=treating_physician,
        )

    # Process through pipeline
    service = get_appeal_service()
    try:
        appeal = await service.process_denial(content, patient_context)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process denial: {str(e)}")

    return AppealResponse(
        appeal_id=appeal.id,
        appeal_letter=appeal.letter_content,
        denial_info=appeal.denial_extraction,
        required_documents=appeal.required_attachments,
        confidence_score=appeal.confidence_score,
    )


@router.post("/appeals/text", response_model=AppealResponse)
async def generate_appeal_from_text(request: TextAppealRequest) -> AppealResponse:
    """
    Generate an appeal letter from denial text.

    Use this endpoint when you already have the denial letter text
    (e.g., from copy-paste or a different OCR system).
    """
    if not request.denial_text or len(request.denial_text) < 50:
        raise HTTPException(
            status_code=400,
            detail="Denial text must be at least 50 characters",
        )

    # Build patient context if provided
    patient_context = None
    if request.patient_name or request.procedure_code:
        patient_context = PatientContext(
            patient_name=request.patient_name or "Unknown",
            procedure_code=request.procedure_code or "Unknown",
            procedure_description=request.procedure_description,
            diagnosis_codes=request.diagnosis_codes or [],
            clinical_notes=request.clinical_notes,
            prior_treatments=request.prior_treatments or [],
            treating_physician=request.treating_physician,
        )

    # Process through pipeline (skip OCR)
    service = get_appeal_service()
    try:
        appeal = await service.process_denial_from_text(
            request.denial_text,
            patient_context,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process denial: {str(e)}")

    return AppealResponse(
        appeal_id=appeal.id,
        appeal_letter=appeal.letter_content,
        denial_info=appeal.denial_extraction,
        required_documents=appeal.required_attachments,
        confidence_score=appeal.confidence_score,
    )


@router.get("/appeals/{appeal_id}")
async def get_appeal(appeal_id: str) -> dict[str, str]:
    """
    Retrieve a previously generated appeal.

    Note: Currently returns not_found as persistence is not yet implemented.
    """
    # TODO: Implement appeal retrieval from database
    return {"appeal_id": appeal_id, "status": "not_found"}
