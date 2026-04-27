import { useState, useCallback } from 'react';
import { FileUpload } from './components/FileUpload';
import { PatientContextForm, PatientContext } from './components/PatientContextForm';
import { AppealPreview } from './components/AppealPreview';
import { TextInputMode } from './components/TextInputMode';
import { BYOKSettings } from './components/BYOKSettings';
import {
  generateAppealFromDocument,
  generateAppealFromText,
  ApiError,
  AuthenticationError,
  BudgetExhaustedError,
  RateLimitError,
  ValidationError,
} from './api';
import { AppealResponse } from './types';

type InputMode = 'upload' | 'text';

interface ErrorState {
  message: string;
  type: 'error' | 'warning' | 'auth' | 'rate_limit' | 'budget_exhausted';
  retryAfter?: number;
}

function App() {
  const [inputMode, setInputMode] = useState<InputMode>('upload');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [patientContext, setPatientContext] = useState<PatientContext | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<ErrorState | null>(null);
  const [appeal, setAppeal] = useState<AppealResponse | null>(null);

  const handleError = useCallback((err: unknown): void => {
    if (err instanceof AuthenticationError) {
      setError({
        message: 'Authentication required. Please provide an API key.',
        type: 'auth',
      });
    } else if (err instanceof RateLimitError) {
      setError({
        message: err.message,
        type: 'rate_limit',
        retryAfter: err.retryAfter,
      });
    } else if (err instanceof BudgetExhaustedError) {
      setError({
        message: err.message,
        type: 'budget_exhausted',
      });
    } else if (err instanceof ValidationError) {
      setError({
        message: err.message,
        type: 'warning',
      });
    } else if (err instanceof ApiError) {
      setError({
        message: err.message,
        type: 'error',
      });
    } else {
      setError({
        message: err instanceof Error ? err.message : 'An unexpected error occurred',
        type: 'error',
      });
    }
  }, []);

  const handleFileSelect = useCallback((file: File) => {
    setSelectedFile(file);
    setError(null);
  }, []);

  const handleContextChange = useCallback((context: PatientContext) => {
    setPatientContext(context);
  }, []);

  const handleGenerateFromFile = async () => {
    if (!selectedFile) return;

    setIsLoading(true);
    setError(null);

    try {
      const result = await generateAppealFromDocument(selectedFile, patientContext || undefined);
      setAppeal(result);
    } catch (err) {
      handleError(err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleGenerateFromText = async (text: string) => {
    setIsLoading(true);
    setError(null);

    try {
      const request = {
        denial_text: text,
        ...(patientContext && {
          patient_name: patientContext.patient_name || undefined,
          procedure_code: patientContext.procedure_code || undefined,
          procedure_description: patientContext.procedure_description || undefined,
          diagnosis_codes: patientContext.diagnosis_codes
            ? patientContext.diagnosis_codes.split(',').map((c) => c.trim())
            : undefined,
          clinical_notes: patientContext.clinical_notes || undefined,
          prior_treatments: patientContext.prior_treatments
            ? patientContext.prior_treatments.split(',').map((t) => t.trim())
            : undefined,
          treating_physician: patientContext.treating_physician || undefined,
        }),
      };
      const result = await generateAppealFromText(request);
      setAppeal(result);
    } catch (err) {
      handleError(err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleReset = useCallback(() => {
    setSelectedFile(null);
    setPatientContext(null);
    setAppeal(null);
    setError(null);
  }, []);

  const demoBanner = (
    <div
      role="note"
      className="bg-amber-50 border-b border-amber-200 text-amber-900"
    >
      <div className="max-w-4xl mx-auto px-4 py-3 flex items-start gap-3 text-sm">
        <svg className="w-5 h-5 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
          <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
        </svg>
        <div>
          <p className="font-semibold">Public demo — do not submit real PHI.</p>
          <p className="text-amber-800">
            This deployment is a portfolio reference architecture. Use the synthetic
            samples in &quot;Paste Text&quot; mode. Submitted text is processed by Claude
            and persisted in the demo database.
          </p>
        </div>
      </div>
    </div>
  );

  // Show appeal preview if we have a result
  if (appeal) {
    return (
      <div className="min-h-screen bg-gray-50">
        {demoBanner}
        <div className="max-w-4xl mx-auto px-4 py-8">
          <AppealPreview appeal={appeal} onReset={handleReset} />
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {demoBanner}
      <div className="max-w-3xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="flex items-start justify-between mb-8">
          <div className="flex-1 text-center">
            <h1 className="text-3xl font-bold text-gray-900 mb-2">
              Prior Authorization Assistant
            </h1>
            <p className="text-gray-600">
              Upload a denial letter or paste the text to generate an appeal
            </p>
          </div>
          <div className="flex-shrink-0 ml-4 mt-1">
            <BYOKSettings />
          </div>
        </div>

        {/* Input Mode Toggle */}
        <div className="flex justify-center mb-6">
          <div className="inline-flex rounded-lg border border-gray-200 bg-white p-1">
            <button
              onClick={() => setInputMode('upload')}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                inputMode === 'upload'
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
              disabled={isLoading}
            >
              Upload Document
            </button>
            <button
              onClick={() => setInputMode('text')}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                inputMode === 'text'
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
              disabled={isLoading}
            >
              Paste Text
            </button>
          </div>
        </div>

        {/* Error Display */}
        {error && (
          <div
            role="alert"
            aria-live="assertive"
            className={`mb-6 p-4 rounded-lg border ${
              error.type === 'auth'
                ? 'bg-purple-50 border-purple-200 text-purple-700'
                : error.type === 'rate_limit'
                ? 'bg-orange-50 border-orange-200 text-orange-700'
                : error.type === 'budget_exhausted'
                ? 'bg-amber-50 border-amber-200 text-amber-800'
                : error.type === 'warning'
                ? 'bg-yellow-50 border-yellow-200 text-yellow-700'
                : 'bg-red-50 border-red-200 text-red-700'
            }`}
          >
            <div className="flex items-start gap-3">
              {error.type === 'auth' ? (
                <svg className="w-5 h-5 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
                  <path fillRule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clipRule="evenodd" />
                </svg>
              ) : error.type === 'rate_limit' ? (
                <svg className="w-5 h-5 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd" />
                </svg>
              ) : error.type === 'warning' ? (
                <svg className="w-5 h-5 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
                  <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
              ) : (
                <svg className="w-5 h-5 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                </svg>
              )}
              <div className="flex-1">
                <p className="font-medium">
                  {error.type === 'budget_exhausted' ? "Demo's LLM budget exhausted" : error.message}
                </p>
                {error.type === 'rate_limit' && error.retryAfter && (
                  <p className="text-sm mt-1">Please try again in {error.retryAfter} seconds.</p>
                )}
                {error.type === 'rate_limit' && !error.retryAfter && (
                  <p className="text-sm mt-1">Please wait a few seconds and try again.</p>
                )}
                {error.type === 'auth' && (
                  <p className="text-sm mt-1">Contact your administrator to obtain API credentials.</p>
                )}
                {error.type === 'budget_exhausted' && (
                  <p className="text-sm mt-1">
                    The shared Anthropic budget for this public demo has been hit for the
                    period. Try again later, or supply your own Anthropic API key in the
                    settings menu (BYOK) to keep using the demo on your own credits.
                  </p>
                )}
              </div>
              <button
                onClick={() => setError(null)}
                className="flex-shrink-0 ml-2 hover:opacity-70 transition-opacity"
                aria-label="Dismiss error"
              >
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
                  <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                </svg>
              </button>
            </div>
          </div>
        )}

        <div className="space-y-6">
          {/* File Upload or Text Input */}
          {inputMode === 'upload' ? (
            <>
              <FileUpload
                onFileSelect={handleFileSelect}
                selectedFile={selectedFile}
                disabled={isLoading}
              />

              {/* Patient Context */}
              <PatientContextForm
                onContextChange={handleContextChange}
                disabled={isLoading}
              />

              {/* Generate Button */}
              <button
                onClick={handleGenerateFromFile}
                disabled={!selectedFile || isLoading}
                className="w-full btn-primary py-3 text-lg"
              >
                {isLoading ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg
                      className="animate-spin h-5 w-5"
                      fill="none"
                      viewBox="0 0 24 24"
                    >
                      <circle
                        className="opacity-25"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="currentColor"
                        strokeWidth="4"
                      />
                      <path
                        className="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                      />
                    </svg>
                    Generating Appeal...
                  </span>
                ) : (
                  'Generate Appeal Letter'
                )}
              </button>
            </>
          ) : (
            <>
              <TextInputMode
                onSubmit={handleGenerateFromText}
                disabled={isLoading}
              />

              {/* Patient Context */}
              <PatientContextForm
                onContextChange={handleContextChange}
                disabled={isLoading}
              />

              {isLoading && (
                <div className="flex items-center justify-center py-4">
                  <svg
                    className="animate-spin h-8 w-8 text-blue-600"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    />
                  </svg>
                  <span className="ml-2 text-gray-600">Generating appeal...</span>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="mt-12 text-center text-sm text-gray-500">
          <p>
            This tool assists in generating prior authorization appeals. Always review
            generated content before submission.
          </p>
        </div>
      </div>
    </div>
  );
}

export default App;
