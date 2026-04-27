import axios, { AxiosError, AxiosInstance, InternalAxiosRequestConfig } from 'axios';
import { AppealResponse, TextAppealRequest } from './types';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// API error types for better error handling
export class ApiError extends Error {
  constructor(
    message: string,
    public statusCode: number,
    public errorCode?: string
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export class AuthenticationError extends ApiError {
  constructor(message: string = 'Authentication required') {
    super(message, 401, 'AUTH_REQUIRED');
    this.name = 'AuthenticationError';
  }
}

export class RateLimitError extends ApiError {
  constructor(
    message: string = 'Rate limit exceeded',
    public retryAfter?: number
  ) {
    super(message, 429, 'RATE_LIMITED');
    this.name = 'RateLimitError';
  }
}

export class BudgetExhaustedError extends ApiError {
  constructor(message: string) {
    super(message, 503, 'BUDGET_EXHAUSTED');
    this.name = 'BudgetExhaustedError';
  }
}

export class ValidationError extends ApiError {
  constructor(message: string, public details?: Record<string, string[]>) {
    super(message, 400, 'VALIDATION_ERROR');
    this.name = 'ValidationError';
  }
}

// Auth token storage
let authToken: string | null = null;
let apiKey: string | null = null;

export function setAuthToken(token: string | null): void {
  authToken = token;
}

export function setApiKey(key: string | null): void {
  apiKey = key;
}

// Create axios instance
const api: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60000, // 60 second timeout for LLM operations
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor - add auth headers
api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // Add API key if available
    if (apiKey) {
      config.headers['X-API-Key'] = apiKey;
    }

    // Add JWT token if available
    if (authToken) {
      config.headers['Authorization'] = `Bearer ${authToken}`;
    }

    // Add request ID for tracing
    config.headers['X-Request-ID'] = crypto.randomUUID();

    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor - handle errors
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ detail?: string; error_code?: string }>) => {
    if (!error.response) {
      // Network error
      throw new ApiError(
        'Network error. Please check your connection.',
        0,
        'NETWORK_ERROR'
      );
    }

    const { status, data, headers } = error.response;
    const message = data?.detail || error.message || 'An error occurred';

    switch (status) {
      case 401:
        throw new AuthenticationError(message);
      case 429:
        const retryAfter = headers['retry-after']
          ? parseInt(headers['retry-after'], 10)
          : undefined;
        throw new RateLimitError(message, retryAfter);
      case 400:
      case 422:
        throw new ValidationError(message);
      case 503: {
        // Backend signals budget cap via X-Error-Code header so the frontend
        // can offer the BYOK path instead of a generic "try again later".
        const errorCode = headers['x-error-code'] || data?.error_code;
        if (errorCode === 'BUDGET_EXHAUSTED') {
          throw new BudgetExhaustedError(message);
        }
        throw new ApiError(
          'Service temporarily unavailable. Please try again later.',
          503,
          'SERVICE_UNAVAILABLE'
        );
      }
      default:
        throw new ApiError(message, status, data?.error_code);
    }
  }
);

// The server dedupes on (org_id, idempotency_key). Callers that want a
// **retry** (same logical submission) MUST pass the same key explicitly
// as the second argument; the default generator produces a new key per
// call, which is correct for user-initiated re-submissions (a different
// appeal) but wrong for network-level retries of a single attempt.
function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

export async function generateAppealFromText(
  request: TextAppealRequest,
  idempotencyKey: string = newIdempotencyKey()
): Promise<AppealResponse> {
  const response = await api.post<AppealResponse>('/api/v1/appeals/text', request, {
    headers: { 'Idempotency-Key': idempotencyKey },
  });
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
  },
  idempotencyKey: string = newIdempotencyKey()
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
      'Idempotency-Key': idempotencyKey,
    },
  });
  return response.data;
}

export interface HealthResponse {
  status: 'healthy' | 'degraded' | 'unhealthy';
  timestamp: string;
  version: string;
  environment: string;
  components: Array<{
    name: string;
    status: 'healthy' | 'degraded' | 'unhealthy';
    latency_ms?: number;
    message?: string;
  }>;
}

export async function checkHealth(): Promise<HealthResponse> {
  const response = await api.get<HealthResponse>('/health');
  return response.data;
}

export async function checkReadiness(): Promise<{ status: string }> {
  const response = await api.get<{ status: string }>('/health/ready');
  return response.data;
}

// Export the api instance for direct use if needed
export { api };
