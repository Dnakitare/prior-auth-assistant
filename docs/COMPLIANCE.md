# Compliance checklist

This document tracks the business / legal steps that sit alongside the
technical controls. None of these items can be closed by shipping code.
They require signed agreements, policy documents, or audit evidence.

> **Draft for legal review.** Nothing here is legal advice. The named
> regulations (HIPAA, SOC2) require your counsel and auditor's guidance on
> scope and sufficiency.

---

## Business Associate Agreements (BAA)

Under HIPAA, any vendor that processes PHI on your behalf is a "Business
Associate" and must sign a BAA. For this stack:

| Vendor | Role | BAA required? | Status | Link |
|---|---|---|---|---|
| **Anthropic** | Receives denial letter text → returns structured extraction + generated appeal. PHI passes through. | **Yes** | TODO | https://www.anthropic.com/legal/baa (contact enterprise sales) |
| **AWS (Textract)** | Receives denial letter PDFs / images → returns extracted text. PHI passes through. | **Yes** | TODO (covered under AWS BAA for eligible services) | https://aws.amazon.com/compliance/hipaa-compliance/ |
| **AWS (S3)** | Backup storage — ciphertext only. Still touched by the BAA because the bucket lives in AWS. | **Yes** | TODO (same AWS BAA) | as above |
| **AWS (CloudWatch Logs)** | Audit sink — may contain `user_id`, `ip_address`, `resource_id`. PHI is not logged but check your audit event shapes. | **Yes** | TODO | as above |
| **PostgreSQL host** | Primary PHI store. Self-hosted on AWS RDS = covered by AWS BAA. Managed elsewhere = separate BAA. | **Yes** | TODO | — |
| **Redis host** | Does NOT touch PHI (rate-limit counters + lockout IPs + session hashes). BAA not strictly required but advisable if self-hosted on a covered provider. | Situational | — | — |
| **Monitoring stack (Prometheus / Grafana)** | No PHI in metrics (labels are scrubbed). Still review your specific setup. | Situational | — | — |
| **Log aggregator (Datadog / Splunk / etc.)** | If you ship application logs: yes, BAA required. Audit the log shapes first. | **Yes if used** | TODO | — |

**Action**: obtain and file signed BAAs with Anthropic, AWS (covers
Textract, S3, CloudWatch, RDS), and any third-party log or observability
provider. Record the effective date and annual review date in your GRC
system.

---

## Covered Entity vs Business Associate posture

Determine whether Prior Auth Assistant is operated **as** a covered entity
(e.g., payer, provider, clearinghouse) or **on behalf of** one (BA). This
changes the obligations:

- As a **covered entity**: you hold the HIPAA obligations directly.
- As a **business associate**: you sign BAAs with your customers
  (covered entities) and inherit obligations from them.

Most likely posture for a vendor SaaS offering: **business associate**.
A BAA template for customer onboarding should be available before the
first production tenant is onboarded. Your counsel should draft it.

---

## SOC 2 Type I / Type II preflight

SOC 2 reports attest to the design (Type I) and operating effectiveness
(Type II) of controls across five Trust Service Criteria. Security is
required; the others are often included:

- **Security** (required)
- **Availability**
- **Confidentiality**
- **Processing integrity**
- **Privacy**

### What you need before engaging an auditor

| Item | Owned by | Status |
|---|---|---|
| Written Information Security Program (ISP / ISMS) | Security lead + counsel | TODO |
| Access-control policy (who can touch prod, how access is granted / revoked) | Security lead | TODO |
| Change-management policy (how code ships to prod, approvals, rollbacks) | Engineering lead | TODO |
| Incident response plan (see `docs/RUNBOOK.md`; formalize) | Security lead | Partial — runbook in place |
| Business continuity / disaster recovery plan (see `docs/BACKUP.md`) | Ops lead | Partial — backup procedure in place |
| Vendor management (BAAs + security questionnaires for critical vendors) | Security lead | See BAA table above |
| Employee onboarding/offboarding checklist | People ops | TODO |
| Background checks for employees with prod access | People ops | TODO |
| Asset inventory (laptops, prod hosts, secrets) | Ops lead | TODO |
| Penetration test report (external, recent) | Security lead | TODO |
| Risk assessment (annual) | Security lead | TODO |
| Evidence collection automation (e.g., Vanta / Drata / Secureframe) | Ops lead | TODO — strongly recommended to avoid manual evidence work |

### Technical controls SOC2 will ask for (already in place)

- Audit logging of privileged actions: `audit_log` table + HMAC chain + CloudWatch sink.
- Encryption at rest for PHI: Fernet/MultiFernet.
- Encryption in transit: TLS required (`REQUIRE_HTTPS=true`).
- Access control: API-key hashing + JWT revocation + tenant isolation.
- Monitoring and alerting: Prometheus `/metrics` + structlog.
- Backup and restore: `scripts/backup.sh` + drill checklist.
- Change management: source-controlled migrations; no direct schema edits.

### Typical timeline

- **Type I** (point-in-time design attestation): ~3 months of policy work
  + auditor report.
- **Type II** (6-12 month operating effectiveness window): plan for a
  12-month audit window after Type I completes.

### Recommended sequence

1. Sign BAAs with Anthropic + AWS first (unblocks production PHI usage).
2. Engage a SOC 2 platform (Vanta/Drata/Secureframe) for evidence
   automation.
3. Publish policies (above).
4. Commission Type I audit.
5. Operate controls for the Type II window; commission Type II audit.

---

## Records retention

| Record | Minimum retention | Where stored |
|---|---|---|
| `appeals` (PHI) | Per state law and customer contract. Default to 6 years (HIPAA minimum for designated record sets). | PostgreSQL (encrypted) |
| `audit_log` | 6 years (HIPAA §164.316(b)) | PostgreSQL + CloudWatch (WORM retention-locked) |
| Backups | Aligned with above; 7 years default in `docs/BACKUP.md` | S3 Object Lock |
| Email / ticket correspondence with PHI | Per contract; default 6 years | Your ticketing system — must have a BAA |

---

## Breach notification

See `docs/RUNBOOK.md` section 5. The technical playbook is there; the
**legal** notification workflow (who sends, to whom, within what window,
with what content) belongs in counsel's breach response plan.

Headline numbers for reference:

- HHS notification within 60 days (§164.408).
- Individual notification within 60 days of discovery (§164.404).
- Media notification if >500 residents in a state affected (§164.406).
