"""Index dead_letter_tasks.user_id for the per-user DLQ list query.

GET /dlq filters by user_id and orders by created_at DESC. The FK column was
unindexed (Postgres does not auto-index FKs), making the only per-user read path
a sequential scan. A composite (user_id, created_at DESC) index serves the
filter + sort + LIMIT 50 in one scan.

Revision ID: 0010_dlq_user_index
Revises: 0009_encrypt_client_name
Create Date: 2026-07-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_dlq_user_index"
down_revision: Union[str, None] = "0009_encrypt_client_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_dead_letter_tasks_user_created",
        "dead_letter_tasks",
        ["user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_dead_letter_tasks_user_created", table_name="dead_letter_tasks")
