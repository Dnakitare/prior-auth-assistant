# Prior Authorization Assistant

AI-powered prior authorization appeals automation for healthcare providers. Extracts structured data from denial letters and generates tailored appeal letters.

> **Status.** The security posture was overhauled in a two-round hardening pass. See [SECURITY.md notes](#security-model) below for the current model and [Launch readiness](#launch-readiness) for what's still in scope before public release.

---

## Features

- **OCR**: AWS Textract (with a mock provider for local development).
- **LLM extraction**: Claude extracts payer, denial reason, codes, deadlines. Hallucinated codes are dropped via post-validation against the source text.
- **Appeal generation**: 9 denial-type templates, enhanced by Claude with role-separated system prompts, nonced delimiters, and prompt caching.
- **Tenant isolation**: every PHI query is scoped by `org_id`; cross-tenant reads return 404. Postgres **row-level security** enforces the boundary at the database layer too: even a query that forgets the `WHERE org_id = …` clause can't leak rows from another tenant.
- **PHI encryption at rest**: Fernet/MultiFernet field-level encryption for `patient_name`, `member_id`, `claim_number`, `denial_reason_text`, `denial_text`, `appeal_letter`, and diagnosis codes.
- **Audit log**: append-only `audit_log` table with an HMAC-SHA256 hash chain. `audit.verify_chain()` detects insertion, deletion, or modification.
- **Distributed rate limiting**: Redis fixed-window, keyed by API key / JWT subject (falls back to IP only for unauthenticated traffic).
- **Brute-force lockout**: per-IP failure counter on `/auth/token`.
- **Strict CSP, HSTS, no `data:` images, trusted-proxy X-Forwarded-For**.
- **Prometheus `/metrics`**, structured JSON logs in production, per-request `X-Request-ID`.

---

## Architecture

```
┌──────────────┐     ┌───────────────────────┐     ┌──────────────┐
│ React + Vite │────▶│ FastAPI (async)        │────▶│ PostgreSQL   │
└──────────────┘     │  ├── appeals            │     │   (PHI enc)  │
                     │  ├── auth               │     └──────────────┘
                     │  ├── admin              │     ┌──────────────┐
                     │  └── health / metrics   │────▶│ Redis        │
                     └────────┬──────────┬─────┘     │ (rate limit, │
                              │          │           │  lockout)    │
                              ▼          ▼           └──────────────┘
                       ┌─────────┐ ┌──────────┐
                       │ Claude  │ │ Textract │
                       │  (API)  │ │  (OCR)   │
                       └─────────┘ └──────────┘
```

Key request flow for appeal generation:

1. Client POST to `/api/v1/appeals/{upload,text}` with an API key or JWT.
2. Middleware: body size cap → HTTPS enforcement → CSP/HSTS → rate limit → request-id binding.
3. Handler validates magic bytes (upload) or Pydantic schema (text), runs OCR → Claude extraction (post-validated) → template fill → Claude enhancement (preserves identifiers).
4. Repository persists encrypted row scoped to `(org_id, created_by)` with optional `Idempotency-Key` dedupe.
5. Audit writes into the HMAC-chained log (best-effort — appeal write is durable even if the audit row fails).

---

## Quick start (development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Fill in ANTHROPIC_API_KEY; generate JWT + audit secrets and a Fernet PHI key:
#   python -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_urlsafe(64))"
#   python -c "import secrets; print('AUDIT_HMAC_KEY=' + secrets.token_urlsafe(64))"
#   python -c "from cryptography.fernet import Fernet; print('PHI_ENCRYPTION_KEYS=' + Fernet.generate_key().decode())"
#   python -c "import secrets; print('BOOTSTRAP_API_KEYS=pa_' + secrets.token_urlsafe(32))"

# With Docker (brings up Postgres + Redis + API + frontend):
docker compose up --build

# Or locally against existing Postgres + Redis:
python -m scripts.migrate upgrade head
uvicorn src.api.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev
```

On first boot, any keys in `BOOTSTRAP_API_KEYS` are seeded into `api_keys` (hashed). Remove the env var after the first run — additional keys are managed via `/api/v1/admin/api-keys`.

---

## Configuration

All settings come from environment variables, parsed by `src/core/config.py`. The **production validator** fails startup if any of the following are missing or weak:

| Variable | Required in prod | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✓ | Claude API credential |
| `DATABASE_URL` | ✓ | `postgresql+asyncpg://…` |
| `JWT_SECRET_KEY` | ✓ | ≥32 chars; must be set explicitly |
| `AUDIT_HMAC_KEY` | ✓ | ≥32 chars; must differ from JWT key |
| `PHI_ENCRYPTION_KEYS` | ✓ | Comma-separated Fernet keys. First is used for writes; all are tried for reads (key rotation) |
| `REQUIRE_HTTPS` | ✓ (true) | Middleware rejects non-HTTPS unless probe path |
| `RATE_LIMIT_BACKEND` | ✓ (`redis`) | `memory` is dev-only |
| `CORS_ORIGINS` | ✓ | No `*`, no `localhost` |
| `TRUSTED_PROXIES` | recommended | IPs/CIDRs whose `X-Forwarded-For` / `X-Forwarded-Proto` we honor. Blank = ignore |
| `BOOTSTRAP_API_KEYS` | one-time | Seeded on boot; remove after |
| `MIGRATE_ON_STARTUP` | `false` in multi-replica | Use `python -m scripts.migrate` as an init job instead |
| `HEALTH_CHECK_LLM_LIVE` | optional | If `true`, `/health` pings Claude (costs tokens) |

See `.env.example` for the full list including tunables.

---

## API

### Auth

| Endpoint | Auth | Description |
|---|---|---|
| `POST /api/v1/auth/token` | API key | Exchange an API key for a short-lived JWT. Rate-limited per IP via lockout |
| `POST /api/v1/auth/logout` | JWT | Revoke the caller's current session row |

### Appeals

| Endpoint | Auth | Description |
|---|---|---|
| `POST /api/v1/appeals/upload` | API key / JWT | Multipart file (PDF/PNG/JPEG/TIFF); validated by magic bytes, not `Content-Type`. Accepts `Idempotency-Key` |
| `POST /api/v1/appeals/text` | API key / JWT | JSON with `denial_text`; body-size-capped. Accepts `Idempotency-Key` |
| `GET /api/v1/appeals/{id}` | API key / JWT | Tenant-scoped; cross-tenant returns 404 (and is audited) |

### Admin (scope: `admin`)

| Endpoint | Description |
|---|---|
| `POST /api/v1/admin/api-keys` | Create a key. Plaintext returned **once** in the response |
| `GET /api/v1/admin/api-keys` | List keys (filtered by org for org-scoped admins) |
| `DELETE /api/v1/admin/api-keys/{id}` | Revoke a key (idempotent) |
| `POST /api/v1/admin/webhooks` | Register a webhook endpoint. Signing secret returned **once** |
| `GET /api/v1/admin/webhooks` | List webhook endpoints |
| `DELETE /api/v1/admin/webhooks/{id}` | Soft-delete (sets `is_active=false`) |

### Appeal lifecycle

| Endpoint | Description |
|---|---|
| `PATCH /api/v1/appeals/{id}/status` | Transition status (`generated` → `submitted` → `approved`/`denied`/`withdrawn`). Emits `appeal.status_changed` webhook |

### Operational

| Endpoint | Description |
|---|---|
| `GET /health` | Component health (DB, Redis, LLM, OCR) |
| `GET /health/live` | Liveness probe |
| `GET /health/ready` | Readiness probe (DB + LLM key format) |
| `GET /metrics` | Prometheus exposition. **Do not expose publicly** — restrict to the monitoring network |

---

## Security model

### Authentication & authorization

- API keys are stored as SHA-256 hashes in the `api_keys` table; plaintext is never persisted. Comparison uses `hmac.compare_digest` for defence-in-depth constant time.
- **Postgres RLS** (migration 005) enables FORCE ROW LEVEL SECURITY on every tenant-scoped table (`appeals`, `audit_log`, `webhook_endpoints`, `webhook_deliveries`, `api_keys`, `org_quotas`). Policies check `app.org_id` and `app.is_admin` GUCs, which `get_current_user` sets via `set_config()` once per request. System paths (bootstrap seeding, webhook worker) explicitly set `app.is_admin='true'`. A bug that forgets to filter by `org_id` in the ORM still cannot return cross-tenant rows.
- JWTs reference a `user_sessions` row (`jti` claim = row id). Revoking the row instantly invalidates the token — `/auth/logout` does this for the caller, admin endpoints can revoke any session.
- Scopes: `appeals:read`, `appeals:write`, `admin`. `require_scope` returns 403 to under-privileged tokens.

### Data protection

- `EncryptedText` columns wrap Fernet. `MultiFernet` supports key rotation: prepend a new key, run `scripts/encrypt_phi_backfill.py`, then retire the old key.
- Migration 002 widened string columns to `Text` to hold ciphertext. Migration 003 drops the legacy plaintext `diagnosis_codes` column once the backfill has run.

### Audit log integrity

Every write links to the previous row:

```
row_hmac = HMAC-SHA256(AUDIT_HMAC_KEY, prev_hmac || canonical_event_json)
```

- `audit.verify_chain()` recomputes the chain and returns `(ok, first_bad_sequence)`. Run this as a scheduled job.
- `AUDIT_HMAC_KEY` must differ from `JWT_SECRET_KEY` (enforced at startup).
- For stronger tamper-evidence against app-level RCE, ship `audit_event` structlog lines to an append-only external sink (CloudWatch Logs with WORM, S3 Object Lock, QLDB). The in-DB chain catches insider threats and disk corruption but not an attacker who controls the process.

### Transport & headers

- `HttpsEnforcementMiddleware` rejects plain-HTTP requests when `REQUIRE_HTTPS=true`, honoring `X-Forwarded-Proto` only from trusted peers.
- HSTS `max-age=63072000; includeSubDomains; preload` in production.
- CSP: strict `script-src 'self'`; `style-src 'self' 'unsafe-inline'` (React inline `style={{}}`; migrating to CSS modules would let us drop this); no `data:` in `img-src`; `frame-ancestors 'none'`.

### Operational limits

- Global request body size cap (`MAX_UPLOAD_SIZE_MB × 2` by default) rejects before Pydantic ever buffers the body.
- Redis fixed-window rate limit per API key / JWT subject; falls back to client IP when unauthenticated.
- Brute-force lockout: 5 failures per IP per 15 minutes on `/auth/token`.
- Postgres server-side `statement_timeout=30s` and `idle_in_transaction_session_timeout=60s` (applied when using `asyncpg`).

---

## Operations

### Deploying

1. Build the image: `docker build -t prior-auth-assistant:$(git rev-parse --short HEAD) .`
2. Provision secrets (KMS, k8s Secrets, etc.). The container expects env vars, not files.
3. Run migrations as a separate step (**do not** run `MIGRATE_ON_STARTUP=true` in multi-replica):

   ```bash
   docker run --rm --env-file .env.prod prior-auth-assistant:TAG \
       python -m scripts.migrate upgrade head
   ```

4. Roll out the app replicas with `MIGRATE_ON_STARTUP=false`.
5. Point monitoring at `/metrics` (internal network only).
6. Confirm `/health/ready` returns 200.

### Key rotation

1. Generate a new Fernet key. Prepend to `PHI_ENCRYPTION_KEYS` (new key first). Roll the app so writes use the new key while reads still accept the old.
2. Run `python -m scripts.encrypt_phi_backfill` — this is idempotent; it rewrites ciphertext under the new key as ORM round-trips occur.
3. After the backfill completes, remove the old key from `PHI_ENCRYPTION_KEYS` and roll again.

`JWT_SECRET_KEY` rotation invalidates all outstanding tokens. Plan for a short window where old tokens produce 401.

### Chain verification

Schedule a weekly job that calls `audit.verify_chain(db)` and alerts on divergence. A broken chain indicates tampering or corruption.

### Backfill after upgrade (PHI encryption)

For an existing deployment upgrading through migration 002:

```bash
# 1. Apply migration 002 (adds diagnosis_codes_encrypted, widens PHI columns)
python -m scripts.migrate upgrade 002

# 2. Backfill the encrypted column from the legacy plaintext column
python -m scripts.encrypt_phi_backfill --dry-run  # check
python -m scripts.encrypt_phi_backfill            # commit

# 3. Drop the legacy plaintext column
python -m scripts.migrate upgrade head  # applies 003
```

### Observability

Metrics exposed at `/metrics`:

- `http_requests_total{method,path_template,status}` / `http_request_duration_seconds`
- `llm_calls_total{operation,outcome}` / `llm_call_duration_seconds{operation}`
- `rate_limit_exceeded_total`, `auth_failures_total{kind}`, `audit_write_failures_total`

Structured JSON logs in production include `request_id`, `user_id`, `org_id`, and never the query string.

---

## Development

### Testing

```bash
pytest             # 84 tests, real SQLite DB + PHI encryption + audit chain verification
pytest --cov=src   # with coverage
```

Integration tests seed two tenants and exercise cross-tenant 404, revocation, magic-byte upload rejection, audit HMAC chain, body-size rejection, and lockout.

### Project layout

```
prior-auth-assistant/
├── src/
│   ├── api/
│   │   ├── main.py                   # app + middleware stack + /metrics
│   │   └── routes/
│   │       ├── admin.py              # API-key lifecycle
│   │       ├── appeals.py            # generation + tenant-scoped retrieval
│   │       ├── auth.py               # token exchange + logout + lockout
│   │       ├── health.py             # /health, /health/live, /health/ready
│   │       └── payers.py
│   ├── core/
│   │   ├── audit.py                  # HMAC chain with retry-on-conflict
│   │   ├── config.py                 # Pydantic settings; fail-closed in prod
│   │   ├── database.py               # asyncpg + statement_timeout
│   │   ├── db_models.py              # ORM + encrypted columns
│   │   ├── encryption.py             # Fernet/MultiFernet TypeDecorator
│   │   ├── lockout.py                # brute-force counter (Redis / memory)
│   │   ├── metrics.py                # Prometheus registry
│   │   ├── middleware.py             # body size, HTTPS, headers, rate limit
│   │   ├── repositories.py           # tenant-scoped queries
│   │   ├── security.py               # API keys, JWT sessions, revocation
│   │   └── upload_validation.py      # magic-byte MIME detection
│   ├── integrations/
│   │   ├── llm.py                    # delimited prompts + prompt caching
│   │   └── ocr.py                    # Textract + mock provider
│   └── templates/appeal_templates.py
├── alembic/versions/                 # 001 initial, 002 encryption+tenancy, 003 drop legacy
├── scripts/
│   ├── encrypt_phi_backfill.py       # idempotent PHI backfill
│   └── migrate.py                    # alembic CLI for init containers
├── frontend/                         # React + Vite + TS
├── docker-compose.yml                # dev
├── docker-compose.prod.yml           # prod (read-only fs, no mounted source)
└── tests/                            # pytest, real SQLite DB
```

---

## Launch readiness

Completed in the hardening rounds (1–3):

- **Security / PHI**: tenant isolation, field-level PHI encryption (Fernet MultiFernet), HMAC-chained audit log, magic-byte uploads, prompt-injection hardening.
- **Auth**: DB-backed API keys, JWT revocation, brute-force lockout, admin key + webhook CRUD.
- **Edge protections**: Redis distributed rate limiting, body-size cap, HTTPS enforcement, strict CSP.
- **External witness**: CloudWatch Logs audit sink (retention-locked).
- **Observability**: Prometheus `/metrics` with RED + LLM + audit signals; OpenTelemetry tracing for FastAPI + SQLAlchemy + httpx + explicit LLM spans; real LLM health ping (opt-in).
- **DB hygiene**: statement timeout, idle-in-tx timeout, pool recycle.
- **Cost controls**: per-org daily LLM token budget (`org_quotas`).
- **Lifecycle**: appeal status transitions + signed outbound webhooks with retry & exponential backoff.
- **Ops**: separate migration CLI, encrypted backup script + restore drill docs, k6 load test, security/compliance/legal runbooks.
- **Dependencies**: pinned with tight upper bounds.

Still required before serving patient data — work we can't do from code:

- **Signed BAAs** with Anthropic and AWS (see [docs/COMPLIANCE.md](docs/COMPLIANCE.md)).
- **Legal review** of the generated-content disclaimer and UI acknowledgment gate (see [docs/LEGAL.md](docs/LEGAL.md)).
- **Penetration test** + **SOC 2 Type I** audit. Type II follows after a 6–12 month control window.
- **Quarterly drills**: backup restore, chain verification, Fernet key rotation, breach-notification tabletop.

Nice-to-have post-launch:

- **Per-org LLM cost quotas**: schema is in place, but add admin endpoints to set budgets per org and emit notifications as orgs approach their limits.
- **Frontend**: move inline `style={{}}` to CSS modules so CSP can drop `'unsafe-inline'`.
- **Zero-downtime JWT rotation**: accept two keys during cutover.

---

## License

Proprietary. All rights reserved.
