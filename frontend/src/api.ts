import axios, { AxiosError, AxiosInstance, InternalAxiosRequestConfig } from 'axios';
import { AppealResponse, TextAppealRequest } from './types';

// Fail loudly if a production build is missing the API origin: the silent
// fallback used to bake `http://localhost:8000` into deployed bundles, which
// would send requests (including BYOK keys) to whatever runs on the
// *visitor's* machine.
const API_BASE_URL =
  import.meta.env.VITE_API_URL ??
  (import.meta.env.DEV ? 'http://localhost:8000' : undefined);
if (!API_BASE_URL) {
  throw new Error('VITE_API_URL must be set for production builds');
}

// The shared demo key is intentionally public (see README "Try the demo");
// the demo tenant contains only synthetic data. Baking it in is what lets a
// visitor click "Generate" without any setup. setApiKey() overrides it.
const DEMO_API_KEY = 'pa_demo_publickey_safe_to_share_DEADBEEF';

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
let apiKey: string | null = import.meta.env.VITE_API_KEY ?? DEMO_API_KEY;

export function setAuthToken(token: string | null): void {
  authToken = token;
}

export function setApiKey(key: string | null): void {
  apiKey = key;
}

// --- BYOK (Bring Your Own Key) ---------------------------------------------
//
// The visitor may supply their own Anthropic key for this session so they
// don't share the demo's budget. The key lives in sessionStorage (cleared
// on tab close) and is sent on every request as X-User-Anthropic-Key. It
// is NEVER persisted to localStorage and the backend never logs the value.

const BYOK_STORAGE_KEY = 'pa_byok_anthropic_key';

export function getByokKey(): string | null {
  try {
    return sessionStorage.getItem(BYOK_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setByokKey(key: string | null): void {
  try {
    if (key) {
      sessionStorage.setItem(BYOK_STORAGE_KEY, key);
    } else {
      sessionStorage.removeItem(BYOK_STORAGE_KEY);
    }
  } catch {
    /* sessionStorage disabled — silently ignore */
  }
}

// FastAPI validation errors (422) arrive as an array of these.
interface FastApiValidationItem {
  loc?: Array<string | number>;
  msg?: string;
}

function flattenDetail(
  detail: string | FastApiValidationItem[] | undefined
): string | undefined {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const field = item.loc?.slice(1).join('.'); // drop "body"
        return field ? `${field}: ${item.msg}` : item.msg ?? '';
      })
      .filter(Boolean)
      .join('; ');
  }
  return undefined;
}

// Create axios instance
const api: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000, // LLM pipeline (OCR + extract + generate) can exceed 60s
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

    // BYOK: forward the visitor's own Anthropic key when set — but only on
    // the endpoints that spend LLM tokens. Health checks and other calls
    // don't need it, so don't widen the key's exposure surface.
    const byok = getByokKey();
    if (byok && config.url?.startsWith('/api/v1/appeals')) {
      config.headers['X-User-Anthropic-Key'] = byok;
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
  (error: AxiosError<{ detail?: string | FastApiValidationItem[]; error_code?: string }>) => {
    if (!error.response) {
      if (error.code === 'ECONNABORTED') {
        // Axios timeout, not a connectivity problem — generation is slow.
        throw new ApiError(
          'The request timed out. Appeal generation can take a minute or two; please try again.',
          0,
          'TIMEOUT'
        );
      }
      throw new ApiError(
        'Network error. Please check your connection.',
        0,
        'NETWORK_ERROR'
      );
    }

    const { status, data, headers } = error.response;
    // FastAPI 422s put an *array* of error objects in `detail`; rendering
    // that as a React child crashes the app, so flatten it to a string.
    const message = flattenDetail(data?.detail) || error.message || 'An error occurred';

    switch (status) {
      case 401:
        throw new AuthenticationError(message);
      case 429: {
        const retryAfter = headers['retry-after']
          ? parseInt(headers['retry-after'], 10)
          : undefined;
        throw new RateLimitError(message, retryAfter);
      }
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
