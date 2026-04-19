"""Per-org quotas, webhook endpoints, webhook deliveries.

Revision ID: 004
Revises: 003
Create Date: 2026-04-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "org_quotas",
        sa.Column("org_id", sa.String(255), primary_key=True),
        sa.Column("daily_token_budget", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_used_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_used_month", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("day_window_start", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("month_window_start", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(255), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("signing_secret", sa.String(128), nullable=False),
        sa.Column("events", sa.JSON(), default=list),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivery_status", sa.Integer(), nullable=True),
    )
    op.create_index("ix_webhook_endpoints_org", "webhook_endpoints", ["org_id"])

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("endpoint_id", sa.String(36), nullable=False),
        sa.Column("org_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), default=dict),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_webhook_deliveries_endpoint", "webhook_deliveries", ["endpoint_id"])
    op.create_index("ix_webhook_deliveries_next", "webhook_deliveries", ["next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_next", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_endpoint", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")

    op.drop_index("ix_webhook_endpoints_org", table_name="webhook_endpoints")
    op.drop_table("webhook_endpoints")

    op.drop_table("org_quotas")
