import { useState } from 'react';

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
      <p className="text-sm text-gray-500 mb-4">
        Paste the text content from your denial letter below
      </p>
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
