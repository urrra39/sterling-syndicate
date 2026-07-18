"""Widen leads.url to Text for field-level encryption.

Lead.raw_text and Contract.execution_draft are already Text (unbounded), so they
hold Fernet ciphertext without change. Lead.url was String(2048); Fernet output is
~3x the plaintext length, so widen it to Text to avoid truncating encrypted URLs.
Legacy plaintext rows stay valid (decrypt_field passes them through).

Revision ID: 0012_encrypt_lead_fields
Revises: 0011_user_role
Create Date: 2026-07-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_encrypt_lead_fields"
down_revision: Union[str, None] = "0011_user_role"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("leads") as batch:
        batch.alter_column(
            "url",
            existing_type=sa.String(length=2048),
            type_=sa.Text(),
            existing_nullable=True,
        )


def downgrade() -> None:
    # NOTE: narrowing back can truncate ciphertext written while encryption was on.
    with op.batch_alter_table("leads") as batch:
        batch.alter_column(
            "url",
            existing_type=sa.Text(),
            type_=sa.String(length=2048),
            existing_nullable=True,
        )
