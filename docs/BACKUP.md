# Backup & Restore

HIPAA requires a contingency plan (45 CFR §164.308(a)(7)) covering backup,
disaster recovery, and emergency-mode operation. This document describes the
implementation for Prior Auth Assistant.

## Threat model

The backups contain PHI. Two scenarios we protect against:

1. **App compromise** — attacker gains RCE on API replicas. They must not
   be able to decrypt historical backups using keys the app has in memory.
2. **Backup storage compromise** — attacker gains read access to the S3
   bucket containing backup artifacts. They must not get plaintext data.

Both are addressed by:

- Encrypting backups with an **age** recipient whose private key is stored
  in a secret manager **separate** from `PHI_ENCRYPTION_KEYS` and only
  accessible to backup / DR operators, not to the application.
- Writing artifacts to an S3 bucket with **Object Lock** (WORM) and a
  compliance-mode retention period covering the regulatory minimum.

## Prerequisites

On the backup host (cron job / CI runner):

```
brew install postgresql@16 zstd age awscli      # or apt-get equivalents
aws sts get-caller-identity                     # confirm IAM
age-keygen -o /secure/path/backup.age           # generate key once, store safely
age-keygen -y /secure/path/backup.age > /secure/path/backup.pub
```

Share the public key as `BACKUP_AGE_RECIPIENT` with operators; keep the
private key in a separate vault.

## S3 bucket (one-time)

```bash
aws s3api create-bucket --bucket prior-auth-backups --region us-east-1 \
    --object-lock-enabled-for-bucket

aws s3api put-object-lock-configuration \
  --bucket prior-auth-backups \
  --object-lock-configuration '{
    "ObjectLockEnabled":"Enabled",
    "Rule":{"DefaultRetention":{"Mode":"COMPLIANCE","Days":2555}}
  }'

# Versioning is required for Object Lock.
aws s3api put-bucket-versioning --bucket prior-auth-backups \
  --versioning-configuration Status=Enabled
```

Retention days — match the regulatory window that applies (HIPAA record
retention is 6 years / 2190 days; 2555 days ≈ 7 years).

## Taking a backup

```bash
export DATABASE_URL=postgresql+asyncpg://...
export BACKUP_AGE_RECIPIENT=$(cat /secure/path/backup.pub)
export BACKUP_S3_URI=s3://prior-auth-backups/daily

./scripts/backup.sh
```

Schedule nightly via cron, SystemD timer, or a Kubernetes CronJob. The
script produces `prior-auth-db-<timestamp>.sql.zst.age` and uploads it.

## Restoring

Restores should go to a **separate** database, not production.

```bash
export RESTORE_DATABASE_URL=postgresql+asyncpg://restore-host/prior_auth_restore
export BACKUP_AGE_IDENTITY=/secure/path/backup.age

./scripts/restore.sh s3://prior-auth-backups/daily/prior-auth-db-20260418T020000Z.sql.zst.age
```

After the dump is restored, apply migrations to bring the schema to head:

```bash
DATABASE_URL="${RESTORE_DATABASE_URL}" python -m scripts.migrate upgrade head
```

## Restore drills

Run a drill **quarterly**:

1. Pick a random artifact from the last 30 days.
2. Restore to an ephemeral database.
3. Run the schema migration to head.
4. Spot-check a handful of appeal records: decrypt a PHI column via the ORM
   to verify the encryption keys and ciphertext are consistent across the
   backup boundary.
5. Drop the ephemeral database.
6. File a ticket recording the drill outcome — SOC2 and HIPAA auditors will
   ask for evidence.

## Key rotation

The age recipient used to encrypt backups can be rotated independently of
the PHI encryption keys:

1. Generate a new age key pair.
2. Update the `BACKUP_AGE_RECIPIENT` env var on the backup host.
3. Keep the old private key in cold storage until the last backup encrypted
   with it has aged out of retention.

Never combine the backup key and `PHI_ENCRYPTION_KEYS` — they protect
different threat models and must have different access control.
