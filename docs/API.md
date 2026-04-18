# Prior Authorization Assistant API Documentation

## Base URL

- Development: `http://localhost:8000`
- Production: `https://api.yourdomai.com`

## Authentication

All `/api/v1/*` endpoints require authentication. Two methods are supported:

### API Key Authentication

Include your API key in the `X-API-Key` header:

```bash
curl -H "X-API-Key: your-api-key" https://api.example.com/api/v1/appeals/text
```

### JWT Token Authentication

Include a Bearer token in the `Authorization` header:

```bash
curl -H "Authorization: Bearer your-jwt-token" https://api.example.com/api/v1/appeals/text
```

## Rate Limiting

- Default: 100 requests per minute per IP
- Headers returned:
  - `X-RateLimit-Limit`: Maximum requests allowed
  - `X-RateLimit-Remaining`: Requests remaining in window
  - `X-RateLimit-Reset`: Unix timestamp when limit resets

## Endpoints

---

### Health Checks

#### GET /health

Comprehensive health check for all dependencies.

**Response 200:**
```json
{
  "status": "healthy",
  "timestamp": "2024-12-29T10:00:00Z",
  "version": "1.0.0",
  "environment": "production",
  "components": [
    {
      "name": "database",
      "status": "healthy",
      "latency_ms": 5.2
    },
    {
      "name": "redis",
      "status": "healthy",
      "latency_ms": 1.1
    },
    {
      "name": "llm",
      "status": "healthy",
      "message": "API key configured"
    },
    {
      "name": "ocr",
      "status": "healthy",
      "message": "AWS Textract configured"
    }
  ]
}
```

#### GET /health/live

Kubernetes liveness probe.

**Response 200:**
```json
{
  "status": "alive"
}
```

#### GET /health/ready

Kubernetes readiness probe.

**Response 200:**
```json
{
  "status": "ready"
}
```

**Response 503:** Service not ready (database or LLM unavailable)

---

### Appeals

#### POST /api/v1/appeals/upload

Generate an appeal letter from an uploaded denial document.

**Request:**
- Content-Type: `multipart/form-data`
- Authentication: Required

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| denial_letter | File | Yes | PDF, PNG, JPEG, or TIFF (max 10MB) |
| patient_name | string | No | Patient's full name |
| procedure_code | string | No | CPT/HCPCS code |
| procedure_description | string | No | Description of procedure |
| diagnosis_codes | string | No | Comma-separated ICD-10 codes |
| clinical_notes | string | No | Relevant clinical notes |
| prior_treatments | string | No | Comma-separated prior treatments |
| treating_physician | string | No | Physician name |

**Example:**
```bash
curl -X POST \
  -H "X-API-Key: your-api-key" \
  -F "denial_letter=@denial.pdf" \
  -F "patient_name=John Doe" \
  -F "diagnosis_codes=M54.5,G89.29" \
  https://api.example.com/api/v1/appeals/upload
```

**Response 200:**
```json
{
  "appeal_id": "550e8400-e29b-41d4-a716-446655440000",
  "appeal_letter": "Dear Sir/Madam,\n\nI am writing to appeal...",
  "denial_info": {
    "payer_name": "Blue Cross Blue Shield",
    "denial_date": "2024-12-01T00:00:00Z",
    "denial_reason": "medical_necessity",
    "denial_reason_text": "Does not meet medical necessity criteria",
    "procedure_codes": ["99213"],
    "diagnosis_codes": ["M54.5"],
    "member_id": "MEM123456",
    "claim_number": "CLM987654",
    "appeal_deadline": "2025-06-01T00:00:00Z"
  },
  "required_documents": [
    "Letter of medical necessity from treating physician",
    "Clinical notes from past 12 months",
    "Lab results and imaging reports"
  ],
  "confidence_score": 0.85,
  "created_at": "2024-12-29T10:00:00Z",
  "warnings": []
}
```

**Error Responses:**

