"""CRM tables: leads, proposals, conversations, contracts, deliverables.

Revision ID: 0002_crm
Revises: 0001_initial
Create Date: 2026-07-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_crm"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("title", sa.String(500), nullable=False, server_default=""),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("url", sa.String(2048), nullable=True),
        sa.Column("category", sa.String(120), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("embedding", postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("pipeline_status", sa.String(32), nullable=False, server_default="new"),
    )
    op.create_index("ix_leads_user_id", "leads", ["user_id"])
    op.create_index("ix_leads_match_score", "leads", ["match_score"])
    op.create_index("ix_leads_pipeline_status", "leads", ["pipeline_status"])

    op.create_table(
        "proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("draft_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("generated_by", sa.String(32), nullable=False, server_default="ai_generated"),
        sa.Column("tone", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_proposals_lead_id", "proposals", ["lead_id"])

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("direction", sa.String(32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("label", sa.String(120), nullable=True),
        sa.Column("generated_by", sa.String(32), nullable=False, server_default="human"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_conversations_lead_id", "conversations", ["lead_id"])

    op.create_table(
        "contracts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("agreed_scope", sa.Text(), nullable=False),
        sa.Column("agreed_price", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "deliverables",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("checklist", postgresql.ARRAY(sa.String(255)), nullable=False, server_default="{}"),
    )
    op.create_index("ix_deliverables_contract_id", "deliverables", ["contract_id"])


def downgrade() -> None:
    op.drop_index("ix_deliverables_contract_id", table_name="deliverables")
    op.drop_table("deliverables")
    op.drop_table("contracts")
    op.drop_index("ix_conversations_lead_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_proposals_lead_id", table_name="proposals")
    op.drop_table("proposals")
    op.drop_index("ix_leads_pipeline_status", table_name="leads")
    op.drop_index("ix_leads_match_score", table_name="leads")
    op.drop_index("ix_leads_user_id", table_name="leads")
    op.drop_table("leads")
