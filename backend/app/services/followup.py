from __future__ import annotations

"""Automated follow-up (48h) + archive timeout (7d).

Never auto-sends to clients — only creates outgoing_draft rows for human review.
"""

import logging
import threading
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.lead import Lead, PipelineStatus
from app.models.proposal import Conversation, Proposal
from app.models.user import User

logger = logging.getLogger("sterling.followup")

FOLLOW_UP_LABEL = "auto_follow_up_48h"

FOLLOW_UP_STATUSES = frozenset(
    {
        PipelineStatus.SENT.value,
        PipelineStatus.NEGOTIATING.value,
    }
)

# Never auto-archive active money / delivery work
PROTECTED_FROM_ARCHIVE = frozenset(
    {
        PipelineStatus.WON.value,
        PipelineStatus.PENDING_PAYMENT_VERIFICATION.value,
        PipelineStatus.IN_PROGRESS.value,
        PipelineStatus.PAUSED_FOR_BUDGET_EXTENSION.value,
        PipelineStatus.PAUSED_FOR_CAPTCHA.value,
        PipelineStatus.DELIVERED.value,
        PipelineStatus.PAID.value,
        PipelineStatus.ARCHIVED.value,
        PipelineStatus.REJECTED_TOS_VIOLATION.value,
    }
)

_stop = threading.Event()
_thread: Optional[threading.Thread] = None


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def last_activity_at(db: Session, lead: Lead) -> datetime:
    """Latest real activity — ignores auto follow-up drafts so they don't reset the 7d clock."""
    candidates: List[datetime] = [_aware(lead.ingested_at) or datetime.now(timezone.utc)]

    last_conv = db.scalar(
        select(func.max(Conversation.created_at)).where(
            Conversation.lead_id == lead.id,
            Conversation.label.is_distinct_from(FOLLOW_UP_LABEL),
        )
    )
    if last_conv is not None:
        candidates.append(_aware(last_conv))  # type: ignore[arg-type]

    last_prop = db.scalar(
        select(func.max(func.coalesce(Proposal.sent_at, Proposal.created_at))).where(
            Proposal.lead_id == lead.id
        )
    )
    if last_prop is not None:
        candidates.append(_aware(last_prop))  # type: ignore[arg-type]

    return max(c for c in candidates if c is not None)


def silence_hours(db: Session, lead: Lead, *, now: Optional[datetime] = None) -> float:
    now = now or datetime.now(timezone.utc)
    last = last_activity_at(db, lead)
    return max(0.0, (now - last).total_seconds() / 3600.0)


def already_has_pending_follow_up(db: Session, lead_id: UUID) -> bool:
    """True if a 48h follow-up draft exists after the last incoming message."""
    last_incoming = db.scalar(
        select(func.max(Conversation.created_at)).where(
            Conversation.lead_id == lead_id,
            Conversation.direction == "incoming",
        )
    )
    q = select(Conversation.id).where(
        Conversation.lead_id == lead_id,
        Conversation.label == FOLLOW_UP_LABEL,
    )
    if last_incoming is not None:
        q = q.where(Conversation.created_at > last_incoming)
    return db.scalar(q.limit(1)) is not None


def polite_follow_up_body(*, lead_title: str, user_name: str) -> str:
    title = (lead_title or "your project").strip()[:120]
    return (
        f"Hi — just floating this back to the top of your inbox regarding {title}. "
        f"Happy to answer any questions or adjust the approach if helpful. "
        f"No rush either way.\n\nBest,\n{user_name}"
    )


def should_draft_follow_up(
    *,
    status: str,
    hours_silent: float,
    has_follow_up: bool,
    follow_up_after_hours: float,
) -> bool:
    if status not in FOLLOW_UP_STATUSES:
        return False
    if has_follow_up:
        return False
    return hours_silent >= follow_up_after_hours


def should_archive(
    *,
    status: str,
    hours_silent: float,
    archive_after_hours: float,
) -> bool:
    if status in PROTECTED_FROM_ARCHIVE:
        return False
    return hours_silent >= archive_after_hours


def process_lead(
    db: Session,
    lead: Lead,
    user: User,
    *,
    now: Optional[datetime] = None,
) -> Tuple[bool, bool]:
    """Returns (follow_up_created, archived)."""
    now = now or datetime.now(timezone.utc)
    hours = silence_hours(db, lead, now=now)
    follow_h = float(settings.follow_up_after_hours)
    archive_h = float(settings.archive_after_days) * 24.0

    followed = False
    archived = False

    if should_draft_follow_up(
        status=lead.pipeline_status,
        hours_silent=hours,
        has_follow_up=already_has_pending_follow_up(db, lead.id),
        follow_up_after_hours=follow_h,
    ):
        db.add(
            Conversation(
                lead_id=lead.id,
                direction="outgoing_draft",
                body=polite_follow_up_body(lead_title=lead.title, user_name=user.name),
                label=FOLLOW_UP_LABEL,
                generated_by="ai_generated",
            )
        )
        followed = True

    if should_archive(
        status=lead.pipeline_status,
        hours_silent=hours,
        archive_after_hours=archive_h,
    ):
        lead.pipeline_status = PipelineStatus.ARCHIVED.value
        archived = True

    return followed, archived


def run_followup_cycle(db: Session) -> dict:
    """Scan non-archived leads; draft follow-ups / archive stale ones."""
    stats = {"checked": 0, "follow_ups": 0, "archived": 0}
    users = db.scalars(select(User).where(User.is_active.is_(True)).limit(50)).all()
    for user in users:
        leads = db.scalars(
            select(Lead)
            .where(
                Lead.user_id == user.id,
                Lead.pipeline_status != PipelineStatus.ARCHIVED.value,
            )
            .limit(300)
        ).all()
        for lead in leads:
            stats["checked"] += 1
            fu, ar = process_lead(db, lead, user)
            if fu:
                stats["follow_ups"] += 1
            if ar:
                stats["archived"] += 1
    db.commit()
    return stats


def _loop() -> None:
    while not _stop.wait(settings.followup_poll_seconds):
        if settings.environment.lower() == "test":
            continue
        db = SessionLocal()
        try:
            stats = run_followup_cycle(db)
            if stats["follow_ups"] or stats["archived"]:
                logger.info("Follow-up cycle: %s", stats)
        except Exception as exc:
            logger.exception("Follow-up cycle error: %s", exc)
            db.rollback()
        finally:
            db.close()


def start_followup_scheduler() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="followup-scheduler", daemon=True)
    _thread.start()
    logger.info(
        "Follow-up scheduler started (48h draft / %sd archive, poll=%ss)",
        settings.archive_after_days,
        settings.followup_poll_seconds,
    )


def stop_followup_scheduler() -> None:
    _stop.set()
