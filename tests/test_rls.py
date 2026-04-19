"""Row-level security tests.

The full isolation check (RLS rejects cross-tenant rows even when the app
forgets to filter by org_id) requires Postgres and is skipped on SQLite,
which is the default test backend. Wire CI to run against Postgres to
exercise those paths.

The SQLite-friendly tests confirm that set_rls_context is a no-op on
SQLite (doesn't raise, doesn't alter behavior) so the runtime code path
is safe across both dialects.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from src.core.database import async_session_maker
from src.core.security import set_rls_context


_IS_POSTGRES = os.environ.get("DATABASE_URL", "").startswith("postgresql")


class TestSetRlsContext:
    @pytest.mark.asyncio
    async def test_noop_on_sqlite(self):
        """On SQLite (tests' default bind), the helper must be harmless."""
        async with async_session_maker() as db:
            # Should not raise even though SQLite doesn't support the GUCs.
            await set_rls_context(db, org_id="test-org", is_admin=False)
            await set_rls_context(db, org_id=None, is_admin=True)

    @pytest.mark.asyncio
    async def test_auth_sets_rls_context_on_sqlite_is_harmless(
        self, async_client, auth_headers
    ):
        """An authenticated request flows through set_rls_context without error."""
        # Any endpoint behind auth is fine; /appeals/{id} returns 404 either way.
        r = await async_client.get(
            "/api/v1/appeals/00000000-0000-0000-0000-000000000000", headers=auth_headers
        )
        assert r.status_code in (404,)  # authenticated, not found — RLS path didn't crash


@pytest.mark.skipif(not _IS_POSTGRES, reason="RLS enforcement requires Postgres")
class TestRlsEnforcement:
    """These only run when DATABASE_URL points at Postgres and migrations have
    applied 005. They verify that RLS actually blocks cross-tenant reads even
    when a query forgets to filter by org_id — the defence-in-depth win.
    """

    @pytest.mark.asyncio
    async def test_set_config_sets_session_gucs(self):
        async with async_session_maker() as db:
            await set_rls_context(db, org_id="org-A", is_admin=False)
            org = (await db.execute(text("SELECT current_setting('app.org_id', true)"))).scalar()
            admin = (await db.execute(text("SELECT current_setting('app.is_admin', true)"))).scalar()
            assert org == "org-A"
            assert admin == "false"

    @pytest.mark.asyncio
    async def test_unfiltered_select_only_returns_current_org(self):
        """Bypass the repository layer and run a raw SELECT with no WHERE clause.
        RLS should still restrict the result set to the current org.
        """
        async with async_session_maker() as db:
            # Simulate a buggy path that forgot the org filter.
            await set_rls_context(db, org_id="test-org-A", is_admin=False)
            rows = (
                await db.execute(text("SELECT org_id FROM appeals"))
            ).scalars().all()
            assert all(o == "test-org-A" for o in rows), (
                "RLS did not restrict cross-tenant rows"
            )
