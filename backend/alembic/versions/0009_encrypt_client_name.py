"""Widen contracts.client_display_name to Text for field-level encryption.

Fernet ciphertext is ~3x the plaintext length, so the String(200) column can no
longer hold an encrypted display name. Widen to Text (unbounded). Existing rows
stay valid: decrypt_field passes legacy plaintext through, and new writes encrypt
when FIELD_ENCRYPTION_KEY is set.

Revision ID: 0009_encrypt_client_name
Revises: 0008_password_reset
Create Date: 2026-07-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_encrypt_client_name"
down_revision: Union[str, None] = "0008_password_reset"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table works on both Postgres (ALTER COLUMN TYPE) and SQLite
    # (table rebuild), so the widening is portable.
    with op.batch_alter_table("contracts") as batch:
        batch.alter_column(
            "client_display_name",
            existing_type=sa.String(length=200),
            type_=sa.Text(),
            existing_nullable=True,
        )


def downgrade() -> None:
    # NOTE: narrowing back to String(200) can truncate ciphertext written while
    # encryption was enabled. Only safe if FIELD_ENCRYPTION_KEY was never set.
    with op.batch_alter_table("contracts") as batch:
        batch.alter_column(
            "client_display_name",
            existing_type=sa.Text(),
            type_=sa.String(length=200),
            existing_nullable=True,
        )
