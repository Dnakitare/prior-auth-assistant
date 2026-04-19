# Load test

[k6](https://k6.io/) scenarios for Prior Auth Assistant. Run against
**staging**, never prod, and against an org specifically provisioned for
load with a high per-org token budget.

## Install

```bash
brew install k6        # or: https://k6.io/docs/get-started/installation/
```

## Run

```bash
# Smoke (30s, 1 VU) — validates a deploy.
k6 run -e BASE_URL=https://staging.example.com -e API_KEY=pa_...  \
    loadtest/k6-appeals.js

# Soak (sustained) — tune DB/Redis sizing, look for slow creep.
k6 run -e BASE_URL=https://staging.example.com -e API_KEY=pa_... \
    --vus 50 --duration 15m loadtest/k6-appeals.js

# Spike is included in the default scenarios.
```

## What to watch during a run

1. `http_req_duration` p95 / p99 — the thresholds fail the run if breached.
2. `rate_limit_exceeded_total` Prometheus counter — are we hitting the
   configured RPM limit at the replica level?
3. Postgres pool saturation — `pg_stat_activity` for connection count vs
   `database_pool_size × replicas`.
4. Redis `INFO memory` / `INFO clients` for lockout + rate-limit keyspace.
5. Anthropic dashboard for request volume / spend.

## Cost warning

Each VU executing the appeal flow costs roughly 2 Claude calls. A 15-minute
soak with 50 VUs will make several thousand calls. Set the org's
`org_daily_token_budget` to the intended soak budget or you will be
rate-limited partway through.
