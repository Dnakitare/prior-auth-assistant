"""Appeal letter templates for different denial reasons."""

TEMPLATES = {
    "medical_necessity": """
RE: Appeal for Denial of Prior Authorization - Medical Necessity
Date: {current_date}

Member: {patient_name}
Member ID: {member_id}
Claim Number: {claim_number}
Date of Service: {service_date}
Procedure: {procedure_code} - {procedure_description}
Diagnosis: {diagnosis_codes}

Dear {payer_name} Appeals Department,

I am writing to formally appeal the denial of prior authorization for {procedure_description} for the above-referenced patient. The denial letter dated {denial_date} indicates the procedure was denied due to lack of demonstrated medical necessity. We respectfully disagree with this determination and request an expedited review.

CLINICAL SUMMARY:

{patient_name} presents with {diagnosis_codes}, requiring {procedure_description}. The clinical evidence supporting the medical necessity of this intervention includes:

{clinical_notes}

PRIOR TREATMENT HISTORY:

The patient has undergone the following conservative treatments:
{prior_treatments}

Despite these interventions, the patient continues to experience significant symptoms that substantially impair daily functioning and quality of life.

MEDICAL NECESSITY JUSTIFICATION:

The requested procedure is medically necessary for the following reasons:

1. Conservative treatment options have been exhausted or are contraindicated
2. The patient meets established clinical criteria for this intervention
3. Continued delay in treatment poses significant risk to the patient's health outcomes
4. The procedure represents the standard of care for this clinical presentation

SUPPORTING CLINICAL GUIDELINES:

This treatment recommendation aligns with current clinical practice guidelines and peer-reviewed medical literature. The requested intervention is recognized as appropriate and effective for patients meeting these clinical criteria.

REQUEST FOR ACTION:

Based on the clinical evidence presented, we request that {payer_name} reverse the denial and authorize {procedure_description} for {patient_name}. Given the patient's clinical status and the potential for deterioration without treatment, we request expedited review within 72 hours per applicable regulations.

Please contact our office at [PHONE] if additional clinical documentation is required to support this appeal.

Respectfully submitted,

{treating_physician}
[CREDENTIALS]
[PRACTICE NAME]
[ADDRESS]
[PHONE/FAX]
[NPI NUMBER]

Enclosures:
{required_documents}
""",

    "step_therapy_required": """
RE: Appeal for Step Therapy Exception Request
Date: {current_date}

Member: {patient_name}
Member ID: {member_id}
Claim Number: {claim_number}
Procedure/Medication: {procedure_code} - {procedure_description}
Diagnosis: {diagnosis_codes}

Dear {payer_name} Appeals Department,

I am writing to request a step therapy exception for {procedure_description} for the above-referenced patient. The denial dated {denial_date} requires completion of step therapy protocols before authorization. We request an exception based on the clinical documentation provided below.

STEP THERAPY EXCEPTION CRITERIA MET:

Under applicable state and federal regulations, step therapy exceptions are warranted when:
- The required medication/treatment has been ineffective for the patient
- The required medication/treatment caused adverse reactions
- The required medication/treatment is contraindicated
- The patient is stable on the requested medication/treatment

PRIOR TREATMENTS ATTEMPTED:

The patient has previously tried and failed the following therapies:
{prior_treatments}

CLINICAL DOCUMENTATION OF TREATMENT FAILURES:

{clinical_notes}

CONTRAINDICATIONS/ADVERSE REACTIONS:

[Document any contraindications or adverse reactions experienced]

RATIONALE FOR REQUESTED TREATMENT:

Based on the patient's treatment history and clinical presentation, {procedure_description} is the most appropriate next step in their care. Requiring additional step therapy would:

1. Delay necessary treatment without clinical benefit
2. Expose the patient to medications/treatments already proven ineffective
3. Risk adverse outcomes from known contraindications
4. Not align with current clinical practice guidelines

REQUEST:

We respectfully request that {payer_name} grant a step therapy exception and authorize {procedure_description} for {patient_name}. The clinical documentation demonstrates that step therapy requirements have been satisfied or that an exception is medically appropriate.

Sincerely,

{treating_physician}
[CREDENTIALS]
[PRACTICE NAME]
[CONTACT INFORMATION]

Enclosures:
{required_documents}
""",

    "not_covered": """
RE: Appeal for Coverage Determination - Benefit Coverage Dispute
Date: {current_date}

Member: {patient_name}
Member ID: {member_id}
Claim Number: {claim_number}
Procedure: {procedure_code} - {procedure_description}
Diagnosis: {diagnosis_codes}

Dear {payer_name} Appeals Department,

I am writing to appeal the denial of coverage for {procedure_description}, which was denied on {denial_date} as "not a covered benefit." We believe this determination is incorrect and request a review of coverage under the patient's plan.

COVERAGE ANALYSIS:

Based on our review of the member's Summary of Benefits and Coverage (SBC) and Evidence of Coverage (EOC), we believe {procedure_description} should be covered under:

[SPECIFY APPLICABLE BENEFIT CATEGORY]

CLINICAL NECESSITY:

Even if {payer_name} considers this procedure to fall outside standard coverage, we submit that coverage is required because:

1. The procedure is medically necessary for the treatment of {diagnosis_codes}
2. Denial of coverage would result in adverse health outcomes
3. The service falls within a covered benefit category when properly classified
4. Applicable state/federal mandates may require coverage

SUPPORTING DOCUMENTATION:

{clinical_notes}

REGULATORY CONSIDERATIONS:

[Include any applicable state mandates, ACA essential health benefits requirements, or parity laws that may apply]

REQUEST:

We request that {payer_name}:
1. Review the coverage determination under the correct benefit category
2. Provide specific plan language supporting the denial if coverage is not available
3. Authorize the requested procedure if coverage is confirmed

Please respond within the timeframes required by applicable regulations.

Sincerely,

{treating_physician}
[CREDENTIALS]
[PRACTICE NAME]
[CONTACT INFORMATION]

Enclosures:
{required_documents}
""",

    "out_of_network": """
RE: Appeal for Out-of-Network Exception/Gap Exception Request
Date: {current_date}

Member: {patient_name}
Member ID: {member_id}
Claim Number: {claim_number}
Procedure: {procedure_code} - {procedure_description}
Provider: {treating_physician}
Diagnosis: {diagnosis_codes}

Dear {payer_name} Appeals Department,

I am writing to request an out-of-network exception for services provided by {treating_physician} for {procedure_description}. The claim was denied on {denial_date} due to out-of-network status. We request in-network benefits be applied based on the following circumstances.

GROUNDS FOR NETWORK EXCEPTION:

1. NO IN-NETWORK PROVIDER AVAILABLE

After reasonable effort, the member was unable to locate an in-network provider who:
- Offers the specific service required ({procedure_description})
- Is accepting new patients
- Can provide services within a reasonable timeframe
- Is located within a reasonable geographic distance

[Document search efforts and results]

2. CONTINUITY OF CARE

The member has an established relationship with {treating_physician} for the treatment of {diagnosis_codes}. Disrupting this care relationship would:
- Compromise treatment outcomes
- Require unnecessary duplication of services
- Delay time-sensitive treatment

3. SPECIALIZED EXPERTISE REQUIRED

{procedure_description} requires specialized expertise that is not available within the network. {treating_physician} has specific qualifications necessary for this patient's care:

[Document specialized expertise]

CLINICAL DOCUMENTATION:

{clinical_notes}

REQUEST:

We request that {payer_name} authorize {procedure_description} with in-network benefit levels due to the documented network inadequacy or continuity of care requirements. If this request cannot be approved, please provide:

1. Names and contact information of in-network providers offering this service
2. Confirmation that identified providers are accepting new patients
3. Timeline for patient access to in-network care

Sincerely,

{treating_physician}
[CREDENTIALS]
[PRACTICE NAME]
[CONTACT INFORMATION]

Enclosures:
{required_documents}
""",

    "missing_information": """
RE: Appeal with Additional Documentation - Previously Denied for Missing Information
Date: {current_date}

Member: {patient_name}
Member ID: {member_id}
Claim Number: {claim_number}
Procedure: {procedure_code} - {procedure_description}
Diagnosis: {diagnosis_codes}

Dear {payer_name} Appeals Department,

I am resubmitting the prior authorization request for {procedure_description}, which was denied on {denial_date} due to missing or insufficient documentation. This appeal includes all requested documentation to support authorization.

ORIGINAL DENIAL REASON:

"{denial_reason_text}"

DOCUMENTATION NOW PROVIDED:

In response to the information request, we are submitting the following:

{prior_treatments}

ADDITIONAL CLINICAL INFORMATION:

{clinical_notes}

SUMMARY OF MEDICAL NECESSITY:

{patient_name} requires {procedure_description} for the treatment of {diagnosis_codes}. The enclosed documentation demonstrates:

1. Clinical diagnosis and severity
2. Treatment history and prior interventions
3. Medical necessity for the requested procedure
4. Expected outcomes and treatment plan

REQUEST:

With the complete documentation now provided, we request that {payer_name} approve the prior authorization for {procedure_description}. All previously identified documentation gaps have been addressed in this submission.

Please contact our office if any additional information is required.

Sincerely,

{treating_physician}
[CREDENTIALS]
[PRACTICE NAME]
[CONTACT INFORMATION]

Enclosures:
{required_documents}
""",

    "experimental_treatment": """
RE: Appeal for Coverage of Treatment Denied as Experimental/Investigational
Date: {current_date}

Member: {patient_name}
Member ID: {member_id}
Claim Number: {claim_number}
Procedure/Treatment: {procedure_code} - {procedure_description}
Diagnosis: {diagnosis_codes}

Dear {payer_name} Appeals Department,

I am writing to appeal the denial of {procedure_description}, which was denied on {denial_date} as "experimental" or "investigational." We respectfully disagree with this characterization and provide evidence that this treatment is established, effective, and appropriate for {patient_name}.

TREATMENT STATUS - NOT EXPERIMENTAL:

{procedure_description} should not be classified as experimental because:

1. FDA APPROVAL STATUS:
[Document FDA approval, clearance, or established use]

2. CLINICAL EVIDENCE BASE:
The treatment is supported by substantial clinical evidence including:
- Peer-reviewed published studies
- Clinical practice guidelines
- Professional society recommendations

3. STANDARD OF CARE:
{procedure_description} is recognized as standard of care for {diagnosis_codes} by:
[List relevant professional organizations and guidelines]

4. WIDESPREAD ADOPTION:
This treatment is routinely covered by other major insurers and is performed at leading medical institutions nationwide.

CLINICAL NECESSITY FOR THIS PATIENT:

{clinical_notes}

LITERATURE SUPPORT:

[Cite specific peer-reviewed studies supporting efficacy]

PRIOR TREATMENTS:
{prior_treatments}

REQUEST:

Based on the substantial evidence that {procedure_description} is established, effective, and medically necessary, we request that {payer_name}:

1. Reclassify this treatment as non-experimental
2. Authorize the requested procedure for {patient_name}
3. If denied, provide the specific clinical criteria used in the determination

Sincerely,

{treating_physician}
[CREDENTIALS]
[PRACTICE NAME]
[CONTACT INFORMATION]

Enclosures:
{required_documents}
""",

    "quantity_limit": """
RE: Appeal for Quantity Limit Exception
Date: {current_date}

Member: {patient_name}
Member ID: {member_id}
Claim Number: {claim_number}
Medication/Supply: {procedure_code} - {procedure_description}
Diagnosis: {diagnosis_codes}

Dear {payer_name} Appeals Department,

I am writing to request a quantity limit exception for {procedure_description} for the above-referenced patient. The prescription/order was denied on {denial_date} due to quantity limits. We request an exception based on clinical necessity.

CURRENT QUANTITY LIMIT:
[Specify current allowed quantity]

REQUESTED QUANTITY:
[Specify requested quantity]

CLINICAL JUSTIFICATION FOR INCREASED QUANTITY:

{patient_name} requires a quantity exceeding the standard limit due to:

{clinical_notes}

RELEVANT FACTORS:

1. Disease severity: {diagnosis_codes}
2. Treatment protocol requirements
3. Patient-specific factors affecting dosing/usage
4. Prior treatment at standard quantities was inadequate

SUPPORTING DOCUMENTATION:
{prior_treatments}

FDA/MANUFACTURER DOSING:

[Reference FDA-approved dosing or manufacturer recommendations that support the requested quantity]

REQUEST:

We request that {payer_name} approve a quantity limit exception to allow [REQUESTED QUANTITY] of {procedure_description} for {patient_name}. This quantity is medically necessary for adequate treatment of the patient's condition.

Sincerely,

{treating_physician}
[CREDENTIALS]
[PRACTICE NAME]
[CONTACT INFORMATION]

Enclosures:
{required_documents}
""",

    "prior_auth_required": """
RE: Retroactive Prior Authorization Request / Appeal for Timely Filing
Date: {current_date}

Member: {patient_name}
Member ID: {member_id}
Claim Number: {claim_number}
Date of Service: {service_date}
Procedure: {procedure_code} - {procedure_description}
Diagnosis: {diagnosis_codes}

Dear {payer_name} Appeals Department,

I am writing to request retroactive prior authorization for {procedure_description} provided on {service_date}. The claim was denied on {denial_date} because prior authorization was not obtained before the service. We request approval based on the circumstances below.

REASON PRIOR AUTHORIZATION WAS NOT OBTAINED:

[Select applicable reason:]
- Emergency/urgent medical situation
- Provider was unaware PA was required
- Service was rendered during inpatient stay
- Authorization was requested but not processed timely
- Other: [specify]

DOCUMENTATION OF MEDICAL NECESSITY:

{clinical_notes}

The service was medically necessary at the time provided because:
{prior_treatments}

CLINICAL URGENCY:

[If applicable, document why the service could not be delayed to obtain PA]

REQUEST:

We request that {payer_name}:
1. Grant retroactive authorization for the service provided
2. Process the claim with appropriate benefits applied

The clinical documentation demonstrates the service was medically necessary and would have been authorized had the request been submitted prospectively.

Sincerely,

{treating_physician}
[CREDENTIALS]
[PRACTICE NAME]
[CONTACT INFORMATION]

Enclosures:
{required_documents}
""",

    "default": """
RE: Appeal for Prior Authorization Denial
Date: {current_date}

Member: {patient_name}
Member ID: {member_id}
Claim Number: {claim_number}
Date of Service: {service_date}
Procedure: {procedure_code} - {procedure_description}
Diagnosis: {diagnosis_codes}

Dear {payer_name} Appeals Department,

I am writing to formally appeal the denial of prior authorization for {procedure_description}, denied on {denial_date}. The denial stated:

"{denial_reason_text}"

We respectfully disagree with this determination and submit the following information in support of authorization.

PATIENT CLINICAL SUMMARY:

{clinical_notes}

DIAGNOSIS AND TREATMENT HISTORY:

Primary Diagnosis: {diagnosis_codes}

Prior Treatments:
{prior_treatments}

MEDICAL NECESSITY JUSTIFICATION:

{procedure_description} is medically necessary for {patient_name} based on:

1. Clinical presentation and diagnosis
2. Failure or contraindication of alternative treatments
3. Expected benefit from the requested intervention
4. Alignment with current clinical practice guidelines

SUPPORTING DOCUMENTATION:

The enclosed materials provide additional clinical support for this request.

REQUEST:

We request that {payer_name} reverse the denial and authorize {procedure_description} for {patient_name}. Please contact our office if additional information is needed to process this appeal.

Sincerely,

{treating_physician}
[CREDENTIALS]
[PRACTICE NAME]
[CONTACT INFORMATION]

Enclosures:
{required_documents}
"""
}


