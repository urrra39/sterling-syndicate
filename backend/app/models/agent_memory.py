from __future__ import annotations

"""Persistent dynamic system instructions updated by Reflector_Agent."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.types import GUID


class AgentMemory(Base):
    """Per-user instruction memory for self-learning reflector."""

    __tablename__ = "agent_memory"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    writer_instructions: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=(
            "Write concise, evidence-backed freelance proposals. "
            "Cite specific past projects from the RAG context. Never claim auto-send."
        ),
    )
    negotiator_instructions: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=(
            "Hold professional boundaries on price. Offer scope trades, not silent discounts. "
            "Drafts only — human sends."
        ),
    )
    last_lesson: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
