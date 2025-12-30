import axios from 'axios';
import { AppealResponse, TextAppealRequest } from './types';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export async function generateAppealFromText(
  request: TextAppealRequest
): Promise<AppealResponse> {
  const response = await api.post<AppealResponse>('/api/v1/appeals/text', request);
  return response.data;
}

export async function generateAppealFromDocument(
  file: File,
  patientContext?: {
    patient_name?: string;
    procedure_code?: string;
    procedure_description?: string;
    diagnosis_codes?: string;
    clinical_notes?: string;
    prior_treatments?: string;
    treating_physician?: string;
  }
): Promise<AppealResponse> {
  const formData = new FormData();
  formData.append('denial_letter', file);

  if (patientContext) {
    Object.entries(patientContext).forEach(([key, value]) => {
      if (value) {
        formData.append(key, value);
      }
    });
  }

  const response = await api.post<AppealResponse>('/api/v1/appeals/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
}

export async function checkHealth(): Promise<{ status: string }> {
  const response = await api.get<{ status: string }>('/health');
  return response.data;
}
