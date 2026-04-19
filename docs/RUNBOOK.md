# Security & operations runbook

What to do when something goes wrong. Each playbook has: **detection →
immediate action → investigation → remediation → post-incident**.

Contacts and paging rotations should be maintained alongside this file in
your on-call tool (PagerDuty / Opsgenie); placeholders below.

---

## 1. Compromised API key

### Detection
- Auth failures spike on a particular key (`auth_failures_total`).
- `api_key.last_used_at` shows activity from unexpected IPs / geos.
- External report: customer, 3rd-party security disclosure, dark-web monitor.
- Anomalous spend against the org's Anthropic budget.

### Immediate action (≤5 minutes)
1. Revoke the key:
   ```bash
   curl -X DELETE https://$API/api/v1/admin/api-keys/$KEY_ID \
       -H "X-API-Key: $ADMIN_KEY"
   ```
   or, if the admin surface is unreachable:
   ```sql
   UPDATE api_keys SET is_active=false, revoked_at=NOW()
     WHERE id = :key_id;
   ```
2. Revoke any JWT sessions that key minted:
   ```sql
   UPDATE user_sessions SET revoked_at=NOW()
     WHERE user_id = 'apikey:' || :key_id
       AND revoked_at IS NULL;
   ```
3. Tell the org owner to rotate any integrations pinned to that key.

### Investigation
- `SELECT * FROM audit_log WHERE user_id = 'apikey:' || :key_id ORDER BY sequence DESC LIMIT 500;`
- Cross-reference `ip_address` with known good ranges.
- Cross-reference `resource_id` access patterns — was PHI enumeration attempted?

### Remediation
- Issue a replacement via `POST /api/v1/admin/api-keys`.
- If the leak vector is unknown, rotate all keys for that org.
- If source-of-truth is an external repo (accidental Git commit), rotate
  Anthropic + any shared secrets that might have been exposed alongside.

### Post-incident
- HIPAA breach notification calculus: did the attacker access PHI? If yes,
  start the §164.410 clock.
- File a retrospective. Add a detection signal that would have caught this
  faster.

---

## 2. Audit chain verification failure

### Detection
- Scheduled job invoking `audit.verify_chain()` returns `ok=False` with a
  `first_bad_sequence`.
- Or: the CloudWatch stream and DB table diverge in count by more than the
  in-flight queue size.

### Immediate action
1. **Do not truncate or mutate `audit_log`.** Snapshot it:
   ```bash
   pg_dump --table=audit_log $DATABASE_URL > audit_log_snapshot_$(date -u +%Y%m%dT%H%M%SZ).sql
   ```
2. Copy the relevant CloudWatch stream to cold storage for forensic parity.
3. Declare a security incident; alert SecOps on-call.

### Investigation
- Locate the break:
  ```sql
  SELECT sequence, timestamp, action, user_id, resource_id,
         (prev_hmac IS NOT NULL) AS has_prev, length(row_hmac)
  FROM audit_log
  WHERE sequence BETWEEN (:bad_seq - 5) AND (:bad_seq + 5)
  ORDER BY sequence;
  ```
- Compare to the CloudWatch events at the same timestamps. If DB rows are
  mutated or missing but CloudWatch has them, someone touched the DB
  directly.
- Check DB write auditing (RDS Activity Streams if enabled) for the offending
  session.

### Remediation
- The chain break itself is evidence; preserve it. Do not attempt to "fix"
  the chain. New writes will continue in a new segment.
- Identify the root cause (corrupted disk, accidental manual update,
  malicious insider). Act accordingly.

### Post-incident
- Review RBAC: who has DB write access? Should they still?
- If the break was a bug (race, missing index), file and fix; add a
  regression test.

---

## 3. PHI encryption key rotation (planned)

### Prep
- Generate a new Fernet key:
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- Prepend (not append) to `PHI_ENCRYPTION_KEYS`. MultiFernet tries keys in
  order; new key first means new writes use it, old reads still work.

