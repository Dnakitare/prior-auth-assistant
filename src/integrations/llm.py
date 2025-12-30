"""LLM integration for appeal generation."""

import json
import re
from datetime import datetime

import anthropic
import structlog

from src.core.config import settings
from src.core.models import DenialExtraction, DenialReason, PatientContext

logger = structlog.get_logger()

DENIAL_EXTRACTION_PROMPT = """You are a healthcare prior authorization specialist analyzing denial letters.

Extract the following information from this denial letter and return ONLY valid JSON (no markdown, no explanation):

<denial_letter>
{denial_text}
</denial_letter>

Return this exact JSON structure:
{{
    "payer_name": "string or null",
    "denial_date": "YYYY-MM-DD or null",
    "denial_reason": "one of: medical_necessity, not_covered, out_of_network, missing_information, experimental_treatment, step_therapy_required, quantity_limit, prior_auth_required, other",
    "denial_reason_text": "exact quote from letter explaining denial or null",
    "procedure_codes": ["CPT codes as strings"],
    "diagnosis_codes": ["ICD-10 codes as strings"],
    "member_id": "string or null",
    "claim_number": "string or null",
    "appeal_deadline": "YYYY-MM-DD or null"
}}

Important:
- Extract exact values from the letter, don't infer
- Use null for missing information
- denial_reason must be one of the specified values
- Dates should be YYYY-MM-DD format"""

APPEAL_TEMPLATES = {
    "medical_necessity": """
RE: Appeal for Denial of Prior Authorization - Medical Necessity
Member: {patient_name}
Member ID: {member_id}
Claim Number: {claim_number}
Date of Service: {service_date}
Procedure: {procedure_code} - {procedure_description}

Dear {payer_name} Appeals Department,

I am writing to formally appeal the denial of prior authorization for {procedure_description} for the above-referenced patient. The denial letter dated {denial_date} states the procedure was denied due to lack of medical necessity. We respectfully disagree with this determination and request an expedited review.

CLINICAL JUSTIFICATION:

{patient_name} has been diagnosed with {diagnosis_codes}, which necessitates the requested treatment. The clinical evidence supporting medical necessity includes:

{clinical_notes}

PRIOR TREATMENTS:
{prior_treatments}

The requested procedure is medically necessary because:
1. Conservative treatments have been attempted and failed or are contraindicated
2. The patient's condition meets established clinical criteria for this intervention
3. Delaying treatment poses significant risk to the patient's health outcomes

SUPPORTING EVIDENCE:

This treatment is supported by current clinical guidelines and peer-reviewed literature. The requested intervention represents the standard of care for patients with this clinical presentation.

REQUEST:

We request that {payer_name} reverse the denial and authorize {procedure_description} for {patient_name}. Given the patient's clinical status, we request an expedited review within 72 hours.

Please contact our office if additional clinical documentation is required.

Sincerely,

[Treating Physician Name, MD]
[Practice Name]
[Phone Number]
[Fax Number]
""",
    "step_therapy_required": """
RE: Appeal for Denial - Step Therapy Override Request
Member: {patient_name}
Member ID: {member_id}
Claim Number: {claim_number}
Procedure: {procedure_code} - {procedure_description}

Dear {payer_name} Appeals Department,

I am writing to appeal the denial requiring step therapy for {procedure_description}. We request an exception to the step therapy requirement based on the following clinical justification.

PRIOR TREATMENTS ATTEMPTED:
{prior_treatments}

The patient has previously failed or is contraindicated for the required step therapy medications due to:
{clinical_notes}

Based on the patient's treatment history and clinical presentation, continuing to require additional step therapy would:
1. Delay necessary treatment
2. Expose the patient to unnecessary risk of adverse events
3. Not provide clinical benefit given documented treatment failures

We request approval for {procedure_description} as the appropriate next step in this patient's care.

Sincerely,

[Treating Physician Name, MD]
""",
    "default": """
RE: Appeal for Prior Authorization Denial
Member: {patient_name}
Member ID: {member_id}
Claim Number: {claim_number}
Date of Service: {service_date}
Procedure: {procedure_code} - {procedure_description}

Dear {payer_name} Appeals Department,

I am writing to formally appeal the denial of prior authorization referenced above. The denial dated {denial_date} cited the following reason:

"{denial_reason_text}"

We respectfully disagree with this determination and submit the following information in support of our appeal:

PATIENT CLINICAL SUMMARY:
{clinical_notes}

DIAGNOSIS: {diagnosis_codes}

TREATMENT HISTORY:
{prior_treatments}

MEDICAL JUSTIFICATION:
The requested treatment is appropriate for this patient based on their clinical presentation, diagnosis, and treatment history. We believe authorization should be granted based on the supporting documentation provided.

We request a timely review of this appeal and authorization of the requested service.

Sincerely,

[Treating Physician Name, MD]
[Practice Name]
[Contact Information]
"""
}

APPEAL_ENHANCEMENT_PROMPT = """You are a healthcare appeals specialist. Enhance the following appeal letter draft by:

1. Making it more persuasive while maintaining professionalism
2. Adding specific clinical language appropriate for the diagnosis
3. Ensuring all placeholders are properly filled or noted as [TO BE COMPLETED]
4. Adding relevant clinical guidelines or standards of care references where appropriate
5. Improving flow and readability

Original draft:
{draft}

Denial context:
- Payer: {payer_name}
- Denial reason: {denial_reason}
- Procedure: {procedure_codes}
- Diagnoses: {diagnosis_codes}

Patient context:
{patient_context}

Return the enhanced appeal letter. Maintain the formal letter format."""


