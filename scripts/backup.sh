#!/usr/bin/env bash
# Encrypted database backup.
#
# - pg_dump over the DATABASE_URL's host
# - Compressed with zstd
# - Encrypted with age(1) using a key that MUST be separate from
#   PHI_ENCRYPTION_KEYS. A breach of the app's PHI keys should not
#   compromise backups and vice versa.
# - Uploaded to an S3 bucket with Object Lock (WORM) enabled.
#
# Requires:  pg_dump, zstd, age, awscli on PATH.
# Env:       DATABASE_URL, BACKUP_AGE_RECIPIENT, BACKUP_S3_URI (s3://bucket/prefix).
#
# Restore is in scripts/restore.sh.

set -euo pipefail

: "${DATABASE_URL:?missing DATABASE_URL}"
: "${BACKUP_AGE_RECIPIENT:?missing BACKUP_AGE_RECIPIENT (age public key)}"
: "${BACKUP_S3_URI:?missing BACKUP_S3_URI}"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
artifact="prior-auth-db-${ts}.sql.zst.age"
workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT

tmp="${workdir}/${artifact}"

# pg_dump prefers a URL without the +asyncpg driver suffix.
pg_url="${DATABASE_URL/postgresql+asyncpg/postgresql}"

echo "Dumping → compressing → encrypting …"
pg_dump --format=plain --no-owner --no-privileges "${pg_url}" \
  | zstd -19 --quiet \
  | age -r "${BACKUP_AGE_RECIPIENT}" -o "${tmp}"

size_bytes="$(wc -c < "${tmp}")"
echo "Artifact: ${tmp} (${size_bytes} bytes)"

aws s3 cp "${tmp}" "${BACKUP_S3_URI%/}/${artifact}" \
    --only-show-errors \
    --metadata "source=prior-auth-assistant,created_at=${ts}"

echo "Uploaded: ${BACKUP_S3_URI%/}/${artifact}"
echo "Verify: aws s3api head-object --bucket <bucket> --key <prefix>/${artifact}"
