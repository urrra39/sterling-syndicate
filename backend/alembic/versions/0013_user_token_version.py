"""Add users.token_version for JWT session invalidation.

The `tv` claim embedded in every access token is compared against
users.token_version on each authenticated request (see app/core/deps.py).
Bumping the column invalidates all outstanding sessions for that user
(e.g. after a password reset). This migration backfills existing rows
with 1 so that any token minted before the column existed is rejected.

Revision ID: 0013_user_token_version
Revises: 0012_encrypt_lead_fields
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_user_token_version"
down_revision: Union[str, None] = "0012_encrypt_lead_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "token_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
