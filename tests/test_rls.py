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
    async def test_set_config_sets_org_guc_only(self):
        """set_rls_context sets app.org_id and — since migration 006 — never
        writes an admin GUC (the policies no longer honor one)."""
        async with async_session_maker() as db:
            await set_rls_context(db, org_id="org-A", is_admin=False)
            org = (await db.execute(text("SELECT current_setting('app.org_id', true)"))).scalar()
            admin = (await db.execute(text("SELECT current_setting('app.is_admin', true)"))).scalar()
            assert org == "org-A"
            assert admin in (None, "")  # GUC never set by the app anymore

    @pytest.mark.asyncio
    async def test_client_settable_admin_guc_does_not_bypass_rls(self):
        """The old escape hatch: any connected role could SET app.is_admin.
        Migration 006 removed the policy branch that honored it — flipping
        the GUC must no longer widen visibility beyond the org context."""
        async with async_session_maker() as db:
            await set_rls_context(db, org_id="test-org-A", is_admin=False)
            # Attacker move: set the GUC directly, no privilege required.
            await db.execute(text("SELECT set_config('app.is_admin', 'true', true)"))
            rows = (
                await db.execute(text("SELECT org_id FROM appeals"))
            ).scalars().all()
            assert all(o == "test-org-A" for o in rows), (
                "app.is_admin GUC still bypasses RLS — migration 006 not applied?"
            )

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

            if not all(o == "test-org-A" for o in rows):
                # Gather diagnostics so future runs debug themselves.
                org_guc = (await db.execute(
                    text("SELECT current_setting('app.org_id', true)")
                )).scalar()
                admin_guc = (await db.execute(
                    text("SELECT current_setting('app.is_admin', true)")
                )).scalar()
                rls_state = (await db.execute(text(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relname='appeals'"
                ))).first()
                policies = (await db.execute(text(
                    "SELECT policyname, cmd, qual "
                    "FROM pg_policies WHERE tablename='appeals'"
                ))).all()
                current_user = (await db.execute(text("SELECT current_user"))).scalar()
                is_super = (await db.execute(text(
                    "SELECT rolsuper FROM pg_roles WHERE rolname=current_user"
                ))).scalar()
                raise AssertionError(
                    "RLS did not restrict cross-tenant rows\n"
                    f"  org_guc={org_guc!r} admin_guc={admin_guc!r}\n"
                    f"  rls_enabled={rls_state} rows={rows}\n"
                    f"  policies={policies}\n"
                    f"  current_user={current_user} rolsuper={is_super}"
                )
