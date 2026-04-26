"""Seed a public demo tenant + API key for the portfolio deployment.

The plaintext key written here is intentionally embedded so anyone visiting
the live demo can hit the API. NEVER reuse this script for a real tenant —
the hash you'd want in production must come from a key the operator alone
controls. Idempotent: re-running upserts the row.

Usage:
    python -m scripts.seed_demo
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from src.core.database import async_session_maker
from src.core.db_models import ApiKeyRecord
from src.core.security import hash_api_key, set_rls_context

DEMO_ORG_ID = "demo-org"
DEMO_KEY_NAME = "demo-public"
DEMO_PLAINTEXT_KEY = "pa_demo_publickey_safe_to_share_DEADBEEF"  # noqa: S105
DEMO_SCOPES = ["appeals:read", "appeals:write"]


async def seed() -> None:
    key_hash = hash_api_key(DEMO_PLAINTEXT_KEY)

    async with async_session_maker() as db:
        await set_rls_context(db, org_id=None, is_admin=True, source="seed_demo", scope="session")

        existing = (
            await db.execute(select(ApiKeyRecord).where(ApiKeyRecord.key_hash == key_hash))
        ).scalar_one_or_none()

        if existing:
            print(f"Demo key already seeded (id={existing.id}, org={existing.org_id})")
        else:
            db.add(
                ApiKeyRecord(
                    id=str(uuid.uuid4()),
                    key_hash=key_hash,
                    org_id=DEMO_ORG_ID,
                    name=DEMO_KEY_NAME,
                    scopes=DEMO_SCOPES,
                    created_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
            print("Demo key seeded.")

    print()
    print(f"  Org:    {DEMO_ORG_ID}")
    print(f"  Key:    {DEMO_PLAINTEXT_KEY}")
    print(f"  Scopes: {', '.join(DEMO_SCOPES)}")
    print()
    print("  Try it:")
    print(
        f'    curl -X POST $API_URL/api/v1/appeals/text \\\n'
        f'      -H "X-API-Key: {DEMO_PLAINTEXT_KEY}" \\\n'
        f'      -H "Content-Type: application/json" \\\n'
        f'      -d \'{{"denial_text":"<paste denial letter here>"}}\''
    )


def main() -> int:
    asyncio.run(seed())
    return 0


if __name__ == "__main__":
    sys.exit(main())
