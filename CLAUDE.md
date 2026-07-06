# Prior Authorization Assistant - Project Context

This file provides context for Claude Code to understand this project.

## Project Overview

**Prior Authorization Assistant** is an AI-powered tool that automates healthcare prior authorization appeals. It processes denial letters (via OCR or text input), extracts key information, and generates professional appeal letters tailored to the denial reason and payer. Multi-tenant: every record is scoped to an `org_id`, enforced at the repository layer and by Postgres row-level security.

## Tech Stack

### Backend
- **Framework**: FastAPI (async Python 3.12)
- **Database**: PostgreSQL with SQLAlchemy async ORM (SQLite/aiosqlite for tests)
- **Migrations**: Alembic (6 revisions, latest: 006 RLS redesign)
- **AI**: Anthropic Claude API (default model `claude-sonnet-5`; see `LLM_MODEL`)
- **OCR**: Claude document/image content blocks (mock provider when no API key)
- **Rate limiting**: in-memory (single replica) or Redis (multi-replica)
- **Auth**: DB-backed API keys + JWT sessions
- **Observability**: structlog JSON logs, Prometheus `/metrics`, optional OpenTelemetry (OTLP), optional CloudWatch audit sink

### Frontend
- **Framework**: React 19 with TypeScript
- **Build**: Vite 7
- **Styling**: Tailwind CSS 4
- **HTTP Client**: Axios

### Infrastructure
- Docker & Docker Compose (v2 plugin syntax: `docker compose`)
- PostgreSQL 16
- Redis 7 (opt-in via compose `redis` profile)

## Directory Structure

```
prior-auth-assistant/
├── src/
│   ├── api/
│   │   ├── main.py              # FastAPI app, middleware stack, lifespan (migrations,
│   │   │                        #   bootstrap seeding, RLS bypass check, workers)
│   │   └── routes/
│   │       ├── appeals.py       # Generate (document/text), get, status transitions
│   │       ├── auth.py          # API key → JWT exchange, logout (session revocation)
│   │       ├── admin.py         # API key + webhook endpoint CRUD (admin scope)
│   │       ├── health.py        # /health, /health/live, /health/ready
│   │       └── payers.py        # Payer management
│   ├── core/
│   │   ├── config.py            # Pydantic Settings + fail-closed production validator
│   │   ├── models.py            # Domain models (DenialExtraction, AppealLetter, etc.)
│   │   ├── db_models.py         # ORM: AppealRecord, PayerRecord, PayerRuleRecord,
│   │   │                        #   ApiKeyRecord, UserSessionRecord, OrgQuotaRecord,
│   │   │                        #   WebhookEndpointRecord, WebhookDeliveryRecord,
│   │   │                        #   AuditLogRecord
│   │   ├── database.py          # Runtime engine + admin engine (BYPASSRLS role),
│   │   │                        #   get_session / get_admin_session dependencies
│   │   ├── repositories.py      # Data access; org_id required; idempotency dedupe
│   │   ├── services.py          # AppealGenerationService pipeline
│   │   ├── security.py          # JWT + API key auth, RLS context, scopes
│   │   ├── audit.py             # HMAC-chained HIPAA audit log
│   │   ├── audit_sink.py        # Optional CloudWatch Logs audit shipper
│   │   ├── middleware.py        # Rate limit, security headers, HTTPS, body size
│   │   ├── encryption.py        # Field-level PHI encryption (Fernet/MultiFernet)
│   │   ├── webhooks.py          # Outbound delivery worker + emit_appeal_event
│   │   ├── quota.py             # Per-org daily LLM token budgets
│   │   ├── lockout.py           # Login failure lockout (Redis-shared when available)
│   │   ├── metrics.py           # Prometheus metrics
│   │   ├── tracing.py           # Optional OpenTelemetry instrumentation
│   │   └── upload_validation.py # Magic-byte file validation
│   ├── integrations/
│   │   ├── llm.py               # Anthropic Claude client (+ BYOK client factory)
│   │   └── ocr.py               # Claude document/image OCR + mock provider
│   └── templates/
│       └── appeal_templates.py  # 8 denial-type specific templates
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── api.ts               # API client; demo API key baked in as default
│   │   ├── types.ts
│   │   └── components/
│   │       ├── AppealPreview.tsx
│   │       ├── BYOKSettings.tsx # Bring-your-own Anthropic key (sessionStorage)
│   │       ├── ErrorBoundary.tsx
│   │       ├── FileUpload.tsx
│   │       ├── PatientContextForm.tsx
│   │       └── TextInputMode.tsx
│   ├── public/_headers          # CSP + security headers for static hosting
│   ├── vite.config.ts           # Fails prod builds if VITE_API_URL unset
│   └── package.json
├── alembic/versions/            # 000001 initial schema
│                                # 000002 tenant + encryption + sessions
│                                # 000003 drop legacy diagnosis codes
│                                # 000004 quotas and webhooks
│                                # 000005 row-level security
│                                # 000006 RLS: remove GUC admin bypass
├── tests/                       # Pytest suite (100 tests)
├── docs/                        # API.md, BACKUP.md, COMPLIANCE.md, DEPLOY.md,
│                                #   LEGAL.md, RUNBOOK.md, blog-draft.md
├── scripts/                     # migrate.py, seed_demo.py, backup/restore.sh,
│                                #   encrypt_phi_backfill.py, entrypoint.sh
├── loadtest/                    # k6 script
├── docker-compose.yml           # Dev (Redis behind `redis` profile)
├── docker-compose.prod.yml
├── requirements.txt / requirements-dev.txt
├── .env.example
└── README.md
```

