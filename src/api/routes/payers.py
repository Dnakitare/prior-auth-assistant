"""Payer information and rules endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel

from src.core.repositories import generate_payer_seed_data

router = APIRouter()


class PayerInfo(BaseModel):
    """Payer information response model."""

    id: str
    name: str
    aliases: list[str]
    appeals_phone: str | None
    appeal_deadline_days: int
    medical_necessity_requirements: dict


class PayerListResponse(BaseModel):
    """List of payers response."""

    payers: list[PayerInfo]


@router.get("/payers", response_model=PayerListResponse)
async def list_payers() -> PayerListResponse:
    """
    List all known insurance payers with their appeal requirements.

    Returns payer-specific information including:
    - Contact information for appeals
    - Required documentation
    - Appeal deadlines
    - Tips for successful appeals
    """
    # For now, return seed data directly
    # In production, this would query the database
    payers = [
        PayerInfo(
            id=p["id"],
            name=p["name"],
            aliases=p["aliases"],
            appeals_phone=p.get("appeals_phone"),
            appeal_deadline_days=p.get("appeal_deadline_days", 180),
            medical_necessity_requirements=p.get("medical_necessity_requirements", {}),
        )
        for p in generate_payer_seed_data()
    ]

    return PayerListResponse(payers=payers)


@router.get("/payers/{payer_name}/requirements")
async def get_payer_requirements(payer_name: str) -> dict:
    """
    Get specific requirements for a payer.

    Returns documentation requirements and tips for successful appeals
    based on the denial reason type.
    """
    # Find payer in seed data
    payers = generate_payer_seed_data()
    for p in payers:
        if payer_name.lower() in p["name"].lower() or any(
            payer_name.lower() in alias.lower() for alias in p.get("aliases", [])
        ):
            return {
                "payer": p["name"],
                "appeal_deadline_days": p.get("appeal_deadline_days", 180),
                "appeals_phone": p.get("appeals_phone"),
                "medical_necessity": p.get("medical_necessity_requirements", {}),
                "step_therapy": p.get("step_therapy_requirements", {}),
                "documentation": p.get("documentation_requirements", {}),
            }

    return {
        "error": "Payer not found",
        "message": f"No requirements found for payer: {payer_name}",
    }
