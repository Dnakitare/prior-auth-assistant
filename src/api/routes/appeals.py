"""Appeal generation endpoints."""

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel

router = APIRouter()


class AppealRequest(BaseModel):
    """Request model for appeal generation."""

    patient_name: str
    procedure_code: str
    diagnosis_codes: list[str]
    additional_context: str | None = None


class AppealResponse(BaseModel):
    """Response model for generated appeal."""

    appeal_id: str
    appeal_letter: str
    denial_reason: str | None
    required_documents: list[str]
    confidence_score: float


@router.post("/appeals/generate")
async def generate_appeal(
    denial_letter: UploadFile = File(...),
) -> dict[str, str]:
    """
    Generate an appeal letter from a denial letter.

    Accepts a PDF/image of the denial letter, extracts the denial reason,
    and generates a medical necessity appeal letter.
    """
    # TODO: Implement OCR extraction
    # TODO: Implement appeal generation
    return {
        "status": "processing",
        "message": f"Received denial letter: {denial_letter.filename}",
    }


@router.post("/appeals/generate-with-context")
async def generate_appeal_with_context(
    request: AppealRequest,
    denial_letter: UploadFile = File(...),
) -> dict[str, str]:
    """
    Generate an appeal with additional patient context.

    Combines the denial letter with structured patient information
    for more targeted appeal generation.
    """
    # TODO: Implement full appeal generation pipeline
    return {
        "status": "processing",
        "patient": request.patient_name,
        "procedure": request.procedure_code,
    }


@router.get("/appeals/{appeal_id}")
async def get_appeal(appeal_id: str) -> dict[str, str]:
    """Retrieve a previously generated appeal."""
    # TODO: Implement appeal retrieval from database
    return {"appeal_id": appeal_id, "status": "not_found"}
