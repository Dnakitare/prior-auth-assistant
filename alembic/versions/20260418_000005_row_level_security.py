"""Row-level security as defence-in-depth for tenant isolation.

Revision ID: 005
Revises: 004
Create Date: 2026-04-18

Policies on every tenant-scoped table require the session to have set
`app.org_id` (via `SET LOCAL app.org_id = '<org>'` or `set_config()`) to
read / write that org's rows. An admin escape hatch `app.is_admin = 'true'`
unlocks cross-tenant access for global admins.

FORCE ROW LEVEL SECURITY is applied so even the table owner is subject.

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


_TENANT_POLICY_CLAUSE = """
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
"""


# audit_log allows null org_id (e.g. login failures with no principal) for
# admin writes. Tenants only see their own org's rows.
_AUDIT_POLICY_CLAUSE = """
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
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table in _TABLES_WITH_ORG_ID:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} {_TENANT_POLICY_CLAUSE}")

    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON audit_log {_AUDIT_POLICY_CLAUSE}")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table in _TABLES_WITH_ORG_ID + ["audit_log"]:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
