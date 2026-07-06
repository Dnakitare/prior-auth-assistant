# API Reference

HTTP API for the Prior Authorization Assistant. This documents what the code
actually serves (see `src/api/routes/` and `src/api/main.py`); when in doubt,
the code wins.

## Base URL

- Live demo: `https://prior-auth-assistant-production.up.railway.app`
- Or your own deployment origin (`http://localhost:8000` in development).

The demo runs against synthetic data only. Do not submit real PHI. The demo
API key below is intentionally public and belongs to a synthetic-data tenant:

```
pa_demo_publickey_safe_to_share_DEADBEEF
```

Interactive docs (`/docs`, `/redoc`, `/openapi.json`) are enabled in
development only.

## Authentication

Two methods, interchangeable on all authenticated endpoints:

| Method | Header | Notes |
|---|---|---|
| API key | `X-API-Key: <key>` | Keys are stored hashed server-side; scopes: `appeals:read`, `appeals:write`, `admin` |
| JWT | `Authorization: Bearer <token>` | Short-lived; minted from an API key via `POST /api/v1/auth/token`; revocable via logout |

Authenticated endpoints also require the principal to belong to an
organization; a principal with no `org_id` gets `403` on appeal routes.

## Endpoint summary

| Method | Path | Auth |
|---|---|---|
| POST | `/api/v1/auth/token` | API key |
| POST | `/api/v1/auth/logout` | JWT |
| POST | `/api/v1/appeals/upload` | API key / JWT |
| POST | `/api/v1/appeals/text` | API key / JWT |
| GET | `/api/v1/appeals/{appeal_id}` | API key / JWT |
| PATCH | `/api/v1/appeals/{appeal_id}/status` | API key / JWT |
| GET | `/api/v1/payers` | None |
| GET | `/api/v1/payers/{payer_name}/requirements` | None |
| POST | `/api/v1/admin/api-keys` | `admin` scope |
| GET | `/api/v1/admin/api-keys` | `admin` scope |
| DELETE | `/api/v1/admin/api-keys/{key_id}` | `admin` scope |
| POST | `/api/v1/admin/webhooks` | `admin` scope |
| GET | `/api/v1/admin/webhooks` | `admin` scope |
| DELETE | `/api/v1/admin/webhooks/{webhook_id}` | `admin` scope |
| GET | `/health` | None |
| GET | `/health/live` | None |
| GET | `/health/ready` | None |
| GET | `/metrics` | None (network-restricted; see below) |

## Common headers

| Header | Direction | Meaning |
|---|---|---|
| `Idempotency-Key` | request (optional, max 128 chars) | On `POST /appeals/upload` and `/appeals/text`. If an appeal already exists for (your org, this key), the existing row is returned instead of a duplicate being created. Retry failed requests with the same key. |
| `X-User-Anthropic-Key` | request (optional) | BYOK: an `sk-ant-...` key. The LLM/OCR calls run on your Anthropic account instead of the platform key, and your request skips the platform's per-org token budget. Malformed values get `400`. Never cached or logged. **Portfolio-only feature**; see `docs/COMPLIANCE.md`. |
| `X-Request-ID` | both | Correlation id. Echoed back; generated if absent. |
| `X-Process-Time` | response | Server-side processing seconds. |
| `X-RateLimit-Limit` | response | Requests allowed per window (default 100/60s). |
| `X-RateLimit-Remaining` | response | Requests remaining in the current window. |
| `Retry-After` | response (429) | Seconds to wait. Sent on rate-limit 429s, auth lockout 429s, and org-budget 429s. |
| `X-Error-Code` | response (503) | `BUDGET_EXHAUSTED` when the platform's global LLM budget is spent (distinct from the generic "AI service unavailable" 503). |

There is no `X-RateLimit-Reset` header. Rate limiting is keyed by the hashed
API key or bearer token when present, falling back to client IP; health
endpoints are exempt.

## Errors

Errors return `{"detail": "message"}` (some include machine-readable info in
headers, per the table above). Statuses you will actually see:

| Status | When |
|---|---|
| 400 | Bad file magic bytes, invalid status value, malformed BYOK header |
| 401 | Missing/invalid API key or JWT |
| 403 | Missing scope, or principal has no organization |
| 404 | Not found, including cross-tenant reads (indistinguishable by design) |
| 413 | Body or file over the size cap, or LLM input too large |
| 422 | Validation error, or OCR could not extract text |
| 429 | Rate limit, auth lockout, org token budget, or upstream LLM rate limit |
| 500 | Persistence failure (retry with the same `Idempotency-Key`) |
| 503 | LLM unavailable, or budget exhausted (`X-Error-Code: BUDGET_EXHAUSTED`) |

