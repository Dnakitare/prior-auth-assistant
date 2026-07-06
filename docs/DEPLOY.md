# Deploying the public demo

Target topology: backend on Railway (API + managed Postgres), frontend on
Cloudflare Pages, DNS via the platforms' default subdomains. ~$5/mo plus
LLM tokens.

> **This is the demo deploy.** It is intentionally *not* HIPAA-compliant.
> No BAAs, no pen-test, no SOC 2. Synthetic data only. See
> [What this would need to ship for real](../README.md#what-this-would-need-to-ship-for-real).

---

## 1. Backend on Railway

### Create the project

```bash
# CLI
railway login
railway init prior-auth-assistant
railway add --service postgres
```

Or in the Railway dashboard: New project → Deploy from GitHub repo
(`Dnakitare/prior-auth-assistant`) → Add a Postgres plugin.

`railway.json` at the repo root tells Railway to build from `Dockerfile`,
expose `/health/live` as the healthcheck, and run a single replica.

### Generate secrets locally and set them on Railway

```bash
# Pipe these into `railway variables --set` or paste into the dashboard.
echo "JWT_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(64))')"
echo "AUDIT_HMAC_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(64))')"
echo "PHI_ENCRYPTION_KEYS=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
```

### Required environment variables

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your key (set a `$5/mo` budget cap on it) |
| `JWT_SECRET_KEY` | generated above (≥32 chars) |
| `AUDIT_HMAC_KEY` | generated above (≥32 chars, **different** from JWT key) |
| `PHI_ENCRYPTION_KEYS` | generated above (single Fernet key, comma-separated for rotation) |
| `APP_ENV` | `production` |
| `REQUIRE_HTTPS` | `true` |
| `RATE_LIMIT_BACKEND` | `memory` (single replica) |
| `MIGRATE_ON_STARTUP` | `true` (single replica; flip to `false` when scaling) |
| `CORS_ORIGINS` | placeholder; update once Cloudflare Pages URL is known |
| `TRUSTED_PROXIES` | `100.64.0.0/10,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.1/32` (Railway's edge connects from private/CGNAT space; do NOT use `0.0.0.0/0`, which marks every client a trusted proxy) |
| `DATABASE_URL` | injected automatically by the Postgres plugin |
| `DATABASE_ADMIN_URL` | required in production on Postgres. Reference `${{Postgres.DATABASE_URL}}` on Railway |

The config validator auto-rewrites `postgresql://` → `postgresql+asyncpg://`,
so the DSN Railway injects works directly.

> **Labeled shortcut:** Railway's Postgres plugin hands you a single
> superuser role, so on this demo `DATABASE_ADMIN_URL` points at the same
> DSN as `DATABASE_URL` and RLS never actually binds (the ORM org-scoping
> is the effective control). The real two-role topology (restricted runtime
> role + separate `BYPASSRLS` admin role) is what CI exercises and what a
> production deployment should provision; see `docs/RUNBOOK.md` §9.

### Generate a public domain

```bash
railway domain
# or in the dashboard: Service → Settings → Networking → Generate Domain
```

You get something like `prior-auth-api-production.up.railway.app`
(the live demo runs at `prior-auth-assistant-production.up.railway.app`).

### Seed the demo tenant

After the first deploy completes:

```bash
railway run python -m scripts.seed_demo
```

This inserts the public demo API key (`pa_demo_publickey_safe_to_share_DEADBEEF`)
under `org_id=demo-org`. Idempotent.

### Smoke test

```bash
API=https://prior-auth-assistant-production.up.railway.app  # or your own domain

# 1. Health
curl -s "$API/health/live" | jq

# 2. Auth
curl -s -X POST "$API/api/v1/appeals/text" \
  -H "X-API-Key: pa_demo_publickey_safe_to_share_DEADBEEF" \
  -H "Content-Type: application/json" \
  -d '{"denial_text":"<paste a sample denial from frontend/src/data/sampleDenials.ts>"}' | jq
```

Expect a generated appeal in the response.

---

## 2. Frontend on Cloudflare Pages

### How this demo actually deploys: direct upload

The live project is **not Git-connected** (`wrangler pages project list`
shows `Git Provider: No`). Nothing rebuilds on push; frontend changes ship
by building locally and uploading:

```bash
cd frontend
VITE_API_URL=https://prior-auth-assistant-production.up.railway.app npm run build
wrangler pages deploy dist --project-name prior-auth-assistant --branch main \
  --commit-hash "$(git rev-parse HEAD)" --commit-message "<what changed>"
```

`--branch main` targets the production environment, so the deployment
promotes to `prior-auth-assistant.pages.dev` immediately. `public/_headers`
(CSP and friends) ships inside `dist/` automatically.

> Forgetting this step is a silent failure mode: the API redeploys on every
> push while the frontend quietly stays stale. If you prefer push-to-deploy,
> connect the repo in the dashboard instead (below) — just know that today
> it is not connected.

### Alternative: Git-connected auto-builds

In the Cloudflare dashboard: Workers & Pages → the project → Settings →
Builds → connect `Dnakitare/prior-auth-assistant`. Build settings:

| Setting | Value |
|---|---|
| Framework preset | None (custom) |
| Build command | `cd frontend && npm install && npm run build` |
| Build output directory | `frontend/dist` |
| Root directory | (leave blank — keep at repo root) |
| Node version | `20` (set via `NODE_VERSION` env var if needed) |

Environment variable for production builds:

| Variable | Value |
|---|---|
| `VITE_API_URL` | `https://prior-auth-assistant-production.up.railway.app` (or your own domain; production builds fail without it) |

### Update backend CORS

Back in Railway, set `CORS_ORIGINS` to the Cloudflare Pages URL and
redeploy:

```bash
railway variables --set CORS_ORIGINS=https://prior-auth-assistant.pages.dev
```

If you wire a custom domain later (`app.example.com`), append it to
`CORS_ORIGINS` (comma-separated).

---

## 3. End-to-end smoke test

Open the Pages URL in a browser:

1. Yellow "Public demo — do not submit real PHI" banner is visible.
2. Switch to **Paste Text** mode.
3. Click any "Try a sample" pill → text fills the textarea.
4. Click **Generate Appeal**.
5. Within ~10 seconds you should see a generated appeal with the right payer
   name, codes, and structure.

If the generation hangs or 401s, check:

- Browser console: `VITE_API_URL` baked into the bundle correctly (search
  for it in `frontend/dist/assets/*.js`)
- Railway logs: `railway logs` — likely missing CORS origin or Anthropic key
- Both: TRUSTED_PROXIES not set → HTTPS middleware rejecting forwarded traffic

---

## 4. Cost guardrails

- **Anthropic**: set a monthly budget on the API key (Console → Limits).
  $5/month is enough for hundreds of demo runs with prompt caching.
- **Railway**: $5/month base on the Hobby plan covers 1 service + 1 Postgres.
  Scale to zero is not enabled by default; if usage is bursty, look into
  Railway's autoscale.
- **Cloudflare Pages**: free tier (500 builds/month, unlimited requests).
- **Domain**: optional. Demo runs fine on the platform subdomains.

---

## 5. Day-2 operations

- **Logs**: `railway logs --tail`
- **Metrics**: `/metrics` (do not expose publicly; Railway can be configured
  to require auth or restrict by IP)
- **Audit chain verification**: schedule weekly:
  ```bash
  railway run python -c "
  import asyncio
  from src.core.database import async_session_maker
  from src.core import audit
  async def main():
      async with async_session_maker() as db:
          ok, first_bad = await audit.verify_chain(db)
          print('chain_ok' if ok else f'chain_broken_at={first_bad}')
  asyncio.run(main())
  "
  ```
- **Rotating PHI keys**: prepend a new Fernet key to `PHI_ENCRYPTION_KEYS`,
  redeploy, run `railway run python -m scripts.encrypt_phi_backfill`,
  remove the old key, redeploy.
- **Rotating the demo API key**: edit `DEMO_PLAINTEXT_KEY` in
  `scripts/seed_demo.py`, also update README + frontend if hardcoded
  references exist, then `railway run python -m scripts.seed_demo`.
