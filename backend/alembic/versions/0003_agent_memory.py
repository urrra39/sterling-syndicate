"""Agent memory table for Reflector_Agent self-learning.

Revision ID: 0003_agent_memory
Revises: 0002_crm
Create Date: 2026-07-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_agent_memory"
down_revision: Union[str, None] = "0002_crm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_WRITER = (
    "Write concise, evidence-backed freelance proposals. "
    "Cite specific past projects from the RAG context. Never claim auto-send."
)
_DEFAULT_NEG = (
    "Hold professional boundaries on price. Offer scope trades, not silent discounts. "
    "Drafts only — human sends."
)


def upgrade() -> None:
    op.create_table(
        "agent_memory",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("writer_instructions", sa.Text(), nullable=False, server_default=_DEFAULT_WRITER),
        sa.Column("negotiator_instructions", sa.Text(), nullable=False, server_default=_DEFAULT_NEG),
        sa.Column("last_lesson", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_agent_memory_user_id", "agent_memory", ["user_id"])

    # Proposal outcome for reflector feedback
    op.add_column(
        "proposals",
        sa.Column("outcome", sa.String(32), nullable=True),
    )
    op.add_column(
        "proposals",
        sa.Column("recommended_bid", sa.Float(), nullable=True),
    )
    op.add_column(
        "proposals",
        sa.Column("rag_citations", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("proposals", "rag_citations")
    op.drop_column("proposals", "recommended_bid")
    op.drop_column("proposals", "outcome")
    op.drop_index("ix_agent_memory_user_id", table_name="agent_memory")
    op.drop_table("agent_memory")