| Status | Description |
|--------|-------------|
| 400 | Invalid file type or size |
| 401 | Authentication required |
| 422 | Could not extract text from document |
| 429 | Rate limit exceeded |
| 503 | AI service unavailable |

---

#### POST /api/v1/appeals/text

Generate an appeal letter from denial text.

**Request:**
- Content-Type: `application/json`
- Authentication: Required

```json
{
  "denial_text": "Full text of the denial letter (50-100000 chars)",
  "patient_name": "John Doe",
  "procedure_code": "99213",
  "procedure_description": "Office visit",
  "diagnosis_codes": ["M54.5", "G89.29"],
  "clinical_notes": "Patient presents with chronic pain...",
  "prior_treatments": ["Physical therapy", "NSAIDs"],
  "treating_physician": "Dr. Jane Smith"
}
```

**Example:**
```bash
curl -X POST \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"denial_text": "Your claim has been denied..."}' \
  https://api.example.com/api/v1/appeals/text
```

**Response:** Same as `/appeals/upload`

---

#### GET /api/v1/appeals/{appeal_id}

Retrieve a previously generated appeal.

**Parameters:**
- `appeal_id`: UUID of the appeal

**Example:**
```bash
curl -H "X-API-Key: your-api-key" \
  https://api.example.com/api/v1/appeals/550e8400-e29b-41d4-a716-446655440000
```

**Response 200:** Same structure as appeal creation response

**Response 404:** Appeal not found

---

### Payers

#### GET /api/v1/payers

List all configured payers.

**Response 200:**
```json
{
  "payers": [
    {
      "id": "payer-uuid",
      "name": "Blue Cross Blue Shield",
      "aliases": ["BCBS", "Blue Cross"],
      "appeals_phone": "1-800-555-0100",
      "appeal_deadline_days": 180
    }
  ]
}
```

#### GET /api/v1/payers/{payer_id}

Get detailed payer information.

**Response 200:**
```json
{
  "id": "payer-uuid",
  "name": "Blue Cross Blue Shield",
  "aliases": ["BCBS", "Blue Cross"],
  "appeals_phone": "1-800-555-0100",
  "appeals_fax": "1-800-555-0101",
  "appeals_address": "P.O. Box 12345...",
  "appeal_deadline_days": 180,
  "expedited_review_available": true,
  "medical_necessity_requirements": {
    "required_docs": [
      "Letter of medical necessity",
      "Clinical notes"
    ],
    "tips": [
      "Reference clinical policy bulletins"
    ]
  }
}
```

---

## Error Response Format

All errors return a consistent format:

```json
{
  "detail": "Human-readable error message",
  "error_code": "ERROR_CODE"  // Optional
}
```

## Common Error Codes

| Code | Status | Description |
|------|--------|-------------|
| AUTH_REQUIRED | 401 | Authentication required |
| INVALID_TOKEN | 401 | Invalid or expired token |
| FORBIDDEN | 403 | Insufficient permissions |
| NOT_FOUND | 404 | Resource not found |
| VALIDATION_ERROR | 422 | Invalid request data |
| RATE_LIMITED | 429 | Too many requests |
| SERVICE_UNAVAILABLE | 503 | External service down |

## Webhook Events (Future)

Coming soon: webhook notifications for appeal status changes.

## SDK Examples

### Python

```python
import httpx

client = httpx.Client(
    base_url="https://api.example.com",
    headers={"X-API-Key": "your-api-key"}
)

# Generate appeal from text
response = client.post("/api/v1/appeals/text", json={
    "denial_text": "Your claim has been denied..."
})
appeal = response.json()
print(appeal["appeal_letter"])
```

### JavaScript/TypeScript

```typescript
const response = await fetch("https://api.example.com/api/v1/appeals/text", {
  method: "POST",
  headers: {
    "X-API-Key": "your-api-key",
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    denial_text: "Your claim has been denied..."
  })
});
const appeal = await response.json();
console.log(appeal.appeal_letter);
```
