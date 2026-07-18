from __future__ import annotations

"""Scout scheduler — allowed sources only, hard-capped cadence with jitter + idempotency.

REFUSED: Playwright anti-detect marketplace scraping / login automation.
Compliance firewall runs BEFORE scoring / pipeline insert.
"""

import logging
import random
import threading
from typing import Optional

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.lead import Lead, PipelineStatus
from app.models.user import User
from app.services.agents import scout_fetch_with_jitter
from app.services.compliance import check_tos_compliance
from app.services.idempotency import begin_idempotent_insert, content_hash, insert_or_recover, release
from app.services.ingestion import RemoteOKIngestor, WeWorkRemotelyRSSIngestor
from app.services.matching import embed_text, match_score
from app.services.prompt_guard import sanitize_external_text
from app.services.semantic_extract import enrich_raw_lead_text

logger = logging.getLogger("sterling.scout")

_stop = threading.Event()
_thread: Optional[threading.Thread] = None


def _cycle_once() -> None:
    db = SessionLocal()
    try:
        users = db.scalars(select(User).where(User.is_active.is_(True)).limit(20)).all()
        for user in users:
            portfolio = (
                f"{user.name}\nSkills: {', '.join(user.skills or [])}\n"
                f"{user.portfolio_summary or ''}"
            )
            for ingestor in (
                RemoteOKIngestor(limit=5),
                WeWorkRemotelyRSSIngestor(limit=5),
            ):
                try:
                    raws = scout_fetch_with_jitter(ingestor)
                except Exception as exc:
                    logger.warning("Scout fetch failed: %s", exc)
                    continue
                for raw in raws:
                    # Isolate each item: an exception on one raw lead (bad enrich,
                    # transient embed/compliance error) must not abort the whole
                    # cycle and skip every remaining user. Prior committed leads
                    # are unaffected; rollback clears any pending-error state.
                    try:
                        title, description, _budget, category = enrich_raw_lead_text(
                            raw.title, raw.raw_text, url=raw.url, category=raw.category
                        )
                        clean = sanitize_external_text(description).clean_text
                        verdict = check_tos_compliance(f"{title}\n{clean}")
                        h = content_hash(
                            user_id=str(user.id),
                            source=raw.source,
                            url=raw.url,
                            raw_text=clean,
                        )
                        if not verdict.allowed:
                            lead = Lead(
                                user_id=user.id,
                                source=raw.source,
                                title=title[:500],
                                raw_text=clean,
                                url=raw.url,
                                category=category,
                                embedding=None,
                                match_score=0.0,
                                pipeline_status=PipelineStatus.REJECTED_TOS_VIOLATION.value,
                                content_hash=h,
                                tos_rejection_reason=verdict.reason[:500],
                            )
                            _lead, should_insert, acquired = begin_idempotent_insert(db, lead)
                            try:
                                if should_insert:
                                    insert_or_recover(db, lead)
                            finally:
                                if acquired:
                                    release(h)
                            continue
                        score = match_score(portfolio, clean)
                        # match_score is now true cosine clamped to [0,1] (was a
                        # stretched value where 0.5 == cosine 0). Keep the prior
                        # admission behaviour (drop only genuinely unrelated leads)
                        # with a low positive-signal floor instead of 0.5.
                        if score < settings.scout_min_match:
                            continue
                        lead = Lead(
                            user_id=user.id,
                            source=raw.source,
                            title=title[:500],
                            raw_text=clean,
                            url=raw.url,
                            category=category,
                            embedding=embed_text(clean),
                            match_score=score,
                            pipeline_status=PipelineStatus.NEW.value,
                            content_hash=h,
                        )
                        _lead, should_insert, acquired = begin_idempotent_insert(db, lead)
                        try:
                            if should_insert:
                                insert_or_recover(db, lead)
                        finally:
                            if acquired:
                                release(h)
                    except Exception as exc:
                        logger.warning(
                            "Scout item failed (source=%s url=%s): %s", raw.source, raw.url, exc
                        )
                        db.rollback()
                        continue
                db.commit()
    finally:
        db.close()


def _loop() -> None:
    while not _stop.is_set():
        try:
            _cycle_once()
        except Exception as exc:
            logger.exception("Scout cycle error: %s", exc)
        lo = settings.scout_interval_min_minutes * 60
        hi = settings.scout_interval_max_minutes * 60
        wait = random.uniform(lo, hi)
        _stop.wait(wait)


def start_scout_scheduler() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="scout-scheduler", daemon=True)
    _thread.start()
    logger.info(
        "Scout scheduler started (every %s–%s min, allowed sources only)",
        settings.scout_interval_min_minutes,
        settings.scout_interval_max_minutes,
    )


def stop_scout_scheduler() -> None:
    _stop.set()
