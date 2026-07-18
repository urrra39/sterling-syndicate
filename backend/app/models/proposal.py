from __future__ import annotations

"""Proposal, conversation, contract, deliverable models."""

import uuid
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.encryption import EncryptedStr
from app.core.types import GUID, JSONList


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    generated_by: Mapped[str] = mapped_column(String(32), nullable=False, default="ai_generated")
    tone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    outcome: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    recommended_bid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rag_citations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    lead = relationship("Lead", back_populates="proposals")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    direction: Mapped[str] = mapped_column(String(32), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    generated_by: Mapped[str] = mapped_column(String(32), nullable=False, default="human")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    lead = relationship("Lead", back_populates="conversations")


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("leads.id", ondelete="CASCADE"), unique=True
    )
    agreed_scope: Mapped[str] = mapped_column(Text, nullable=False)
    agreed_price: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_payment_verification"
    )
    is_payment_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    client_display_name: Mapped[Optional[str]] = mapped_column(EncryptedStr(), nullable=True)
    payment_claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payment_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    effort_level: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    max_api_budget: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cumulative_api_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    budget_warning_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Agent-produced work product / config — sensitive, encrypted at rest.
    execution_draft: Mapped[Optional[str]] = mapped_column(EncryptedStr(), nullable=True)
    qa_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    completeness_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    emergency_extensions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    lead = relationship("Lead", back_populates="contract")
    deliverables = relationship(
        "Deliverable", back_populates="contract", cascade="all, delete-orphan"
    )


class Deliverable(Base):
    __tablename__ = "deliverables"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("contracts.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    checklist: Mapped[List[str]] = mapped_column(JSONList(String(255)), nullable=False, default=list)

    contract = relationship("Contract", back_populates="deliverables")