## Key Files Reference

### Configuration
- `src/core/config.py` - All settings via Pydantic Settings; production validator fails startup on missing secrets, `DEBUG=true`, permissive CORS, missing `DATABASE_ADMIN_URL` (on Postgres), or `REQUIRE_HTTPS=false`
- `.env.example` - Template for environment variables (kept current; mirror it)

### API Entry Points
- `src/api/main.py` - FastAPI app with middleware, lifespan events
- `src/api/routes/appeals.py` - Appeal generation, retrieval, status transitions

### Core Business Logic
- `src/core/services.py` - `AppealGenerationService` orchestrates the pipeline
- `src/integrations/llm.py` - `LLMClient` for Claude API calls; `make_byok_llm_client` for per-request BYOK keys
- `src/templates/appeal_templates.py` - Appeal letter templates by denial type

### Data Models
- `src/core/models.py` - Pydantic: `DenialExtraction`, `PatientContext`, `AppealLetter`
- `src/core/db_models.py` - SQLAlchemy: see directory tree above for the full list

### Security
- `src/core/security.py` - JWT creation/validation, API key hashing (SHA-256) and lookup, `set_rls_context`, `require_scope`
- `src/core/database.py` - Two engines: runtime (RLS-bound role) and admin (`DATABASE_ADMIN_URL`, BYPASSRLS role); `get_admin_session` for admin routes
- `src/core/audit.py` - HMAC-chained audit logging
- `src/core/middleware.py` - Rate limiting, security headers, HTTPS enforcement, body size limit

## Common Development Tasks

### Running the Backend
```bash
# Development
uvicorn src.api.main:app --reload --port 8000

# With Docker (add --profile redis to include Redis)
docker compose up api
```

### Running the Frontend
```bash
cd frontend
npm run dev
```

### Database Operations
```bash
# Apply migrations (also runs at startup unless MIGRATE_ON_STARTUP=false)
python -m scripts.migrate upgrade head

# Create new migration
alembic revision --autogenerate -m "Description"

# Rollback
alembic downgrade -1
```

### Running Tests
```bash
pytest                           # All tests (SQLite by default)
pytest tests/test_api_appeals.py # Specific file
pytest --cov=src                 # With coverage

# Against Postgres (RLS tests run only here): set DATABASE_URL and
# DATABASE_ADMIN_URL to the two-role topology, see .github/workflows/ci.yml
```

## Denial Types (DenialReason enum)

1. `medical_necessity` - Not medically necessary
2. `not_covered` - Service not covered
3. `out_of_network` - Provider not in network
4. `missing_information` - Documentation incomplete
5. `experimental_treatment` - Experimental/investigational
6. `step_therapy_required` - Must try alternatives first
7. `quantity_limit` - Exceeds quantity limits
8. `prior_auth_required` - Prior auth not obtained
9. `other` - Default/unknown

