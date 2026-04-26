import { useState } from 'react';
import { sampleDenials } from '../data/sampleDenials';

interface TextInputModeProps {
  onSubmit: (text: string) => void;
  disabled?: boolean;
}

export function TextInputMode({ onSubmit, disabled }: TextInputModeProps) {
  const [denialText, setDenialText] = useState('');

  const handleSubmit = () => {
    if (denialText.trim().length >= 50) {
      onSubmit(denialText);
    }
  };

  return (
    <div className="card">
      <h3 className="font-semibold text-gray-900 mb-2">Paste Denial Letter Text</h3>
      <p className="text-sm text-gray-500 mb-3">
        Paste the text content from your denial letter below, or load a synthetic sample.
      </p>

      <div className="flex flex-wrap gap-2 mb-4" aria-label="Sample denial letters">
        <span className="text-xs uppercase tracking-wide text-gray-500 self-center mr-1">
          Try a sample:
        </span>
        {sampleDenials.map((sample) => (
          <button
            key={sample.id}
            type="button"
            onClick={() => setDenialText(sample.text)}
            disabled={disabled}
            className="text-xs px-3 py-1 rounded-full border border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 disabled:opacity-50 transition-colors"
            title={sample.reason}
          >
            {sample.label}
          </button>
        ))}
      </div>

      <textarea
        className="textarea-field min-h-[200px]"
        placeholder="Paste the denial letter text here..."
        value={denialText}
        onChange={(e) => setDenialText(e.target.value)}
        disabled={disabled}
      />
      <div className="flex items-center justify-between mt-4">
        <span className="text-sm text-gray-500">
          {denialText.length} characters (minimum 50)
        </span>
        <button
          onClick={handleSubmit}
          disabled={disabled || denialText.trim().length < 50}
          className="btn-primary"
        >
          Generate Appeal
        </button>
      </div>
    </div>
  );
}
