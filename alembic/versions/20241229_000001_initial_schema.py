"""Initial schema for Prior Auth Assistant

Revision ID: 001
Revises:
Create Date: 2024-12-29

Creates the core tables:
- payers: Insurance payer information
- appeals: Generated appeal records
- payer_rules: Payer-specific appeal rules
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create DenialReason enum type
    denial_reason_enum = postgresql.ENUM(
        "medical_necessity",
        "not_covered",
        "out_of_network",
        "missing_information",
        "experimental_treatment",
        "step_therapy_required",
        "quantity_limit",
        "prior_auth_required",
        "other",
        name="denialreason",
        create_type=True,
    )
    denial_reason_enum.create(op.get_bind(), checkfirst=True)

    # Create payers table
    op.create_table(
        "payers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("aliases", sa.JSON(), default=list),
        sa.Column("appeals_address", sa.Text(), nullable=True),
        sa.Column("appeals_fax", sa.String(20), nullable=True),
        sa.Column("appeals_phone", sa.String(20), nullable=True),
        sa.Column("appeals_portal_url", sa.String(500), nullable=True),
        sa.Column("appeal_deadline_days", sa.Integer(), default=180),
        sa.Column("expedited_review_available", sa.Boolean(), default=True),
        sa.Column("medical_necessity_requirements", sa.JSON(), default=dict),
        sa.Column("step_therapy_requirements", sa.JSON(), default=dict),
        sa.Column("documentation_requirements", sa.JSON(), default=dict),
        sa.Column("total_appeals", sa.Integer(), default=0),
        sa.Column("successful_appeals", sa.Integer(), default=0),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # Create appeals table
    op.create_table(
        "appeals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("patient_name", sa.String(255), nullable=True),
        sa.Column("member_id", sa.String(100), nullable=True),
        sa.Column("payer_name", sa.String(255), nullable=True),
        sa.Column("payer_id", sa.String(36), sa.ForeignKey("payers.id"), nullable=True),
        sa.Column(
            "denial_reason",
            postgresql.ENUM(
                "medical_necessity",
                "not_covered",
                "out_of_network",
                "missing_information",
                "experimental_treatment",
                "step_therapy_required",
                "quantity_limit",
                "prior_auth_required",
                "other",
                name="denialreason",
                create_type=False,
            ),
            nullable=False,
            server_default="other",
        ),
        sa.Column("denial_reason_text", sa.Text(), nullable=True),
        sa.Column("denial_date", sa.DateTime(), nullable=True),
        sa.Column("claim_number", sa.String(100), nullable=True),
        sa.Column("procedure_codes", sa.JSON(), default=list),
        sa.Column("diagnosis_codes", sa.JSON(), default=list),
        sa.Column("appeal_letter", sa.Text(), nullable=False),
        sa.Column("required_documents", sa.JSON(), default=list),
        sa.Column("confidence_score", sa.Float(), default=0.0),
        sa.Column("denial_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="generated"),
    )

    # Create payer_rules table
    op.create_table(
        "payer_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("payer_id", sa.String(36), sa.ForeignKey("payers.id"), nullable=False),
        sa.Column("procedure_code", sa.String(20), nullable=True),
        sa.Column("diagnosis_code", sa.String(20), nullable=True),
        sa.Column(
            "denial_reason",
            postgresql.ENUM(
                "medical_necessity",
                "not_covered",
                "out_of_network",
                "missing_information",
                "experimental_treatment",
                "step_therapy_required",
                "quantity_limit",
                "prior_auth_required",
                "other",
                name="denialreason",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("rule_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("required_documentation", sa.JSON(), default=list),
        sa.Column("appeal_tips", sa.JSON(), default=list),
        sa.Column("times_used", sa.Integer(), default=0),
        sa.Column("success_count", sa.Integer(), default=0),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Create indexes for common queries
    op.create_index("ix_appeals_created_at", "appeals", ["created_at"])
    op.create_index("ix_appeals_payer_id", "appeals", ["payer_id"])
    op.create_index("ix_appeals_status", "appeals", ["status"])
    op.create_index("ix_payer_rules_payer_id", "payer_rules", ["payer_id"])


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_payer_rules_payer_id", table_name="payer_rules")
    op.drop_index("ix_appeals_status", table_name="appeals")
    op.drop_index("ix_appeals_payer_id", table_name="appeals")
    op.drop_index("ix_appeals_created_at", table_name="appeals")

    # Drop tables
    op.drop_table("payer_rules")
    op.drop_table("appeals")
    op.drop_table("payers")

    # Drop enum type
    op.execute("DROP TYPE IF EXISTS denialreason")
