"""TOS / compliance + DLQ + sandbox fields.

Revision ID: 0007_resilience
Revises: 0006_profit_guard
Create Date: 2026-07-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_resilience"
down_revision: Union[str, None] = "0006_profit_guard"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("tos_rejection_reason", sa.String(length=500), nullable=True),
    )
    op.create_table(
        "dead_letter_tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("lead_id", sa.UUID(), nullable=True),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dead_letter_tasks_status", "dead_letter_tasks", ["status"])
    op.create_index("ix_dead_letter_tasks_next_retry", "dead_letter_tasks", ["next_retry_at"])


def downgrade() -> None:
    op.drop_index("ix_dead_letter_tasks_next_retry", table_name="dead_letter_tasks")
    op.drop_index("ix_dead_letter_tasks_status", table_name="dead_letter_tasks")
    op.drop_table("dead_letter_tasks")
    op.drop_column("leads", "tos_rejection_reason")
