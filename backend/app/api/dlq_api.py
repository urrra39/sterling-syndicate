from __future__ import annotations

"""DLQ inspection endpoints (read-only + manual requeue)."""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.models.dlq import DeadLetterTask

router = APIRouter()


def _to_public(task: DeadLetterTask) -> "DLQPublic":
    return DLQPublic(
        id=task.id,
        lead_id=task.lead_id,
        task_type=task.task_type,
        attempts=task.attempts,
        max_attempts=task.max_attempts,
        status=task.status,
        last_error=task.last_error,
        next_retry_at=task.next_retry_at.isoformat() if task.next_retry_at else None,
    )


class DLQPublic(BaseModel):
    id: UUID
    lead_id: Optional[UUID] = None
    task_type: str
    attempts: int
    max_attempts: int
    status: str
    last_error: Optional[str] = None
    next_retry_at: Optional[str] = None

    model_config = {"from_attributes": True}


@router.get("/dlq", response_model=List[DLQPublic])
def list_dlq(
    db: DbSession,
    user: CurrentUser,
    status_filter: Optional[str] = None,
) -> List[DLQPublic]:
    stmt = select(DeadLetterTask).where(DeadLetterTask.user_id == user.id)
    if status_filter:
        stmt = stmt.where(DeadLetterTask.status == status_filter)
    stmt = stmt.order_by(DeadLetterTask.created_at.desc()).limit(50)
    rows = db.scalars(stmt).all()
    out: List[DLQPublic] = []
    for r in rows:
        out.append(
            DLQPublic(
                id=r.id,
                lead_id=r.lead_id,
                task_type=r.task_type,
                attempts=r.attempts,
                max_attempts=r.max_attempts,
                status=r.status,
                last_error=r.last_error,
                next_retry_at=r.next_retry_at.isoformat() if r.next_retry_at else None,
            )
        )
    return out


@router.get("/dlq/{task_id}", response_model=DLQPublic)
def get_dlq(task_id: UUID, db: DbSession, user: CurrentUser) -> DLQPublic:
    task = db.get(DeadLetterTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="DLQ task not found")
    return _to_public(task)


@router.post("/dlq/{task_id}/requeue", response_model=DLQPublic)
def requeue_dlq(task_id: UUID, db: DbSession, user: CurrentUser) -> DLQPublic:
    """Reset an exhausted task back to pending so the worker retries it.

    Without this, a task exhausted by an outage longer than max_attempts is
    permanently dead — process_due only selects status=='pending'.
    """
    task = db.get(DeadLetterTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="DLQ task not found")
    if task.status != "exhausted":
        raise HTTPException(
            status_code=409, detail="Only exhausted tasks can be requeued"
        )
    task.status = "pending"
    task.attempts = 0
    task.next_retry_at = datetime.now(timezone.utc)
    task.last_error = None
    db.commit()
    db.refresh(task)
    return _to_public(task)
