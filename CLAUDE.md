# Prior Authorization Assistant - Project Context

This file provides context for Claude Code to understand this project.

## Project Overview

**Prior Authorization Assistant** is an AI-powered tool that automates healthcare prior authorization appeals. It processes denial letters (via OCR or text input), extracts key information, and generates professional appeal letters tailored to the denial reason and payer.

## Tech Stack

### Backend
- **Framework**: FastAPI (async Python)
- **Database**: PostgreSQL with SQLAlchemy async ORM
- **Migrations**: Alembic
- **AI**: Anthropic Claude API (claude-sonnet-4-20250514)
- **OCR**: AWS Textract (with mock provider for testing)
- **Caching**: Redis (optional)
- **Auth**: JWT tokens + API keys

### Frontend
- **Framework**: React 18 with TypeScript
- **Build**: Vite
- **Styling**: Tailwind CSS
- **HTTP Client**: Axios

### Infrastructure
- Docker & Docker Compose
- PostgreSQL 14+
- Redis (optional)

## Directory Structure

```
prior-auth-assistant/
├── src/                      # Python backend source
│   ├── api/
│   │   ├── main.py          # FastAPI app entry point
│   │   └── routes/          # API endpoints
│   │       ├── appeals.py   # Appeal generation endpoints
│   │       ├── health.py    # Health check endpoints
│   │       └── payers.py    # Payer management
│   ├── core/
│   │   ├── config.py        # Pydantic settings (from .env)
│   │   ├── models.py        # Domain models (DenialExtraction, AppealLetter, etc.)
│   │   ├── db_models.py     # SQLAlchemy ORM models
│   │   ├── database.py      # Async database session management
│   │   ├── repositories.py  # Data access layer
│   │   ├── services.py      # Business logic (AppealGenerationService)
│   │   ├── security.py      # JWT/API key authentication
│   │   ├── audit.py         # HIPAA audit logging
│   │   └── middleware.py    # Rate limiting, security headers
│   ├── integrations/
│   │   ├── llm.py           # Anthropic Claude client (async)
│   │   └── ocr.py           # AWS Textract + mock provider
│   └── templates/
│       └── appeal_templates.py  # 8 denial-type specific templates
├── frontend/                 # React frontend
│   ├── src/
│   │   ├── App.tsx          # Main app component
│   │   ├── api.ts           # API client with error handling
│   │   ├── types.ts         # TypeScript types
│   │   └── components/
│   │       ├── ErrorBoundary.tsx
│   │       ├── FileUpload.tsx
│   │       ├── PatientContextForm.tsx
│   │       ├── AppealPreview.tsx
│   │       └── TextInputMode.tsx
│   └── package.json
├── alembic/                  # Database migrations
│   ├── env.py
│   └── versions/
├── tests/                    # Pytest test suite
├── docs/
│   └── API.md               # API documentation
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

## Key Files Reference

### Configuration
- `src/core/config.py` - All settings via Pydantic Settings from environment
- `.env.example` - Template for environment variables

### API Entry Points
- `src/api/main.py` - FastAPI app with middleware, lifespan events
- `src/api/routes/appeals.py` - Main appeal generation endpoints

### Core Business Logic
- `src/core/services.py` - `AppealGenerationService` orchestrates the pipeline
- `src/integrations/llm.py` - `LLMClient` for Claude API calls
- `src/templates/appeal_templates.py` - Appeal letter templates by denial type

### Data Models
- `src/core/models.py` - Pydantic models: `DenialExtraction`, `PatientContext`, `AppealLetter`
- `src/core/db_models.py` - SQLAlchemy: `AppealRecord`, `PayerRecord`, `PayerRuleRecord`

### Security
- `src/core/security.py` - JWT creation/validation, API key validation
- `src/core/audit.py` - HIPAA-compliant audit logging
- `src/core/middleware.py` - Rate limiting, security headers

## Common Development Tasks

### Running the Backend
```bash
# Development
uvicorn src.api.main:app --reload --port 8000

