from __future__ import annotations

"""Lead model — ingested job posts scored against the user profile."""

import uuid
from datetime import datetime
from enum import Enum
from typing import List, Optional

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.encryption import EncryptedStr
from app.core.types import GUID, JSONList


class PipelineStatus(str, Enum):
    NEW = "new"
    DRAFTING = "drafting"
    SENT = "sent"
    NEGOTIATING = "negotiating"
    WON = "won"
    LOST = "lost"
    REJECTED_TOS_VIOLATION = "rejected_tos_violation"
    PENDING_PAYMENT_VERIFICATION = "pending_payment_verification"
    IN_PROGRESS = "in_progress"
    PAUSED_FOR_BUDGET_EXTENSION = "paused_for_budget_extension"
    PAUSED_FOR_CAPTCHA = "paused_for_captcha"
    REJECTED_BY_SAST = "rejected_by_sast"
    DELIVERED = "delivered"
    PAID = "paid"
    ARCHIVED = "archived"


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # Sensitive free text / links captured from external job posts — encrypted at
    # rest via envelope Fernet (EncryptedStr). Neither column is used in equality
    # WHERE filters (dedup keys off content_hash), so encryption is transparent.
    raw_text: Mapped[str] = mapped_column(EncryptedStr(), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(EncryptedStr(), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    embedding: Mapped[Optional[List[float]]] = mapped_column(JSONList(Float), nullable=True)
    match_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True, index=True)
    pipeline_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PipelineStatus.NEW.value, index=True
    )
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    tos_rejection_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    proposals = relationship("Proposal", back_populates="lead", cascade="all, delete-orphan")
    conversations = relationship(
        "Conversation", back_populates="lead", cascade="all, delete-orphan"
    )
    contract = relationship(
        "Contract", back_populates="lead", uselist=False, cascade="all, delete-orphan"
    )
