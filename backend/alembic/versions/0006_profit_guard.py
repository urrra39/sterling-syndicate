"""Profit guard + adaptive quality fields on contracts.

Revision ID: 0006_profit_guard
Revises: 0005_payment_kill_switch
Create Date: 2026-07-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_profit_guard"
down_revision: Union[str, None] = "0005_payment_kill_switch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "contracts",
        sa.Column("effort_level", sa.String(length=16), nullable=False, server_default="medium"),
    )
    op.add_column(
        "contracts",
        sa.Column("max_api_budget", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "contracts",
        sa.Column("cumulative_api_cost", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "contracts",
        sa.Column(
            "budget_warning_sent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("contracts", sa.Column("execution_draft", sa.Text(), nullable=True))
    op.add_column(
        "contracts",
        sa.Column("qa_status", sa.String(length=32), nullable=False, server_default="pending"),
    )
    op.add_column(
        "contracts",
        sa.Column("completeness_pct", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "contracts",
        sa.Column("emergency_extensions", sa.Integer(), nullable=False, server_default="0"),
    )
    # Backfill budgets for verified contracts at the hard 10% of revenue cap
    # (must match MEDIUM_RATIO/HIGH_RATIO in profit_guard.py — init_budget only
    # recomputes when max_api_budget <= 0, so a wrong constant here sticks forever).
    op.execute(
        "UPDATE contracts SET max_api_budget = agreed_price * 0.10 "
        "WHERE is_payment_verified = true AND max_api_budget = 0"
    )


def downgrade() -> None:
    for col in (
        "emergency_extensions",
        "completeness_pct",
        "qa_status",
        "execution_draft",
        "budget_warning_sent",
        "cumulative_api_cost",
        "max_api_budget",
        "effort_level",
    ):
        op.drop_column("contracts", col)