### Rollout
1. Deploy the new env var. Existing ciphertext stays readable; new writes
   use the new key.
2. Run the backfill:
   ```bash
   python -m scripts.encrypt_phi_backfill --dry-run   # sanity
   python -m scripts.encrypt_phi_backfill
   ```
3. When the backfill completes, remove the old key from
   `PHI_ENCRYPTION_KEYS` and deploy again. Old-key ciphertext should now be
   zero — confirm with a sampling query that decrypts a random row.

### Rollback
- If the backfill errors mid-run, leave both keys in place. MultiFernet
  handles the mixed state. Investigate the error and restart.

---

## 4. JWT signing key rotation

### Prep
- There is no dual-key JWT verification in this codebase. Rotating
  `JWT_SECRET_KEY` invalidates **all** outstanding tokens.

### Rollout
1. Broadcast to API consumers: "tokens will be invalidated at T; please
   re-exchange API keys for new JWTs after that time."
2. At T, update `JWT_SECRET_KEY`, deploy.
3. Monitor `auth_failures_total{kind="jwt"}` for stragglers.

### Follow-up
- If zero-downtime JWT rotation becomes a requirement, add a
  `JWT_PREVIOUS_SECRET_KEY` env var and try both on decode. Track as a
  future improvement.

---

## 5. Suspected PHI breach

Follow your organization's incident response plan in addition to these
technical steps.

### Immediate action
1. Containment: rotate any credentials that may have been exposed. Revoke
   all API keys for the affected org. Quarantine the compromised host /
   replica.
2. Preserve evidence: pg_dump audit_log; snapshot CloudWatch audit log
   stream; save relevant application logs to cold storage.

### Investigation
- `SELECT user_id, COUNT(*) FROM audit_log WHERE contains_phi=true
    AND timestamp > now() - interval '24 hours' GROUP BY user_id;` — who
  touched PHI in the window?
- `audit_log.resource_id` distribution — was enumeration attempted?
- Cross-reference with `http_requests_total{status="404"}` spikes (a 404
  here means a tenant-isolation block; worth noting).

### Breach notification (HIPAA §164.400-414)
- Determine the scope (records impacted, PHI elements exposed).
- Notify the covered entity / patients within 60 days of discovery.
- Notify HHS via the breach portal within 60 days (or annually for <500
  records).
- If >500 records in a state, notify local media.

Legal counsel drives notification — this is the technical feed into that
process, not a substitute.