def get_template(denial_reason: str) -> str:
    """Get the appropriate template for a denial reason."""
    return TEMPLATES.get(denial_reason, TEMPLATES["default"])


def get_required_documents(denial_reason: str) -> list[str]:
    """Get required documents based on denial reason."""
    base_docs = [
        "Copy of denial letter",
        "Patient insurance card (front and back)",
    ]

    reason_specific = {
        "medical_necessity": [
            "Physician letter of medical necessity",
            "Relevant clinical notes and history",
            "Lab results and diagnostic imaging",
            "Peer-reviewed literature supporting treatment",
            "Treatment plan documentation",
        ],
        "step_therapy_required": [
            "Documentation of all prior treatments attempted",
            "Clinical notes showing treatment failures or adverse reactions",
            "Pharmacy records showing previous medications filled",
            "Documentation of contraindications (if applicable)",
        ],
        "not_covered": [
            "Summary of Benefits and Coverage (SBC)",
            "Evidence of Coverage (EOC) relevant sections",
            "Documentation supporting benefit category classification",
            "Any applicable state mandate documentation",
        ],
        "out_of_network": [
            "Documentation of in-network provider search",
            "Evidence of network inadequacy",
            "Continuity of care documentation",
            "Provider qualifications/credentials",
        ],
        "missing_information": [
            "All previously submitted documentation",
            "Specifically requested missing documents",
            "Updated clinical notes",
            "Any additional supporting materials",
        ],
        "experimental_treatment": [
            "FDA approval documentation",
            "Published peer-reviewed clinical studies",
            "Clinical practice guidelines",
            "Professional society position statements",
            "Evidence of coverage by other major insurers",
        ],
        "quantity_limit": [
            "Physician justification for quantity",
            "Treatment protocol documentation",
            "Disease severity documentation",
            "FDA/manufacturer dosing guidelines",
        ],
        "prior_auth_required": [
            "Documentation of emergency/urgency (if applicable)",
            "Clinical notes from date of service",
            "Evidence of medical necessity",
            "Explanation for lack of prospective authorization",
        ],
    }

    specific_docs = reason_specific.get(denial_reason, [
        "Supporting clinical documentation",
        "Physician statement",
    ])

    return base_docs + specific_docs
