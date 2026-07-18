from __future__ import annotations

"""Idempotent task queue — SHA-256 content hashes prevent duplicate agent runs.

DB unique index is the source of truth. In-process set (and optional Redis)
blocks parallel workers from racing the same hash before commit.
"""

import hashlib
import logging
import threading
import time
from typing import Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger("sterling.idempotency")

_local_inflight: Set[str] = set()
_local_lock = threading.Lock()


def content_hash(*, user_id: str, source: str, url: Optional[str], raw_text: str) -> str:
    """Stable SHA-256 for a lead identity (prefer URL, else normalized text)."""
    key = (url or "").strip().lower()
    if not key:
        normalized = " ".join((raw_text or "").split()).lower()[:8000]
        key = normalized
    material = f"{user_id}|{source}|{key}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def try_acquire(hash_key: str, *, ttl_seconds: int = 600) -> bool:
    """Return True if this worker owns the hash (not already in-flight)."""
    redis_url = settings.redis_url
    if redis_url:
        try:
            import redis

            r = redis.Redis.from_url(redis_url, decode_responses=True)
            ok = r.set(f"sterling:job:{hash_key}", "1", nx=True, ex=ttl_seconds)
            return bool(ok)
        except Exception as exc:
            logger.warning("Redis acquire failed, falling back to memory: %s", exc)

    with _local_lock:
        if hash_key in _local_inflight:
            return False
        _local_inflight.add(hash_key)
        return True


def release(hash_key: str) -> None:
    redis_url = settings.redis_url
    if redis_url:
        try:
            import redis

            r = redis.Redis.from_url(redis_url, decode_responses=True)
            r.delete(f"sterling:job:{hash_key}")
        except Exception:
            pass
    with _local_lock:
        _local_inflight.discard(hash_key)


def lead_exists_by_hash(db: Session, user_id, hash_key: str) -> bool:
    from app.models.lead import Lead

    row = db.scalar(
        select(Lead.id).where(Lead.user_id == user_id, Lead.content_hash == hash_key)
    )
    return row is not None


def get_lead_by_hash(db: Session, user_id, hash_key: str):
    from app.models.lead import Lead

    return db.scalar(
        select(Lead).where(Lead.user_id == user_id, Lead.content_hash == hash_key)
    )


def begin_idempotent_insert(db: Session, lead) -> Tuple[object, bool, bool]:
    """Prepare an idempotent insert.

    Returns (lead_or_existing, should_insert, acquired_lock).
    Caller must commit if should_insert, and always release if acquired_lock.
    """
    if not lead.content_hash:
        return lead, True, False

    existing = get_lead_by_hash(db, lead.user_id, lead.content_hash)
    if existing is not None:
        return existing, False, False

    if not try_acquire(lead.content_hash):
        time.sleep(0.1)
        existing = get_lead_by_hash(db, lead.user_id, lead.content_hash)
        if existing is not None:
            return existing, False, False
        # Lost the in-flight lock but the winner hasn't committed yet. Do NOT drop
        # (that caused silent data loss if the winner then rolled back). Insert and
        # let the partial unique index uq_leads_user_content_hash arbitrate — the
        # caller catches IntegrityError to recover the real winner.
        return lead, True, False

    # Re-check after lock
    existing = get_lead_by_hash(db, lead.user_id, lead.content_hash)
    if existing is not None:
        release(lead.content_hash)
        return existing, False, False

    return lead, True, True


def insert_or_recover(db: Session, lead) -> Tuple[object, bool]:
    """Add+flush a lead inside a savepoint; on a racing duplicate, recover the winner.

    Returns (lead_or_existing, inserted). The partial unique index
    uq_leads_user_content_hash is the real arbiter — the in-flight lock is only a
    best-effort optimization, so a lost lock never drops a lead (at-least-once),
    and a true duplicate is rejected by the index (at-most-once).
    """
    from sqlalchemy.exc import IntegrityError

    try:
        with db.begin_nested():  # SAVEPOINT — a duplicate won't poison the outer txn
            db.add(lead)
            db.flush()
        return lead, True
    except IntegrityError:
        if lead.content_hash:
            existing = get_lead_by_hash(db, lead.user_id, lead.content_hash)
            if existing is not None:
                return existing, False
        raise
