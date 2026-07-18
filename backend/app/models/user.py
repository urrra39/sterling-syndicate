from __future__ import annotations

"""User model — freelancer account + skill profile."""

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.types import GUID, JSONList


class User(Base):
    """Authenticated freelancer using The Sterling Syndicate."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    skills: Mapped[List[str]] = mapped_column(
        JSONList(String(64)),
        nullable=False,
        default=list,
    )
    portfolio_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    portfolio_embedding: Mapped[Optional[List[float]]] = mapped_column(
        JSONList(Float),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # RBAC: "owner" (full control, default for the single-operator model),
    # "approver" (may confirm payments / release the kill switch), or "member".
    role: Mapped[str] = mapped_column(String(16), default="owner", nullable=False)
    token_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"
