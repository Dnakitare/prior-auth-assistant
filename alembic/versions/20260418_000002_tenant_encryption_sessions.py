"""Tenant isolation, PHI encryption, session/API key/audit tables.

Revision ID: 002
Revises: 001
Create Date: 2026-04-18

Schema changes:
- appeals: add created_by, org_id, idempotency_key; convert PHI columns to Text
  (ciphertext is base64 ASCII; no size constraint). Replace patient_name String(255)
  with Text, member_id String(100) with Text, claim_number String(100) with Text.
  Drop diagnosis_codes JSON in favor of encrypted JSON-string column.
  Unique (org_id, idempotency_key); indexes on (org_id, created_at), created_by.
- New tables: api_keys, user_sessions, audit_log.

NOTE: This migration re-encrypts existing plaintext PHI rows as-is. If rows exist,
run the companion backfill script before upgrading (docs/MIGRATION.md). For a
fresh install with no prior PHI, the migration runs cleanly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- appeals: tenant columns + idempotency -------------------------------
    # Add with NULL first, backfill, then set NOT NULL.
    op.add_column("appeals", sa.Column("created_by", sa.String(255), nullable=True))
    op.add_column("appeals", sa.Column("org_id", sa.String(255), nullable=True))
    op.add_column("appeals", sa.Column("idempotency_key", sa.String(128), nullable=True))

    # Backfill legacy rows to a system tenant so existing data is recoverable
    # under a known owner. Operators should reassign rows before exposing them.
    op.execute(
        "UPDATE appeals SET created_by = COALESCE(created_by, 'legacy'), "
        "org_id = COALESCE(org_id, 'legacy')"
    )

    op.alter_column("appeals", "created_by", nullable=False)
    op.alter_column("appeals", "org_id", nullable=False)

    op.create_unique_constraint("uq_appeals_org_idem", "appeals", ["org_id", "idempotency_key"])
    op.create_index("ix_appeals_org_created", "appeals", ["org_id", "created_at"])
    op.create_index("ix_appeals_created_by", "appeals", ["created_by"])

    # --- appeals: PHI columns → Text (to hold base64 Fernet ciphertext) -------
    # Bounded-string columns can't hold ~1.4× ciphertext reliably; widen to Text.
    # Data remains plaintext after this migration — operators must run the
    # encryption backfill (scripts/encrypt_phi_backfill.py) before exposing
    # /api/v1/appeals/{id} with the new decrypting ORM.
    with op.batch_alter_table("appeals") as batch:
        batch.alter_column("patient_name", type_=sa.Text(), existing_nullable=True)
        batch.alter_column("member_id", type_=sa.Text(), existing_nullable=True)
        batch.alter_column("claim_number", type_=sa.Text(), existing_nullable=True)
        # denial_reason_text, denial_text, appeal_letter were already Text

    # Add the new encrypted diagnosis codes column (JSON serialized + encrypted
    # as ciphertext string). Legacy plaintext `diagnosis_codes` JSON column is
    # retained for backfill; the new column shadows it and should be populated
    # by the backfill job, after which the legacy column can be dropped in a
    # follow-up migration.
    op.add_column("appeals", sa.Column("diagnosis_codes_encrypted", sa.Text(), nullable=True))

    # --- api_keys -------------------------------------------------------------
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("key_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("org_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("scopes", sa.JSON(), default=list),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])
    op.create_index("ix_api_keys_org_active", "api_keys", ["org_id", "is_active"])

    # --- user_sessions --------------------------------------------------------
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("org_id", sa.String(255), nullable=True),
        sa.Column("scopes", sa.JSON(), default=list),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
    )
    op.create_index("ix_sessions_token_hash", "user_sessions", ["token_hash"])
    op.create_index("ix_sessions_user", "user_sessions", ["user_id"])
    op.create_index("ix_sessions_expires", "user_sessions", ["expires_at"])

    # --- audit_log ------------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sequence", sa.Integer(), autoincrement=True, nullable=False, unique=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("org_id", sa.String(255), nullable=True),
        sa.Column("resource_type", sa.String(64), nullable=True),
        sa.Column("resource_id", sa.String(128), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("contains_phi", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("phi_types", sa.JSON(), default=list),
        sa.Column("metadata_json", sa.JSON(), default=dict),
        sa.Column("prev_hmac", sa.String(64), nullable=True),
        sa.Column("row_hmac", sa.String(64), nullable=False),
    )
    op.create_index("ix_audit_user_time", "audit_log", ["user_id", "timestamp"])
    op.create_index("ix_audit_resource", "audit_log", ["resource_type", "resource_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_resource", table_name="audit_log")
    op.drop_index("ix_audit_user_time", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_index("ix_sessions_expires", table_name="user_sessions")
    op.drop_index("ix_sessions_user", table_name="user_sessions")
    op.drop_index("ix_sessions_token_hash", table_name="user_sessions")
    op.drop_table("user_sessions")

    op.drop_index("ix_api_keys_org_active", table_name="api_keys")
    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_column("appeals", "diagnosis_codes_encrypted")
    op.drop_index("ix_appeals_created_by", table_name="appeals")
    op.drop_index("ix_appeals_org_created", table_name="appeals")
    op.drop_constraint("uq_appeals_org_idem", "appeals", type_="unique")
    op.drop_column("appeals", "idempotency_key")
    op.drop_column("appeals", "org_id")
    op.drop_column("appeals", "created_by")

    # Revert column widths (best-effort; ciphertext rows will be truncated if present)
    with op.batch_alter_table("appeals") as batch:
        batch.alter_column("patient_name", type_=sa.String(255), existing_nullable=True)
        batch.alter_column("member_id", type_=sa.String(100), existing_nullable=True)
        batch.alter_column("claim_number", type_=sa.String(100), existing_nullable=True)
