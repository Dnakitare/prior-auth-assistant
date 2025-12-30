import { useState } from 'react';

export interface PatientContext {
  patient_name: string;
  procedure_code: string;
  procedure_description: string;
  diagnosis_codes: string;
  clinical_notes: string;
  prior_treatments: string;
  treating_physician: string;
}

interface PatientContextFormProps {
  onContextChange: (context: PatientContext) => void;
  disabled?: boolean;
}

export function PatientContextForm({ onContextChange, disabled }: PatientContextFormProps) {
  const [context, setContext] = useState<PatientContext>({
    patient_name: '',
    procedure_code: '',
    procedure_description: '',
    diagnosis_codes: '',
    clinical_notes: '',
    prior_treatments: '',
    treating_physician: '',
  });

  const [isExpanded, setIsExpanded] = useState(false);

  const handleChange = (field: keyof PatientContext, value: string) => {
    const newContext = { ...context, [field]: value };
    setContext(newContext);
    onContextChange(newContext);
  };

  return (
    <div className="card">
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between text-left"
        disabled={disabled}
      >
        <div>
          <h3 className="font-semibold text-gray-900">Patient Context</h3>
          <p className="text-sm text-gray-500">
            Optional: Add patient details for a more tailored appeal
          </p>
        </div>
        <svg
          className={`w-5 h-5 text-gray-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isExpanded && (
        <div className="mt-4 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="label">Patient Name</label>
              <input
                type="text"
                className="input-field"
                placeholder="John Smith"
                value={context.patient_name}
                onChange={(e) => handleChange('patient_name', e.target.value)}
                disabled={disabled}
              />
            </div>
            <div>
              <label className="label">Treating Physician</label>
              <input
                type="text"
                className="input-field"
                placeholder="Dr. Jane Doe"
                value={context.treating_physician}
                onChange={(e) => handleChange('treating_physician', e.target.value)}
                disabled={disabled}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="label">Procedure Code (CPT)</label>
              <input
                type="text"
                className="input-field"
                placeholder="27447"
                value={context.procedure_code}
                onChange={(e) => handleChange('procedure_code', e.target.value)}
                disabled={disabled}
              />
            </div>
            <div>
              <label className="label">Diagnosis Codes (ICD-10)</label>
              <input
                type="text"
                className="input-field"
                placeholder="M17.11, M17.12"
                value={context.diagnosis_codes}
                onChange={(e) => handleChange('diagnosis_codes', e.target.value)}
                disabled={disabled}
              />
            </div>
          </div>

          <div>
            <label className="label">Procedure Description</label>
            <input
              type="text"
              className="input-field"
              placeholder="Total Knee Arthroplasty"
              value={context.procedure_description}
              onChange={(e) => handleChange('procedure_description', e.target.value)}
              disabled={disabled}
            />
          </div>

          <div>
            <label className="label">Prior Treatments</label>
            <textarea
              className="textarea-field"
              placeholder="Physical therapy x 12 sessions, NSAIDs, Cortisone injections..."
              value={context.prior_treatments}
              onChange={(e) => handleChange('prior_treatments', e.target.value)}
              disabled={disabled}
            />
          </div>

          <div>
            <label className="label">Clinical Notes</label>
            <textarea
              className="textarea-field"
              placeholder="Patient has been experiencing chronic knee pain for 2 years..."
              value={context.clinical_notes}
              onChange={(e) => handleChange('clinical_notes', e.target.value)}
              disabled={disabled}
            />
          </div>
        </div>
      )}
    </div>
  );
}
