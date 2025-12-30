import { AppealResponse, DENIAL_REASON_LABELS, DenialReasonType } from '../types';

interface AppealPreviewProps {
  appeal: AppealResponse;
  onReset: () => void;
}

export function AppealPreview({ appeal, onReset }: AppealPreviewProps) {
  const handleCopy = async () => {
    await navigator.clipboard.writeText(appeal.appeal_letter);
    alert('Appeal letter copied to clipboard!');
  };

  const handleDownload = () => {
    const blob = new Blob([appeal.appeal_letter], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `appeal-${appeal.appeal_id}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const denialReasonLabel =
    DENIAL_REASON_LABELS[appeal.denial_info.denial_reason as DenialReasonType] ||
    appeal.denial_info.denial_reason;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Appeal Generated</h2>
          <p className="text-gray-500">ID: {appeal.appeal_id}</p>
        </div>
        <button onClick={onReset} className="btn-secondary">
          Generate Another
        </button>
      </div>

      {/* Extraction Summary */}
      <div className="card">
        <h3 className="font-semibold text-gray-900 mb-4">Denial Information Extracted</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
          <div>
            <span className="text-gray-500">Payer:</span>
            <p className="font-medium">{appeal.denial_info.payer_name || 'Not detected'}</p>
          </div>
          <div>
            <span className="text-gray-500">Denial Reason:</span>
            <p className="font-medium">{denialReasonLabel}</p>
          </div>
          <div>
            <span className="text-gray-500">Claim Number:</span>
            <p className="font-medium">{appeal.denial_info.claim_number || 'Not detected'}</p>
          </div>
          <div>
            <span className="text-gray-500">Member ID:</span>
            <p className="font-medium">{appeal.denial_info.member_id || 'Not detected'}</p>
          </div>
          <div>
            <span className="text-gray-500">Procedure Codes:</span>
            <p className="font-medium">
              {appeal.denial_info.procedure_codes.length > 0
                ? appeal.denial_info.procedure_codes.join(', ')
                : 'Not detected'}
            </p>
          </div>
          <div>
            <span className="text-gray-500">Diagnosis Codes:</span>
            <p className="font-medium">
              {appeal.denial_info.diagnosis_codes.length > 0
                ? appeal.denial_info.diagnosis_codes.join(', ')
                : 'Not detected'}
            </p>
          </div>
        </div>

        {/* Confidence Score */}
        <div className="mt-4 pt-4 border-t border-gray-200">
          <div className="flex items-center gap-2">
            <span className="text-gray-500 text-sm">Extraction Confidence:</span>
            <div className="flex-1 bg-gray-200 rounded-full h-2 max-w-xs">
              <div
                className={`h-2 rounded-full ${
                  appeal.confidence_score >= 0.7
                    ? 'bg-green-500'
                    : appeal.confidence_score >= 0.4
                    ? 'bg-yellow-500'
                    : 'bg-red-500'
                }`}
                style={{ width: `${appeal.confidence_score * 100}%` }}
              />
            </div>
            <span className="text-sm font-medium">
              {Math.round(appeal.confidence_score * 100)}%
            </span>
          </div>
        </div>
      </div>

      {/* Appeal Letter */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900">Generated Appeal Letter</h3>
          <div className="flex gap-2">
            <button onClick={handleCopy} className="btn-secondary text-sm">
              Copy to Clipboard
            </button>
            <button onClick={handleDownload} className="btn-primary text-sm">
              Download
            </button>
          </div>
        </div>
        <div className="bg-gray-50 rounded-lg p-4 max-h-[500px] overflow-y-auto">
          <pre className="whitespace-pre-wrap text-sm font-mono text-gray-800">
            {appeal.appeal_letter}
          </pre>
        </div>
      </div>

      {/* Required Documents */}
      <div className="card">
        <h3 className="font-semibold text-gray-900 mb-4">Required Supporting Documents</h3>
        <ul className="space-y-2">
          {appeal.required_documents.map((doc, index) => (
            <li key={index} className="flex items-start gap-2">
              <svg
                className="w-5 h-5 text-blue-500 mt-0.5 flex-shrink-0"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
              <span className="text-gray-700">{doc}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
