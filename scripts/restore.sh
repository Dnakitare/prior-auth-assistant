#!/usr/bin/env bash
# Restore a backup produced by scripts/backup.sh.
#
# Requires the age identity file (private key counterpart to
# BACKUP_AGE_RECIPIENT). That identity should live in a separate secret
# store from PHI_ENCRYPTION_KEYS.
#
# Env:       RESTORE_DATABASE_URL (target DB; separate from prod DATABASE_URL!),
#            BACKUP_AGE_IDENTITY (path to age key file).
# Argument:  s3://bucket/prefix/prior-auth-db-YYYYMMDDTHHMMSSZ.sql.zst.age

set -euo pipefail

: "${RESTORE_DATABASE_URL:?missing RESTORE_DATABASE_URL}"
: "${BACKUP_AGE_IDENTITY:?missing BACKUP_AGE_IDENTITY}"

s3_uri="${1:-}"
if [[ -z "${s3_uri}" ]]; then
  echo "usage: $0 s3://bucket/prefix/file.sql.zst.age" >&2
  exit 2
fi

workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT

artifact="${workdir}/$(basename "${s3_uri}")"
aws s3 cp "${s3_uri}" "${artifact}" --only-show-errors

pg_url="${RESTORE_DATABASE_URL/postgresql+asyncpg/postgresql}"

echo "Decrypting → decompressing → restoring …"
age -d -i "${BACKUP_AGE_IDENTITY}" "${artifact}" \
  | zstd -d --quiet \
  | psql "${pg_url}"

echo "Restore complete."
