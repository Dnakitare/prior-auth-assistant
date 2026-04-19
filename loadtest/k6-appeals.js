/*
 * k6 load test for Prior Auth Assistant.
 *
 * Scenarios:
 *   - smoke:   1 VU for 30s — sanity check a staging deploy
 *   - soak:    50 VUs for 15 min — sustained realistic load
 *   - spike:   0 → 200 VUs in 30s, hold 1 min, back to 0 — rate-limit probe
 *
 * Thresholds deliberately tight; breaking them gates a deploy.
 *
 * Env:
 *   BASE_URL       e.g. https://staging.example.com
 *   API_KEY        a valid API key for the staging org (don't use prod)
 *
 * Run:
 *   k6 run -e BASE_URL=... -e API_KEY=... --tag scenario=smoke loadtest/k6-appeals.js
 *   k6 run -e BASE_URL=... -e API_KEY=... --tag scenario=soak  --vus 50 --duration 15m loadtest/k6-appeals.js
 */

import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";
// k6's JS runtime doesn't ship `crypto.randomUUID`. Use the UUID module
// from jslib (bundled with k6 ≥ 0.44) or fall back to a simple generator.
import { uuidv4 } from "https://jslib.k6.io/k6-utils/1.4.0/index.js";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const API_KEY = __ENV.API_KEY;
if (!API_KEY) {
  throw new Error("API_KEY env var is required");
}

const failRate = new Rate("failed_requests");
const appealTextLatency = new Trend("appeal_text_latency");
const appealGetLatency = new Trend("appeal_get_latency");

export const options = {
  scenarios: {
    smoke: {
      executor: "constant-vus",
      vus: 1,
      duration: "30s",
      exec: "appealFlow",
      tags: { scenario: "smoke" },
    },
    spike: {
      executor: "ramping-vus",
      startVUs: 0,
      startTime: "45s",
      stages: [
        { duration: "30s", target: 200 },
        { duration: "1m", target: 200 },
        { duration: "30s", target: 0 },
      ],
      exec: "appealFlow",
      tags: { scenario: "spike" },
    },
  },
  thresholds: {
    // Overall request latency budget
    http_req_duration: [
      "p(95)<5000",        // 5s @ p95 (LLM calls are the long pole)
      "p(99)<15000",       // 15s @ p99
    ],
    // Error budget
    failed_requests: ["rate<0.05"],
    appeal_text_latency: ["p(95)<10000"],
    appeal_get_latency: ["p(95)<400"],
    // Specific-endpoint error rate
    'http_req_failed{scenario:smoke}': ["rate<0.01"],
  },
};

const denialSample = `
Blue Cross Blue Shield
Date: December 1, 2024
RE: Denial of Prior Authorization
Member ID: MEMLT${Math.floor(Math.random() * 1000000)}
Claim Number: CLM-LT-${Math.floor(Math.random() * 1000000)}

Procedure: 99213 - Office visit, established patient
Diagnosis: M54.5 - Low back pain

Reason for Denial: The requested service does not meet medical necessity
criteria based on the clinical information provided.

You have the right to appeal this decision within 180 days of this notice.
`;

export function appealFlow() {
  const headers = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json",
    "Idempotency-Key": uuidv4(),
  };

  // 1. Generate from text
  const r1 = http.post(
    `${BASE_URL}/api/v1/appeals/text`,
    JSON.stringify({ denial_text: denialSample }),
    { headers, tags: { endpoint: "appeal_text" } }
  );
  appealTextLatency.add(r1.timings.duration);
  const ok1 = check(r1, {
    "text: 200 or 429": (r) => r.status === 200 || r.status === 429,
    "text: has appeal_id on 200": (r) => r.status !== 200 || !!r.json("appeal_id"),
  });
  failRate.add(!ok1);
  if (r1.status !== 200) {
    sleep(1);
    return;
  }
  const appealId = r1.json("appeal_id");

  // 2. Retrieve — cheap path, tight latency budget
  const r2 = http.get(
    `${BASE_URL}/api/v1/appeals/${appealId}`,
    { headers, tags: { endpoint: "appeal_get" } }
  );
  appealGetLatency.add(r2.timings.duration);
  failRate.add(!check(r2, { "get: 200": (r) => r.status === 200 }));

  sleep(Math.random() * 2);
}
