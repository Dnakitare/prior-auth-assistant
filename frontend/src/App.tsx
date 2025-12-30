import { useState } from 'react';
import { FileUpload } from './components/FileUpload';
import { PatientContextForm, PatientContext } from './components/PatientContextForm';
import { AppealPreview } from './components/AppealPreview';
import { TextInputMode } from './components/TextInputMode';
import { generateAppealFromDocument, generateAppealFromText } from './api';
import { AppealResponse } from './types';

type InputMode = 'upload' | 'text';

function App() {
  const [inputMode, setInputMode] = useState<InputMode>('upload');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [patientContext, setPatientContext] = useState<PatientContext | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [appeal, setAppeal] = useState<AppealResponse | null>(null);

  const handleFileSelect = (file: File) => {
    setSelectedFile(file);
    setError(null);
  };

  const handleContextChange = (context: PatientContext) => {
    setPatientContext(context);
  };

  const handleGenerateFromFile = async () => {
    if (!selectedFile) return;

    setIsLoading(true);
    setError(null);

    try {
      const result = await generateAppealFromDocument(selectedFile, patientContext || undefined);
      setAppeal(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate appeal');
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
      setError(err instanceof Error ? err.message : 'Failed to generate appeal');
    } finally {
      setIsLoading(false);
    }
  };

  const handleReset = () => {
    setSelectedFile(null);
    setPatientContext(null);
    setAppeal(null);
    setError(null);
  };

  // Show appeal preview if we have a result
  if (appeal) {
    return (
      <div className="min-h-screen bg-gray-50 py-8">
        <div className="max-w-4xl mx-auto px-4">
          <AppealPreview appeal={appeal} onReset={handleReset} />
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 py-8">
      <div className="max-w-3xl mx-auto px-4">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-gray-900 mb-2">
            Prior Authorization Assistant
          </h1>
          <p className="text-gray-600">
            Upload a denial letter or paste the text to generate an appeal
          </p>
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
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
            <div className="flex items-center gap-2">
              <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                <path
                  fillRule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                  clipRule="evenodd"
                />
              </svg>
              <span>{error}</span>
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
