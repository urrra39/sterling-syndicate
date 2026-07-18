from __future__ import annotations

"""Dead letter queue + exponential backoff for external API failures.

Max 5 retries; then webhook alert. Prevents leads stuck forever in drafting.
"""

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional
from uuid import UUID

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.dlq import DeadLetterTask
from app.models.lead import Lead, PipelineStatus
from app.services.notify import notify_api_outage

logger = logging.getLogger("sterling.dlq")

MAX_ATTEMPTS = 5
# Exponential backoff: 30s, 60s, 120s, 240s, 480s
BASE_DELAY_SEC = 30

_stop = threading.Event()
_thread: Optional[threading.Thread] = None

# Registered handlers: task_type -> callable(payload_dict) -> None (raises on failure)
_HANDLERS: Dict[str, Callable[[Dict[str, Any]], None]] = {}


def register_handler(task_type: str, fn: Callable[[Dict[str, Any]], None]) -> None:
    _HANDLERS[task_type] = fn


def backoff_seconds(attempt: int) -> int:
    """attempt is 1-based after a failure."""
    return int(BASE_DELAY_SEC * (2 ** max(0, attempt - 1)))


def enqueue(
    db,
    *,
    task_type: str,
    payload: Dict[str, Any],
    user_id: Optional[UUID] = None,
    lead_id: Optional[UUID] = None,
    error: str = "",
    max_attempts: int = MAX_ATTEMPTS,
) -> DeadLetterTask:
    """Park a failed task for retry. Optionally roll lead out of stuck drafting."""
    now = datetime.now(timezone.utc)
    task = DeadLetterTask(
        user_id=user_id,
        lead_id=lead_id,
        task_type=task_type,
        payload_json=json.dumps(payload, default=str)[:100_000],
        attempts=0,
        max_attempts=max_attempts,
        next_retry_at=now + timedelta(seconds=backoff_seconds(1)),
        last_error=(error or "")[:4000],
        status="pending",
    )
    db.add(task)
    if lead_id is not None:
        lead = db.get(Lead, lead_id)
        if lead is not None and lead.pipeline_status == PipelineStatus.DRAFTING.value:
            # Unstick — human can re-trigger; DLQ will retry
            lead.pipeline_status = PipelineStatus.NEW.value
    db.flush()
    return task


def process_due(db, *, limit: int = 10) -> int:
    """Retry due DLQ items. Returns count processed."""
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(DeadLetterTask)
        .where(
            DeadLetterTask.status == "pending",
            DeadLetterTask.next_retry_at <= now,
        )
        .order_by(DeadLetterTask.next_retry_at.asc())
        .limit(limit)
    ).all()
    done = 0
    for task in rows:
        # Commit per task so one item's failure cannot roll back the DLQ
        # bookkeeping of tasks already retried in this batch (whose handler side
        # effects committed in their own sessions and are durable).
        try:
            _retry_one(db, task)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("DLQ item %s failed", task.id)
        done += 1
    return done


def _retry_one(db, task: DeadLetterTask) -> None:
    handler = _HANDLERS.get(task.task_type)
    task.status = "processing"
    task.attempts = int(task.attempts or 0) + 1
    db.flush()

    if handler is None:
        task.last_error = f"No handler for task_type={task.task_type}"
        task.status = "exhausted"
        notify_api_outage(
            task_id=str(task.id),
            task_type=task.task_type,
            attempts=task.attempts,
            error=task.last_error,
        )
        return

    try:
        payload = json.loads(task.payload_json)
        handler(payload)
        task.status = "done"
        task.last_error = None
    except Exception as exc:
        task.last_error = str(exc)[:4000]
        if task.attempts >= task.max_attempts:
            task.status = "exhausted"
            notify_api_outage(
                task_id=str(task.id),
                task_type=task.task_type,
                attempts=task.attempts,
                error=task.last_error or "",
            )
        else:
            task.status = "pending"
            task.next_retry_at = datetime.now(timezone.utc) + timedelta(
                seconds=backoff_seconds(task.attempts + 1)
            )
            logger.warning(
                "DLQ retry %s/%s for %s failed: %s",
                task.attempts,
                task.max_attempts,
                task.id,
                exc,
            )


def _loop() -> None:
    while not _stop.wait(settings.dlq_poll_seconds):
        if settings.environment.lower() == "test":
            continue
        db = SessionLocal()
        try:
            n = process_due(db)
            if n:
                logger.info("DLQ processed %s task(s)", n)
        except Exception as exc:
            logger.exception("DLQ worker error: %s", exc)
            db.rollback()
        finally:
            db.close()


def start_dlq_worker() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="dlq-worker", daemon=True)
    _thread.start()
    logger.info("DLQ worker started (poll=%ss, max_attempts=%s)", settings.dlq_poll_seconds, MAX_ATTEMPTS)


def stop_dlq_worker() -> None:
    _stop.set()