## API Authentication

Two methods supported:
1. **API Key**: `X-API-Key` header. Keys are stored in the `api_keys` table as SHA-256 hashes with org, scopes, and revocation state. Seeded once from `BOOTSTRAP_API_KEYS` at first boot (unset the var after). Additional keys are managed via the admin endpoints (`POST/GET/DELETE /api/v1/admin/api-keys`, admin scope required).
2. **JWT Token**: `Authorization: Bearer <token>`. Obtained by exchanging an API key at `POST /api/v1/auth/token`. Sessions are DB-backed (`user_sessions`) and revocable via `POST /api/v1/auth/logout`. Expiry set by `JWT_EXPIRATION_HOURS` (default 24).

Optional per-request BYOK: an `X-User-Anthropic-Key` header routes LLM and OCR calls through the caller's own Anthropic key, bypassing the org token budget; usage is tagged in the audit row.

## Environment Variables (Key Ones)

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Claude API access |
| `LLM_MODEL` | Model id, default `claude-sonnet-5` |
| `DATABASE_URL` | PostgreSQL connection (runtime role, RLS-bound) |
| `DATABASE_ADMIN_URL` | BYPASSRLS role for system paths; REQUIRED in production on Postgres |
| `JWT_SECRET_KEY` | JWT signing (production: MUST be set, ≥32 chars) |
| `JWT_EXPIRATION_HOURS` | JWT lifetime, default 24 |
| `AUDIT_HMAC_KEY` | Audit-chain HMAC key (production: MUST differ from JWT key) |
| `PHI_ENCRYPTION_KEYS` | Comma-separated Fernet keys; first used for writes, all tried for reads |
| `BOOTSTRAP_API_KEYS` | One-time seed keys inserted into `api_keys` on boot; remove after first run |
| `RATE_LIMIT_BACKEND` | `memory` (default; fine for a single replica) or `redis` (multi-replica) |
| `ORG_DAILY_TOKEN_BUDGET` | Per-org daily LLM token budget; 0 = unlimited; per-org overrides in `org_quotas` |
| `TRUSTED_PROXIES` | IPs/CIDRs whose `X-Forwarded-For` is trusted; blank = ignore header |
| `REQUIRE_HTTPS` | MUST be true in production |
| `CORS_ORIGINS` | Allowed frontend origins; no `*`, no `localhost` in production |
| `MIGRATE_ON_STARTUP` | Run alembic at boot; set false for multi-replica (use scripts/migrate.py) |
| `APP_ENV` | development / staging / production |

See `.env.example` for the full list (webhook tuning, OTel, CloudWatch audit sink, upload size, lockout/session cleanup).

## Appeal Generation Pipeline

1. **Input**: Document upload (magic-byte validated) or text paste
2. **Idempotency**: optional `Idempotency-Key` header; a repeat (org_id, key) pair returns the existing appeal instead of regenerating
3. **Quota reservation**: upper-bound token estimate reserved against the org's daily budget in its own committed transaction (`_reserve_llm_budget` in `src/api/routes/appeals.py`); skipped for BYOK requests
4. **OCR** (if document): Claude extracts text via document/image content blocks
5. **Extraction**: Claude extracts structured denial info (payer, reason, codes, deadline)
6. **Template Selection**: Choose template based on denial reason
7. **Enhancement**: Claude enhances draft with clinical language (BYOK key used if supplied)
8. **Persistence + Audit**: Save to database; HMAC-chained audit row records PHI types and BYOK usage
9. **Status + Webhooks**: appeals transition through `generated / submitted / approved / denied / withdrawn` via `PATCH /appeals/{id}/status`, which emits an `appeal.status_changed` webhook delivered by the background worker (signed, retried up to `WEBHOOK_MAX_ATTEMPTS`)

## Testing Notes

