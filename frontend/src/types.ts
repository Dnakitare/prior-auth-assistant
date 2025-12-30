export interface DenialExtraction {
  payer_name: string | null;
  denial_date: string | null;
  denial_reason: string;
  denial_reason_text: string | null;
  procedure_codes: string[];
  diagnosis_codes: string[];
  member_id: string | null;
  claim_number: string | null;
  appeal_deadline: string | null;
  raw_text: string;
}

export interface AppealResponse {
  appeal_id: string;
  appeal_letter: string;
  denial_info: DenialExtraction;
  required_documents: string[];
  confidence_score: number;
}

export interface TextAppealRequest {
  denial_text: string;
  patient_name?: string;
  procedure_code?: string;
  procedure_description?: string;
  diagnosis_codes?: string[];
  clinical_notes?: string;
  prior_treatments?: string[];
  treating_physician?: string;
}

export type DenialReasonType =
  | 'medical_necessity'
  | 'not_covered'
  | 'out_of_network'
  | 'missing_information'
  | 'experimental_treatment'
  | 'step_therapy_required'
  | 'quantity_limit'
  | 'prior_auth_required'
  | 'other';

export const DENIAL_REASON_LABELS: Record<DenialReasonType, string> = {
  medical_necessity: 'Medical Necessity',
  not_covered: 'Not Covered',
  out_of_network: 'Out of Network',
  missing_information: 'Missing Information',
  experimental_treatment: 'Experimental Treatment',
  step_therapy_required: 'Step Therapy Required',
  quantity_limit: 'Quantity Limit',
  prior_auth_required: 'Prior Authorization Required',
  other: 'Other',
};