---

## Auth

### POST /api/v1/auth/token

Exchange an API key (`X-API-Key` header, no body) for a short-lived JWT
(default 24h expiry). Repeated failures trigger a per-IP lockout that
returns `429` with `Retry-After`.

Response `200`:

```json
{"access_token": "eyJ...", "token_type": "bearer", "expires_in": 86400}
```

`401` on invalid, revoked, or expired keys.

### POST /api/v1/auth/logout

Revokes the caller's JWT session. Returns `204`. Returns `400` if called
with API-key auth (there is no session to revoke).

---

## Appeals

### POST /api/v1/appeals/upload

Generate an appeal from an uploaded denial document. `multipart/form-data`.
Files are validated by magic bytes; the declared `Content-Type` is ignored.
Accepted: **PDF, PNG, JPEG** only. Max size: 10 MB (configurable via
`MAX_UPLOAD_SIZE_MB`).

| Form field | Type | Required |
|---|---|---|
| `denial_letter` | file | yes |
| `patient_name` | string | no |
| `procedure_code` | string | no |
| `procedure_description` | string | no |
| `diagnosis_codes` | string (comma-separated) | no |
| `clinical_notes` | string | no |
| `prior_treatments` | string (comma-separated) | no |
| `treating_physician` | string | no |

Response: see [AppealResponse](#appealresponse). Declared errors: 400, 401,
413, 422, 429, 503.

### POST /api/v1/appeals/text

Generate an appeal from pasted denial text. JSON body:

| Field | Type | Constraints |
|---|---|---|
| `denial_text` | string | required, 50 to 100,000 chars |
| `patient_name` | string | max 200 |
| `procedure_code` | string | alphanumeric, max 20 |
| `procedure_description` | string | max 500 |
| `diagnosis_codes` | list[string] or comma-separated string | max 20 codes |
| `clinical_notes` | string | max 10,000 |
| `prior_treatments` | list[string] or comma-separated string | |
| `treating_physician` | string | max 200 |

Declared errors: 400, 401, 413, 429, 503.

```bash
curl -X POST https://prior-auth-assistant-production.up.railway.app/api/v1/appeals/text \
  -H "X-API-Key: pa_demo_publickey_safe_to_share_DEADBEEF" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-$(date +%s)" \
  -d '{"denial_text": "Dear Provider: The requested MRI of the lumbar spine (CPT 72148) for member M123456 has been denied as not medically necessary. Conservative therapy has not been documented for the required 6-week period..."}'
```

### AppealResponse

Returned by both generation endpoints, `GET`, and the status `PATCH`:

```json
{
  "appeal_id": "550e8400-e29b-41d4-a716-446655440000",
  "appeal_letter": "Dear Appeals Department, ...",
  "denial_info": {
    "payer_name": "Blue Cross Blue Shield",
    "denial_date": "2026-06-01T00:00:00Z",
    "denial_reason": "medical_necessity",
    "denial_reason_text": "Does not meet medical necessity criteria",
    "procedure_codes": ["72148"],
    "diagnosis_codes": ["M54.5"],
    "member_id": "M123456",
    "claim_number": "CLM987654",
    "appeal_deadline": "2026-11-28T00:00:00Z",
    "raw_text": "..."
  },
  "required_documents": ["Letter of medical necessity", "Clinical notes"],
  "confidence_score": 0.85,
  "created_at": "2026-07-06T10:00:00Z",
  "warnings": []
}
```

`denial_reason` is one of: `medical_necessity`, `not_covered`,
`out_of_network`, `missing_information`, `experimental_treatment`,
`step_therapy_required`, `quantity_limit`, `prior_auth_required`, `other`.

`warnings` may flag low-confidence extraction, an unidentified payer, or a
possibly-passed deadline.

### GET /api/v1/appeals/{appeal_id}

Retrieve a stored appeal. Tenant-scoped: appeals from other orgs return
`404` (and the failed access is audited). Response is an
[AppealResponse](#appealresponse).

### PATCH /api/v1/appeals/{appeal_id}/status

Update an appeal's status. JSON body: `{"status": "submitted"}`.

Valid statuses: `generated`, `submitted`, `approved`, `denied`, `withdrawn`.
Appeals start as `generated`. Any value in that set is accepted (the API does
not enforce a strict transition graph); setting the current status again is an
idempotent no-op. A real change emits the `appeal.status_changed` webhook and
an audit row. Errors: 400 (invalid status), 401, 404. Returns the updated
[AppealResponse](#appealresponse).

---

## Payers

**These endpoints are unauthenticated.** They serve static seed data (contact
info and appeal requirements for common payers), no tenant data.

### GET /api/v1/payers

Returns `{"payers": [...]}` where each payer has `id`, `name`, `aliases`,
`appeals_phone`, `appeal_deadline_days`, and
`medical_necessity_requirements`.

### GET /api/v1/payers/{payer_name}/requirements

Fuzzy name/alias match against the seed list. Returns `payer`,
`appeal_deadline_days`, `appeals_phone`, `medical_necessity`,
`step_therapy`, and `documentation`. Note: an unknown payer returns `200`
with an `error` field in the body, not a `404`.

---

## Admin

All admin endpoints require the `admin` scope. Org-scoped admins see and
manage only their own org; global admins (no `org_id` on the principal) can
operate across orgs and filter lists with `?org_id=...`.

### API keys

| Endpoint | Notes |
|---|---|
| `POST /api/v1/admin/api-keys` | Body: `org_id`, `name`, `scopes` (list), optional `expires_at`. Returns `201` with `plaintext_key` **shown exactly once**; only the SHA-256 hash is stored. |
| `GET /api/v1/admin/api-keys` | List with `key_id`, `org_id`, `name`, `scopes`, `created_at`, `expires_at`, `revoked_at`, `last_used_at`, `is_active`. |
| `DELETE /api/v1/admin/api-keys/{key_id}` | Revoke. `204`; idempotent (re-revoking succeeds). `404` if unknown or cross-org. |

### Webhook endpoints

| Endpoint | Notes |
|---|---|
| `POST /api/v1/admin/webhooks` | Body: `url`, `events` (list; empty = all events), `org_id` (required for global admins). Returns `201` with `signing_secret` **shown exactly once**. |
| `GET /api/v1/admin/webhooks` | List with delivery health: `last_delivery_at`, `last_delivery_status`, `is_active`. |
| `DELETE /api/v1/admin/webhooks/{webhook_id}` | Soft-delete (sets `is_active` false). `204`. |

---

## Outbound webhooks

When an appeal's status changes, a delivery is enqueued for every active
endpoint in the org subscribed to the event (or subscribed to all events).
A background worker POSTs JSON:

```json
{
  "id": "<delivery-id>",
  "event": "appeal.status_changed",
  "payload": {
    "appeal_id": "...",
    "previous_status": "generated",
    "new_status": "submitted",
    "changed_by": "apikey:...",
    "changed_at": "2026-07-06T10:00:00Z"
  }
}
```

Payloads are PHI-free. Request headers:

| Header | Value |
|---|---|
| `X-Signature` | `sha256=<hex>`: HMAC-SHA256 of the raw request body using your endpoint's `signing_secret`. Verify with a constant-time compare. |
| `X-Event-Type` | e.g. `appeal.status_changed` |
| `X-Delivery-Id` | Unique per delivery; use for dedupe |

Respond with any 2xx to acknowledge. Non-2xx and connection errors are
retried with exponential backoff (5s, 10s, 30s, 2m, 10m, 30m, capped at 1h)
up to 5 attempts by default (`WEBHOOK_MAX_ATTEMPTS`). Delivery timeout is 5s.
Currently the only event type is `appeal.status_changed`.

---

## Health and operations

| Endpoint | Behavior |
|---|---|
| `GET /health` | Component report (database, redis, llm, ocr) with overall `healthy` / `degraded` / `unhealthy`. Redis reports healthy when intentionally not in use. |
| `GET /health/live` | Liveness probe. `{"status": "alive"}`. |
| `GET /health/ready` | Readiness probe. `503` if the database or LLM is not ready. |
| `GET /metrics` | Prometheus exposition. Unauthenticated by design; it is expected to be reachable only from the internal monitoring network. **Do not expose publicly.** |

Health endpoints are exempt from rate limiting and HTTPS enforcement (so
platform probes work without TLS).

## CORS

Browser clients must originate from an origin in `CORS_ORIGINS`. Allowed
request headers include `X-API-Key`, `Authorization`, `Idempotency-Key`,
`X-Request-ID`, and `X-User-Anthropic-Key`. Exposed response headers:
`X-Request-ID`, `X-Process-Time`, `X-RateLimit-Limit`,
`X-RateLimit-Remaining`, `X-Error-Code`, `Retry-After`.