- 100 tests. CI runs two jobs (`.github/workflows/ci.yml`): SQLite (97 pass + 3 RLS tests skipped) and Postgres with a two-role topology (runtime role + BYPASSRLS admin role) where all 100 run, exercising migrations and real RLS enforcement
- Tests use `pytest-asyncio`; fixtures in `tests/conftest.py`
- conftest does NOT set an admin GUC (migration 006 removed that bypass); schema setup and cross-org seeding go through the admin engine (`async_admin_session_maker`), and direct-DB assertions in tests should too
- API tests use `httpx.AsyncClient` with ASGI transport (lifespan skipped; schema managed explicitly)
- `DATABASE_USE_NULLPOOL=1` is set for tests to avoid asyncpg event-loop teardown issues

## Security Features

- **JWT sessions** with DB-backed revocation (`user_sessions` + /auth/logout), login lockout (`src/core/lockout.py`)
- **DB-backed API keys** (SHA-256 hashed, scoped, revocable); seeded via `BOOTSTRAP_API_KEYS` on first boot, then managed via admin endpoints
- **Tenant isolation, two layers**: every `AppealRepository` method requires `org_id` (cross-tenant reads 404), plus Postgres RLS. Since migration 006 the policies check `app.org_id` only; there is no client-settable admin GUC. Privileged paths (auth-time API key lookup, audit writer, webhook worker, bootstrap seeder, admin routes via `get_admin_session`) run on the admin engine whose role carries BYPASSRLS. Startup refuses to boot in production if that role can't bypass RLS
- **Field-level PHI encryption** at rest via Fernet (`src/core/encryption.py`, `PHI_ENCRYPTION_KEYS`, rotation via MultiFernet)
- **Rate limiting** keyed by user/API key, not IP; in-memory for single replica, Redis fixed-window for multi-replica
- **Per-org LLM token budgets** (`src/core/quota.py`) with committed-transaction reservation
- **HMAC-chained audit log** in `audit_log` (tamper-evident; verify via `audit.verify_chain`); optional CloudWatch external sink
- **Signed webhooks** with retry/backoff via background worker
- **Magic-byte file validation** (Content-Type is not trusted)
- **Delimited, role-separated LLM prompts** with prompt caching + identifier post-validation; input size caps
- Security headers: strict CSP (no `unsafe-inline` scripts), HSTS preload in prod, `frame-ancestors 'none'`. Middleware dispatch order: CORS → SecurityHeaders → RequestContext → HttpsEnforcement → RateLimit → BodySize (see the comment in `src/api/main.py`; Starlette prepends, so add order is reversed)
- Fail-closed production validator in `src/core/config.py`

## Frontend Notes

- `frontend/src/api.ts` bakes in a public demo API key as the default; the demo tenant holds only synthetic data. Users can supply their own key, and BYOK Anthropic keys live in sessionStorage (`BYOKSettings.tsx`)
- `VITE_API_URL` is required for production builds; `vite.config.ts` fails the build without it (prevents shipping a bundle that silently targets localhost)
- `frontend/public/_headers` carries the CSP and security headers for static hosting

## Common Issues & Solutions

### Database Connection
- Ensure PostgreSQL is running
- Check `DATABASE_URL` format: `postgresql+asyncpg://user:pass@host:5432/db` (bare `postgres://` URLs from hosts like Railway are auto-coerced)

### RLS / Empty Query Results on Privileged Paths
- If API-key auth, audit writes, or webhook delivery silently see zero rows on Postgres, the admin engine's role lacks BYPASSRLS. Set `DATABASE_ADMIN_URL` to a BYPASSRLS role (docs/RUNBOOK.md §9). Production refuses to start in this state

### LLM Errors
- Verify `ANTHROPIC_API_KEY` is set and valid
- Check for rate limiting (uses tenacity retry)
- 429 with "token budget exceeded" means the org's daily quota is spent

### CORS Issues
- Update `CORS_ORIGINS` in .env; frontend must match an allowed origin

### Authentication Failures
- API keys live in the `api_keys` table, not an env var; check the key isn't revoked and was seeded/created
- JWT tokens expire per `JWT_EXPIRATION_HOURS`; sessions can also be revoked server-side

### Health Check
- `/health` reports Redis as healthy with "Not in use" when `RATE_LIMIT_BACKEND != redis`; that's intentional, not a failure

## Open Items (Not Yet Implemented)

- [ ] Document storage (S3); uploads are processed in memory, not persisted
- [ ] Analytics dashboard
- [ ] Batch processing
- [ ] Integration with EHR systems
