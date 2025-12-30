"""LLM integration for appeal generation."""

import anthropic

from src.core.config import settings
from src.core.models import AppealLetter, DenialExtraction, PatientContext

DENIAL_EXTRACTION_PROMPT = """You are a healthcare prior authorization specialist.
Analyze the following denial letter and extract key information.

Denial Letter Text:
{denial_text}

Extract and return the following in a structured format:
1. Payer/Insurance company name
2. Denial date
3. Primary denial reason (medical_necessity, not_covered, out_of_network, missing_information, experimental_treatment, step_therapy_required, quantity_limit, prior_auth_required, other)
4. Denial reason explanation text
5. Procedure codes (CPT codes)
6. Diagnosis codes (ICD-10)
7. Member ID
8. Claim number
9. Appeal deadline

Return as JSON."""

APPEAL_GENERATION_PROMPT = """You are a healthcare prior authorization appeals specialist.
Generate a compelling medical necessity appeal letter based on the following information.

Denial Information:
- Payer: {payer_name}
- Denial Reason: {denial_reason}
- Denial Explanation: {denial_reason_text}
- Procedure: {procedure_code}
- Diagnoses: {diagnosis_codes}

Patient Context:
{patient_context}

Write a professional appeal letter that:
1. Clearly states this is an appeal of the denial
2. References the specific denial reason
3. Provides medical necessity justification
4. Cites relevant clinical guidelines when applicable
5. Requests expedited review if appropriate
6. Lists required supporting documentation

The tone should be professional but assertive."""


class LLMClient:
    """Client for LLM-based text generation."""

    def __init__(self) -> None:
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    async def extract_denial_info(self, denial_text: str) -> DenialExtraction:
        """Extract structured information from denial letter text."""
        message = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": DENIAL_EXTRACTION_PROMPT.format(denial_text=denial_text),
                }
            ],
        )

        # TODO: Parse JSON response into DenialExtraction model
        return DenialExtraction(raw_text=denial_text)

    async def generate_appeal(
        self,
        denial: DenialExtraction,
        patient_context: PatientContext | None = None,
    ) -> str:
        """Generate an appeal letter based on denial and patient context."""
        context_str = ""
        if patient_context:
            context_str = f"""
            Patient: {patient_context.patient_name}
            Procedure: {patient_context.procedure_description or patient_context.procedure_code}
            Prior Treatments: {', '.join(patient_context.prior_treatments) if patient_context.prior_treatments else 'N/A'}
            Clinical Notes: {patient_context.clinical_notes or 'N/A'}
            """

        message = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": APPEAL_GENERATION_PROMPT.format(
                        payer_name=denial.payer_name or "Unknown",
                        denial_reason=denial.denial_reason.value,
                        denial_reason_text=denial.denial_reason_text or "Not specified",
                        procedure_code=", ".join(denial.procedure_codes) or "Not specified",
                        diagnosis_codes=", ".join(denial.diagnosis_codes) or "Not specified",
                        patient_context=context_str or "No additional context provided",
                    ),
                }
            ],
        )

        return message.content[0].text


def get_llm_client() -> LLMClient:
    """Factory function to get LLM client."""
    return LLMClient()
