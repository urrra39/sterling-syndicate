"""Idempotency hash on leads + unique constraint.

Revision ID: 0004_idempotency
Revises: 0003_agent_memory
Create Date: 2026-07-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_idempotency"
down_revision: Union[str, None] = "0003_agent_memory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("content_hash", sa.String(length=64), nullable=True))
    op.create_index("ix_leads_content_hash", "leads", ["content_hash"])
    op.create_index(
        "uq_leads_user_content_hash",
        "leads",
        ["user_id", "content_hash"],
        unique=True,
        postgresql_where=sa.text("content_hash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_leads_user_content_hash", table_name="leads")
    op.drop_index("ix_leads_content_hash", table_name="leads")
    op.drop_column("leads", "content_hash")
