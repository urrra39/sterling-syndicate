"""Add users.role for payment-approval RBAC.

Introduces a role column ("owner" | "approver" | "member") so the ability to
release the payment kill switch can be separated from ordinary tenant login.
Existing rows default to "owner" to preserve the single-operator flow.

Revision ID: 0011_user_role
Revises: 0010_dlq_user_index
Create Date: 2026-07-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_user_role"
down_revision: Union[str, None] = "0010_dlq_user_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(length=16),
            nullable=False,
            server_default="owner",
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("role")