class LLMClient:
    """Client for LLM-based text generation."""

    def __init__(self) -> None:
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    async def extract_denial_info(self, denial_text: str) -> DenialExtraction:
        """Extract structured information from denial letter text."""
        log = logger.bind(text_length=len(denial_text))
        log.info("Sending extraction request to LLM")

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

        response_text = message.content[0].text
        log.debug("LLM response received", response_length=len(response_text))

        # Parse JSON from response
        try:
            # Try to extract JSON from response (handle potential markdown wrapping)
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(response_text)
        except json.JSONDecodeError as e:
            log.error("Failed to parse LLM response as JSON", error=str(e))
            # Return minimal extraction with raw text
            return DenialExtraction(raw_text=denial_text)

        # Map denial reason string to enum
        reason_str = data.get("denial_reason", "other")
        try:
            denial_reason = DenialReason(reason_str)
        except ValueError:
            denial_reason = DenialReason.OTHER

        # Parse dates
        denial_date = None
        if data.get("denial_date"):
            try:
                denial_date = datetime.strptime(data["denial_date"], "%Y-%m-%d")
            except ValueError:
                pass

        appeal_deadline = None
        if data.get("appeal_deadline"):
            try:
                appeal_deadline = datetime.strptime(data["appeal_deadline"], "%Y-%m-%d")
            except ValueError:
                pass

        extraction = DenialExtraction(
            payer_name=data.get("payer_name"),
            denial_date=denial_date,
            denial_reason=denial_reason,
            denial_reason_text=data.get("denial_reason_text"),
            procedure_codes=data.get("procedure_codes", []),
            diagnosis_codes=data.get("diagnosis_codes", []),
            member_id=data.get("member_id"),
            claim_number=data.get("claim_number"),
            appeal_deadline=appeal_deadline,
            raw_text=denial_text,
        )

        log.info(
            "Extraction complete",
            payer=extraction.payer_name,
            reason=extraction.denial_reason.value,
        )
        return extraction

    async def generate_appeal(
        self,
        denial: DenialExtraction,
        patient_context: PatientContext | None = None,
    ) -> str:
        """Generate an appeal letter based on denial and patient context."""
        log = logger.bind(
            denial_reason=denial.denial_reason.value,
            has_context=patient_context is not None,
        )

        # Select template based on denial reason
        template_key = denial.denial_reason.value
        if template_key not in APPEAL_TEMPLATES:
            template_key = "default"

        template = APPEAL_TEMPLATES[template_key]

        # Prepare template variables
        draft = template.format(
            patient_name=patient_context.patient_name if patient_context else "[PATIENT NAME]",
            member_id=denial.member_id or patient_context.member_id if patient_context else "[MEMBER ID]",
            claim_number=denial.claim_number or "[CLAIM NUMBER]",
            service_date="[DATE OF SERVICE]",
            procedure_code=", ".join(denial.procedure_codes) if denial.procedure_codes else "[PROCEDURE CODE]",
            procedure_description=patient_context.procedure_description if patient_context else "[PROCEDURE DESCRIPTION]",
            payer_name=denial.payer_name or "[INSURANCE COMPANY]",
            denial_date=denial.denial_date.strftime("%B %d, %Y") if denial.denial_date else "[DENIAL DATE]",
            diagnosis_codes=", ".join(denial.diagnosis_codes) if denial.diagnosis_codes else "[DIAGNOSIS CODES]",
            clinical_notes=patient_context.clinical_notes if patient_context and patient_context.clinical_notes else "[CLINICAL NOTES TO BE ADDED]",
            prior_treatments="\n".join(f"- {t}" for t in patient_context.prior_treatments) if patient_context and patient_context.prior_treatments else "[PRIOR TREATMENTS TO BE ADDED]",
            denial_reason_text=denial.denial_reason_text or "[DENIAL REASON]",
        )

        # Build patient context string for enhancement
        context_str = "No additional patient context provided."
        if patient_context:
            context_str = f"""
Patient: {patient_context.patient_name}
DOB: {patient_context.date_of_birth or 'Not provided'}
Procedure: {patient_context.procedure_code} - {patient_context.procedure_description or 'Not specified'}
Treating Physician: {patient_context.treating_physician or 'Not specified'}
Prior Treatments: {', '.join(patient_context.prior_treatments) if patient_context.prior_treatments else 'None documented'}
Clinical Notes: {patient_context.clinical_notes or 'None provided'}
"""

        log.info("Enhancing appeal draft with LLM")

        message = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2500,
            messages=[
                {
                    "role": "user",
                    "content": APPEAL_ENHANCEMENT_PROMPT.format(
                        draft=draft,
                        payer_name=denial.payer_name or "Unknown",
                        denial_reason=denial.denial_reason.value,
                        procedure_codes=", ".join(denial.procedure_codes) or "Not specified",
                        diagnosis_codes=", ".join(denial.diagnosis_codes) or "Not specified",
                        patient_context=context_str,
                    ),
                }
            ],
        )

        log.info("Appeal generation complete")
        return message.content[0].text


def get_llm_client() -> LLMClient:
    """Factory function to get LLM client."""
    return LLMClient()
