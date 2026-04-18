"""Drop legacy plaintext diagnosis_codes column.

Revision ID: 003
Revises: 002
Create Date: 2026-04-18

Pre-requisite: scripts/encrypt_phi_backfill.py has been run against this
database so that every row's diagnosis_codes_encrypted column is populated
from the legacy JSON values. This migration removes the plaintext column.

Downgrade re-adds the column as empty; it does NOT restore the legacy
plaintext values (that data is irretrievable from ciphertext without the
encryption keys, which is the point of encrypting it).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("appeals", "diagnosis_codes")


def downgrade() -> None:
    op.add_column(
        "appeals",
        sa.Column("diagnosis_codes", sa.JSON(), nullable=True),
    )