### Post-incident
- Root-cause analysis. Was this a control failure (bug) or a policy
  failure (access that shouldn't have existed)?
- Update this runbook with what was missing.

---

## 6. Anthropic outage

### Detection
- `llm_calls_total{outcome="error"}` climbing.
- `/health` with `HEALTH_CHECK_LLM_LIVE=true` flipping to UNHEALTHY.

### Immediate action
- Degrade gracefully: the API still returns a 503 with a clear message.
  Consumers with retry logic will back off.
- Surface the status on the public status page.

### Optional mitigation
- Preserve denial text so users can retry after the upstream recovers. The
  server already persists the raw input via the encrypted `denial_text`
  column on any successful OCR, but in a prolonged outage the endpoint
  fails before that write. A queue-for-later pattern is a future addition.

---

## 7. Database outage

### Detection
- `/health/ready` returns 503.
- SQLAlchemy `OperationalError` rate climbs.

### Immediate action
1. Confirm the DB is actually down (AWS RDS console / provider status page).
2. Fail over to the replica if HA is configured.
3. Scale app replicas down temporarily to reduce retry storms.

### During the outage
- Appeal generation is unavailable. Document on the status page.
- Audit events that can't land in the DB are still captured by structlog
  and (if configured) the CloudWatch sink — they're durable enough to
  reconstruct events later.

---

## 8. Rate-limit false positives

### Detection
- Legitimate org reports consistent 429s. `rate_limit_exceeded_total` is
  spiking for their API-key hash.

### Diagnosis
- The rate limiter keys on `sha256(api_key)[:32]`. A single key under heavy
  usage will legitimately hit its limit.
- Check `RATE_LIMIT_REQUESTS` and `RATE_LIMIT_WINDOW_SECONDS` against the
  customer's expected volume.

### Remediation
- Issue the org a second API key to spread load, or raise the window limit
  for their bucket (future: per-org overrides table).

---

## 9. Two-role Postgres deployment (recommended for prod)

Row-level security policies (migration 005) only help when the running
app can't trivially set `app.is_admin = 'true'`. An API replica will
always have that capability on its own session — so the real separation
lives at the Postgres role level.

### Provisioning

```sql
-- Schema owner used ONLY for migrations. Run scripts/migrate.py under this
-- role. Not used at runtime.
CREATE ROLE prior_auth_migrator LOGIN PASSWORD :'migrator_pw';
GRANT ALL PRIVILEGES ON DATABASE prior_auth TO prior_auth_migrator;
ALTER DATABASE prior_auth OWNER TO prior_auth_migrator;

-- Runtime role used by API replicas. NOT the table owner, so FORCE RLS
-- applies. No BYPASSRLS.
CREATE ROLE prior_auth_runtime LOGIN PASSWORD :'runtime_pw';
GRANT CONNECT ON DATABASE prior_auth TO prior_auth_runtime;
GRANT USAGE ON SCHEMA public TO prior_auth_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
    TO prior_auth_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public
    TO prior_auth_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE prior_auth_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES
    TO prior_auth_runtime;

-- System role used by bootstrap seeder + webhook worker. Has BYPASSRLS
-- because it legitimately reads/writes across tenants.
CREATE ROLE prior_auth_system LOGIN PASSWORD :'system_pw' BYPASSRLS;
GRANT CONNECT ON DATABASE prior_auth TO prior_auth_system;
GRANT USAGE ON SCHEMA public TO prior_auth_system;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
    TO prior_auth_system;
```

### Environment

```
DATABASE_URL       = postgresql+asyncpg://prior_auth_runtime:...@db/prior_auth
DATABASE_ADMIN_URL = postgresql+asyncpg://prior_auth_system:...@db/prior_auth
MIGRATE_ON_STARTUP = false   # run migrate as a separate step under prior_auth_migrator
```

### What this buys

- An attacker who exfiltrates the runtime DSN gets a role that can only
  see one org's rows (RLS enforced) and cannot promote itself — no
  BYPASSRLS on that role, and Postgres won't let a non-superuser grant
  itself BYPASSRLS.
- Setting `app.is_admin='true'` on the runtime session is a no-op because
  the role lacks BYPASSRLS: policies still evaluate against the row's
  `org_id` only.
- The system DSN should be scoped to the pod running the webhook worker /
  bootstrap job and rotated independently of API key material.

### What it does NOT buy

- Protection against an attacker who gets the admin DSN. That credential
  is as sensitive as the Fernet keys — store in a KMS with break-glass
  access logging.
- Protection against a compromised migration step. The migrator role owns
  the schema and can disable RLS. Treat migrations as a privileged CI
  step, not something replicas trigger.

### Metric to alert on

`rls_admin_bypass_total{source}` — any activation is logged. Expected
volume:

- `bootstrap`: once per replica startup.
- `webhook_worker`: once per poll tick (default 5s).
- `request`: once per authenticated-admin request.
- `test`: only in non-prod.

A spike in `request` or activations from an unexpected source label is
a strong signal. Page on it.

---

## Checklists (drills)

Run on a cadence. Evidence goes in your GRC system.

- **Monthly**: audit chain verification job succeeds for last 30 days.
- **Quarterly**: restore drill (see `docs/BACKUP.md`).
- **Quarterly**: key rotation drill on PHI encryption (staging DB).
- **Quarterly**: tabletop exercise of breach notification.
- **Annually**: full DR exercise — fail over DB + app to a separate region.
