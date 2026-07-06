"""Backfill PHI encryption for rows written before migration 002.

Migration 002 introduced `diagnosis_codes_encrypted` alongside the legacy
plaintext `diagnosis_codes` JSON column. This script copies the legacy
values into the new encrypted column so migration 003 can safely drop the
legacy one.

Idempotent: rows where `diagnosis_codes_encrypted` is already populated are
skipped. Raw SQL is used to read the legacy column because the current ORM
model no longer exposes it.

Usage:
    python -m scripts.encrypt_phi_backfill [--dry-run] [--batch-size 500]

For other PHI columns (patient_name, member_id, claim_number,
denial_reason_text, denial_text, appeal_letter) no backfill is needed because
they already have the encrypting TypeDecorator applied — any plaintext
written before the decorator existed will fail to decrypt on read and must
be re-written through the normal write path (or manually).
"""

from __future__ import annotations

import argparse
import asyncio

import structlog
from sqlalchemy import text

from src.core.database import async_session_maker
from src.core.encryption import encrypt_str

logger = structlog.get_logger()

_SELECT_SQL = text(
    "SELECT id, diagnosis_codes "
    "FROM appeals "
    "WHERE diagnosis_codes_encrypted IS NULL "
    "  AND diagnosis_codes IS NOT NULL "
    "ORDER BY created_at ASC "
    "LIMIT :limit OFFSET :offset"
)

_UPDATE_SQL = text(
    "UPDATE appeals SET diagnosis_codes_encrypted = :ct WHERE id = :id"
)


async def _backfill(batch_size: int, dry_run: bool) -> tuple[int, int]:
    rows_seen = 0
    rows_updated = 0

    async with async_session_maker() as db:
        # The SELECT's `diagnosis_codes_encrypted IS NULL` filter advances the
        # scan as rows are encrypted, so the offset stays 0. Guard against a
        # batch that makes no progress (e.g. rows whose legacy value maps to
        # None and is skipped below) — without it those rows re-select forever.
        while True:
            result = await db.execute(_SELECT_SQL, {"limit": batch_size, "offset": 0})
            batch = list(result.mappings().all())
            if not batch:
                break
            updated_before_batch = rows_updated

            for row in batch:
                rows_seen += 1
                legacy = row["diagnosis_codes"]
                if legacy is None:
                    continue
                # Column is JSON in Postgres, may come back as dict/list or str.
                if isinstance(legacy, (list, dict)):
                    import json as _json
                    as_json = _json.dumps(legacy)
                else:
                    as_json = str(legacy)
                ciphertext = encrypt_str(as_json)
                await db.execute(_UPDATE_SQL, {"ct": ciphertext, "id": row["id"]})
                rows_updated += 1

            if dry_run:
                await db.rollback()
            else:
                await db.commit()

            logger.info(
                "backfill_batch",
                rows_seen=rows_seen,
                rows_updated=rows_updated,
                dry_run=dry_run,
            )
            # We keep offset=0 because each commit moves the filter forward.
            # If dry-run, break to avoid an infinite loop.
            if dry_run:
                break
            if rows_updated == updated_before_batch:
                logger.warning(
                    "backfill_stalled",
                    detail="batch produced no updates; remaining rows are unmigratable",
                    remaining=len(batch),
                )
                break

    return rows_seen, rows_updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    seen, updated = asyncio.run(_backfill(args.batch_size, args.dry_run))
    logger.info(
        "backfill_complete",
        rows_seen=seen,
        rows_updated=updated,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
