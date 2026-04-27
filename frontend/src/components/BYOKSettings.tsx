import { useEffect, useState } from 'react';
import { getByokKey, setByokKey } from '../api';

interface BYOKSettingsProps {
  onChange?: (active: boolean) => void;
}

export function BYOKSettings({ onChange }: BYOKSettingsProps) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [active, setActive] = useState<boolean>(false);

  // Hydrate from sessionStorage on mount.
  useEffect(() => {
    const existing = getByokKey();
    if (existing) {
      setDraft(existing);
      setActive(true);
    }
  }, []);

  const handleSave = () => {
    const trimmed = draft.trim();
    if (!trimmed) {
      setByokKey(null);
      setActive(false);
      onChange?.(false);
      setOpen(false);
      return;
    }
    if (!trimmed.startsWith('sk-ant-')) {
      // No alert spam — just refuse silently with input border.
      return;
    }
    setByokKey(trimmed);
    setActive(true);
    onChange?.(true);
    setOpen(false);
  };

  const handleClear = () => {
    setByokKey(null);
    setDraft('');
    setActive(false);
    onChange?.(false);
  };

  const masked = active && draft ? `…${draft.slice(-6)}` : null;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium transition-colors border ${
          active
            ? 'bg-emerald-50 border-emerald-200 text-emerald-800 hover:bg-emerald-100'
            : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
        }`}
        aria-expanded={open}
        aria-label={active ? `BYOK active, key ending ${masked}` : 'Configure BYOK'}
      >
        <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
          <path fillRule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clipRule="evenodd" />
        </svg>
        {active ? `BYOK active ${masked}` : 'Use my Anthropic key'}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-96 bg-white border border-gray-200 rounded-lg shadow-lg z-10 p-4 text-left">
          <h3 className="font-semibold text-gray-900 mb-1">Bring your own Anthropic key</h3>
          <p className="text-xs text-gray-500 mb-3">
            Sets <code>X-User-Anthropic-Key</code> on requests so this demo runs on your
            account instead of the shared budget. Stored in <strong>sessionStorage</strong>
            only — cleared when you close this tab. Never written to disk.
          </p>
          <input
            type="password"
            placeholder="sk-ant-…"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
            autoComplete="off"
            spellCheck={false}
          />
          <div className="flex items-center justify-between mt-3 gap-2">
            {active ? (
              <button
                onClick={handleClear}
                className="text-xs text-red-600 hover:text-red-800"
              >
                Stop using my key
              </button>
            ) : (
              <span className="text-xs text-gray-400">Key never leaves this tab.</span>
            )}
            <div className="flex gap-2">
              <button
                onClick={() => setOpen(false)}
                className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={!draft.trim() || !draft.trim().startsWith('sk-ant-')}
                className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
