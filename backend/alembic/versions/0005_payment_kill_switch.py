"""Payment verification kill-switch fields on contracts.

Revision ID: 0005_payment_kill_switch
Revises: 0004_idempotency
Create Date: 2026-07-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_payment_kill_switch"
down_revision: Union[str, None] = "0004_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "contracts",
        sa.Column(
            "is_payment_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "contracts",
        sa.Column("client_display_name", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "contracts",
        sa.Column("payment_claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "contracts",
        sa.Column("payment_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Existing contracts stay usable: mark verified so we don't freeze old demos.
    # Do NOT touch status — the old SET status='active' reopened terminal
    # 'completed' contracts. Active rows are already active; completed stay done.
    op.execute(
        "UPDATE contracts SET is_payment_verified = true "
        "WHERE status IN ('active', 'completed')"
    )


def downgrade() -> None:
    op.drop_column("contracts", "payment_verified_at")
    op.drop_column("contracts", "payment_claimed_at")
    op.drop_column("contracts", "client_display_name")
    op.drop_column("contracts", "is_payment_verified")
