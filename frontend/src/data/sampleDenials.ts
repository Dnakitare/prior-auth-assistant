// Synthetic denial letters for the demo "Try a sample" button. Names,
// member IDs, and addresses are fabricated. Procedure and diagnosis codes
// are real CPT/ICD-10 codes so the extraction pipeline behaves realistically.

export interface SampleDenial {
  id: string;
  label: string;
  reason: string;
  text: string;
}

export const sampleDenials: SampleDenial[] = [
  {
    id: 'medical-necessity-knee',
    label: 'Knee replacement — medical necessity',
    reason: 'medical_necessity',
    text: `EVERGREEN HEALTH PLAN
Claims & Authorization Department
PO Box 9921
Springfield, IL 62701

Date: April 12, 2026

RE: DENIAL OF PRIOR AUTHORIZATION
Member: Jane Doe
Member ID: EVG-558811234
Claim Number: CLM-2026-44219
Date of Service Requested: April 28, 2026

Dear Member,

Your request for prior authorization for the following service has been DENIED.

Procedure Requested: 27447 - Total knee arthroplasty, right knee
Diagnosis: M17.11 - Primary osteoarthritis, right knee

REASON FOR DENIAL:
The submitted documentation does not establish medical necessity for the
requested procedure. Specifically, our review found insufficient evidence
of a sustained trial of conservative therapy. Our clinical guidelines
require documentation of:
  - At least 3 months of physical therapy with objective progress notes
  - Documented trial of NSAIDs or other pharmacologic management
  - Recent weight-bearing imaging demonstrating advanced joint degeneration
  - BMI within program guidelines or documented weight-management plan

APPEAL RIGHTS:
You may appeal this determination within 180 days. Submit a written appeal
along with supporting clinical documentation to the address above.

Sincerely,
Medical Review, Evergreen Health Plan`,
  },
  {
    id: 'step-therapy',
    label: 'Specialty medication — step therapy required',
    reason: 'step_therapy_required',
    text: `MERIDIAN MUTUAL HEALTH
Pharmacy Benefits Division

Date: March 30, 2026

RE: PRIOR AUTHORIZATION DECISION
Member: Robert Chen
Member ID: MMH-330055901
Claim Number: RX-2026-09887

Medication Requested: Adalimumab 40 mg subcutaneous injection
Diagnosis: M05.79 - Rheumatoid arthritis with rheumatoid factor

DETERMINATION: DENIED — STEP THERAPY REQUIRED

The requested specialty medication is not approved at this stage of
treatment. Per Meridian Mutual's step-therapy policy for inflammatory
arthritis, members must first demonstrate an inadequate response to or
documented intolerance of:

  Step 1: Methotrexate (≥ 12 weeks at therapeutic dose) AND
  Step 2: A second conventional DMARD (sulfasalazine, leflunomide,
          or hydroxychloroquine) for ≥ 12 weeks

Our records show no claim history for Step 2 therapy. If the prescribing
physician determines that step therapy is medically inappropriate for this
member, a step-therapy exception request may be submitted with clinical
justification.

APPEAL RIGHTS:
A first-level appeal must be filed within 60 days of this notice.

Member Services: 1-800-555-0117
Meridian Mutual Health`,
  },
  {
    id: 'out-of-network',
    label: 'Specialist visit — out of network',
    reason: 'out_of_network',
    text: `NORTHRIDGE PREFERRED HEALTH
Member Services

Date: April 3, 2026

Member: Maria Alvarez
Member ID: NPH-7710-44231
Claim: CLM-2026-77198

RE: NOTICE OF NON-COVERAGE — OUT OF NETWORK PROVIDER

We have reviewed your request for prior authorization for a consultation
with Dr. K. Patel (Tax ID 84-2210099) on May 6, 2026.

REASON FOR DENIAL:
Dr. Patel is not a participating provider in the Northridge Preferred
network. Your plan covers specialist care only when delivered by an
in-network provider, except in cases of emergency or when no in-network
provider is reasonably available within 50 miles for the specialty in
question.

If you believe an exception applies (no in-network provider with the
required subspecialty within network adequacy distance, or continuity of
care for an active treatment plan), you may request a network exception
along with a written statement from your PCP.

APPEAL DEADLINE: May 30, 2026.

Sincerely,
Network Management, Northridge Preferred Health`,
  },
  {
    id: 'experimental',
    label: 'Cardiac procedure — experimental/investigational',
    reason: 'experimental_treatment',
    text: `CASCADE UNITED HEALTH
Medical Policy & Review

Date: April 15, 2026

RE: AUTHORIZATION DETERMINATION
Member: David Park
Member ID: CUH-118-9920334
Claim: CLM-2026-58811
Procedure Requested: 33999 - Unlisted procedure, cardiac surgery
                    (left atrial appendage closure with novel hybrid device)
Diagnosis: I48.91 - Unspecified atrial fibrillation

DETERMINATION: DENIED — EXPERIMENTAL/INVESTIGATIONAL

Cascade United Health's medical policy classifies the requested device-based
procedure as investigational at this time. The device referenced in the
authorization request does not have FDA approval for the indication
submitted, and peer-reviewed evidence does not yet establish improved
clinical outcomes versus standard-of-care anticoagulation or FDA-approved
LAA closure devices for this indication.

If the treating physician believes published evidence has changed since
the policy review, the appeal should include:
  - Citation to peer-reviewed studies (RCTs preferred)
  - Documentation of the member's contraindication to anticoagulation
  - Evidence that no FDA-approved alternative is clinically appropriate

APPEAL: 180 days from the date of this notice.

Cascade United Health Medical Review`,
  },
  {
    id: 'missing-info',
    label: 'Imaging — missing clinical information',
    reason: 'missing_information',
    text: `HARBOR POINT INSURANCE
Utilization Management

Date: April 9, 2026

Member: Sarah Williams
Member ID: HP-22-7710334
Claim: AUTH-2026-30119
Procedure Requested: 70553 - MRI brain with and without contrast
Diagnosis: G43.909 - Migraine, unspecified, not intractable, without status migrainosus

DETERMINATION: DENIED — INSUFFICIENT CLINICAL INFORMATION

Your request cannot be approved as submitted because the documentation
provided does not include the information needed to complete medical
necessity review. Specifically, we did not receive:

  1. Recent neurological examination notes
  2. Documented trial and response to first-line migraine prophylaxis
  3. Description of red-flag symptoms warranting advanced imaging
     (sudden onset, focal deficit, post-trauma, etc.)

You may resubmit with the missing information at no penalty. If the
treating provider believes the documentation already submitted is
sufficient, please appeal in writing within 60 days, including any
additional clinical context.

Harbor Point Insurance — Utilization Management`,
  },
];
