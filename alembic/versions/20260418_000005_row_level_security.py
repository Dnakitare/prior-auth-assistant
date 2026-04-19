"""Row-level security as defence-in-depth for tenant isolation.

Revision ID: 005
Revises: 004
Create Date: 2026-04-18

Policies on every tenant-scoped table require the session to have set
`app.org_id` (via `SET LOCAL app.org_id = '<org>'` or `set_config()`) to
read / write that org's rows. An admin escape hatch `app.is_admin = 'true'`
unlocks cross-tenant access for global admins.

FORCE ROW LEVEL SECURITY is applied so even the table owner is subject.
Alembic migrations run with their own session and should set
`app.is_admin = 'true'` before any data operations; this migration doesn't
touch data so no bypass is required here.

Postgres-only. SQLite tests skip this migration because tests don't run
alembic; they use SQLAlchemy metadata.create_all and SQLite ignores RLS.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES_WITH_ORG_ID = [
    "appeals",
    "webhook_endpoints",
    "webhook_deliveries",
    "api_keys",
    "org_quotas",
]


def _policy_sql(table: str) -> str:
    """Policy predicate: admin bypass OR org_id matches the session GUC.

    Empty `app.org_id` is treated as "no org in context" and denies access,
    which is the fail-closed default.
    """
    return f"""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies WHERE schemaname = current_schema()
              AND tablename = '{table}' AND policyname = 'tenant_isolation'
        ) THEN
            EXECUTE $POLICY$
                CREATE POLICY tenant_isolation ON {table}
                USING (
                    current_setting('app.is_admin', true) = 'true'
                    OR (
                        current_setting('app.org_id', true) <> ''
                        AND org_id = current_setting('app.org_id', true)
                    )
                )
                WITH CHECK (
                    current_setting('app.is_admin', true) = 'true'
                    OR (
                        current_setting('app.org_id', true) <> ''
                        AND org_id = current_setting('app.org_id', true)
                    )
                )
            $POLICY$;
        END IF;
    END
    $$;
    """


def _audit_policy_sql() -> str:
    """audit_log allows nullable org_id (e.g. login failures with no principal)
    to be read by admins only; scoped rows follow the usual tenant rule.
    """
    return """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies WHERE schemaname = current_schema()
              AND tablename = 'audit_log' AND policyname = 'tenant_isolation'
        ) THEN
            EXECUTE $POLICY$
                CREATE POLICY tenant_isolation ON audit_log
                USING (
                    current_setting('app.is_admin', true) = 'true'
                    OR (
                        current_setting('app.org_id', true) <> ''
                        AND org_id = current_setting('app.org_id', true)
                    )
                )
                WITH CHECK (
                    current_setting('app.is_admin', true) = 'true'
                    OR (
                        current_setting('app.org_id', true) <> ''
                        AND (org_id IS NULL OR org_id = current_setting('app.org_id', true))
                    )
                )
            $POLICY$;
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    # Postgres-only; skip cleanly on SQLite (alembic won't be pointed at sqlite
    # in production, but this keeps the migration portable for local fiddling).
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table in _TABLES_WITH_ORG_ID:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(_policy_sql(table))

    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY")
    op.execute(_audit_policy_sql())


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table in _TABLES_WITH_ORG_ID + ["audit_log"]:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
