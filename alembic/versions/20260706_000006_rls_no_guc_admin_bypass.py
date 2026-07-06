"""Remove the client-settable admin escape hatch from RLS policies.

Revision ID: 006
Revises: 005
Create Date: 2026-07-06

Migration 005's policies allowed cross-tenant access whenever the session
GUC `app.is_admin` was 'true'. GUCs are settable by ANY connected role with
plain `SET`/`set_config()` — no privilege needed — so a leaked runtime DSN
(or SQL injection) could flip the flag and read every tenant's rows. That
defeated the entire point of RLS as a backstop.

New model: policies check ONLY `app.org_id`. There is no in-band bypass.
Privileged paths (API-key lookup at auth time, audit writer, webhook worker,
bootstrap seeder) run on the admin engine (`DATABASE_ADMIN_URL`), whose role
carries BYPASSRLS — a *role attribute* the runtime role cannot grant itself.
The production validator now requires DATABASE_ADMIN_URL when running on
Postgres.

Postgres-only, like 005.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "006"
down_revision: Union[str, None] = "005"
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
    current_setting('app.org_id', true) <> ''
    AND org_id = current_setting('app.org_id', true)
)
WITH CHECK (
    current_setting('app.org_id', true) <> ''
    AND org_id = current_setting('app.org_id', true)
)
"""


# audit_log: tenants may read their own org's rows; tenant-context writes
# must carry the org (NULL-org rows, e.g. login failures, are written by the
# admin-engine audit writer, which bypasses RLS by role attribute).
_AUDIT_POLICY_CLAUSE = """
USING (
    current_setting('app.org_id', true) <> ''
    AND org_id = current_setting('app.org_id', true)
)
WITH CHECK (
    current_setting('app.org_id', true) <> ''
    AND (org_id IS NULL OR org_id = current_setting('app.org_id', true))
)
"""


# 005's clauses, needed to restore on downgrade.
_LEGACY_TENANT_POLICY_CLAUSE = """
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

_LEGACY_AUDIT_POLICY_CLAUSE = """
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
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} {_TENANT_POLICY_CLAUSE}")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON audit_log")
    op.execute(f"CREATE POLICY tenant_isolation ON audit_log {_AUDIT_POLICY_CLAUSE}")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table in _TABLES_WITH_ORG_ID:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} {_LEGACY_TENANT_POLICY_CLAUSE}"
        )

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON audit_log")
    op.execute(
        f"CREATE POLICY tenant_isolation ON audit_log {_LEGACY_AUDIT_POLICY_CLAUSE}"
    )