# With Docker
docker-compose up api
```

### Running the Frontend
```bash
cd frontend
npm run dev
```

### Database Operations
```bash
# Apply migrations
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "Description"

# Rollback
alembic downgrade -1
```

### Running Tests
```bash
pytest                           # All tests
pytest tests/test_api_appeals.py # Specific file
pytest --cov=src                 # With coverage
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
1. **API Key**: `X-API-Key` header (configured via `API_KEYS` env var)
2. **JWT Token**: `Authorization: Bearer <token>` header

## Environment Variables (Key Ones)

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Claude API access |
| `DATABASE_URL` | PostgreSQL connection |
| `JWT_SECRET_KEY` | JWT signing (production: MUST be set, ≥32 chars) |
| `AUDIT_HMAC_KEY` | Audit-chain HMAC key (production: MUST differ from JWT key) |
| `PHI_ENCRYPTION_KEYS` | Comma-separated Fernet keys; first used for writes, all tried for reads |
| `BOOTSTRAP_API_KEYS` | One-time seed keys inserted into `api_keys` on boot; remove after first run |
| `RATE_LIMIT_BACKEND` | `memory` (dev) or `redis` (prod; required in production) |
| `TRUSTED_PROXIES` | IPs/CIDRs whose `X-Forwarded-For` is trusted; blank = ignore header |
| `REQUIRE_HTTPS` | MUST be true in production |
| `CORS_ORIGINS` | Allowed frontend origins; no `*`, no `localhost` in production |
| `APP_ENV` | development / staging / production |

## Appeal Generation Pipeline

1. **Input**: Document upload or text paste
2. **OCR** (if document): AWS Textract extracts text
3. **Extraction**: Claude extracts structured denial info (payer, reason, codes, deadline)
4. **Template Selection**: Choose template based on denial reason
5. **Enhancement**: Claude enhances draft with clinical language
6. **Persistence**: Save to database
7. **Audit**: Log PHI access

## Testing Notes

- Tests use `pytest-asyncio` for async tests
- Mock fixtures in `tests/conftest.py`
- Test environment set via environment variables in conftest
- API tests use `httpx.AsyncClient` with ASGI transport

## Security Features

- **JWT sessions** with DB-backed revocation (user_sessions table + /auth/logout)
- **DB-backed API keys** (hashed); seeded via `BOOTSTRAP_API_KEYS` on first boot
- **Tenant isolation**: every `AppealRepository` method requires `org_id`; cross-tenant reads return 404
- **Field-level PHI encryption** at rest via Fernet (`src/core/encryption.py`, `PHI_ENCRYPTION_KEYS`)
- **Distributed rate limiting** via Redis fixed-window (in-memory fallback for dev); keyed by user/API key, not IP
- **HMAC-chained audit log** in `audit_log` table (tamper-evident; verify via `audit.verify_chain`)
- **Magic-byte file validation** (Content-Type is not trusted)
- **Delimited, role-separated LLM prompts** with prompt caching + identifier post-validation
- Security headers: strict CSP (no `unsafe-inline` scripts, no `data:` images), HSTS preload in prod, `frame-ancestors 'none'`
- Fail-closed production validator in `src/core/config.py` — missing secrets abort startup

## Common Issues & Solutions

### Database Connection
- Ensure PostgreSQL is running
- Check `DATABASE_URL` format: `postgresql+asyncpg://user:pass@host:5432/db`

### LLM Errors
- Verify `ANTHROPIC_API_KEY` is set and valid
- Check for rate limiting (uses tenacity retry)

### CORS Issues
- Update `CORS_ORIGINS` in .env
- Frontend must match an allowed origin

### Authentication Failures
- Check `API_KEYS` contains your key (comma-separated)
- JWT tokens expire based on `JWT_EXPIRE_MINUTES`

## Future Enhancements (Not Yet Implemented)

- [ ] User management and multi-tenancy
- [ ] Appeal status tracking (submitted, approved, denied)
- [ ] Document storage (S3)
- [ ] Webhook notifications
- [ ] Analytics dashboard
- [ ] Batch processing
- [ ] Integration with EHR systems
