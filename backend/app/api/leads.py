from __future__ import annotations

"""Lead ingestion & listing endpoints — semantic extract + idempotent persist."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.core.rate_limit import client_key, rate_limit
from app.models.lead import Lead, PipelineStatus
from app.schemas.crm import LeadCreateManual, LeadIngestRemote, LeadPublic, LeadStatusUpdate
from app.services.compliance import check_tos_compliance
from app.services.idempotency import begin_idempotent_insert, content_hash, insert_or_recover, release
from app.services.ingestion import (
    ManualPasteIngestor,
    RemoteOKIngestor,
    WeWorkRemotelyRSSIngestor,
)
from app.services.matching import embed_text, match_score
from app.services.prompt_guard import sanitize_external_text
from app.services.semantic_extract import enrich_raw_lead_text

router = APIRouter()


def _portfolio_text(user) -> str:
    skills = ", ".join(user.skills or [])
    summary = user.portfolio_summary or ""
    return f"{user.name}\nSkills: {skills}\n{summary}".strip()


def _persist_raw(db, user, raw) -> tuple[Lead, bool]:
    """Persist lead with semantic enrichment + SHA-256 idempotency.

    Returns (lead, created). created=False → duplicate dropped.
    TOS violations are persisted as rejected_tos_violation (audit trail) then dropped
    from active pipeline.
    """
    title, description, _budget, category = enrich_raw_lead_text(
        raw.title,
        raw.raw_text,
        url=raw.url,
        category=raw.category,
    )
    guarded = sanitize_external_text(description)
    clean_text = guarded.clean_text

    verdict = check_tos_compliance(f"{title}\n{clean_text}")
    pipeline = (
        PipelineStatus.REJECTED_TOS_VIOLATION.value
        if not verdict.allowed
        else PipelineStatus.NEW.value
    )

    h = content_hash(
        user_id=str(user.id),
        source=raw.source,
        url=raw.url,
        raw_text=clean_text,
    )
    portfolio = _portfolio_text(user)
    score = 0.0 if not verdict.allowed else match_score(portfolio, clean_text)

    lead = Lead(
        user_id=user.id,
        source=raw.source,
        title=title[:500],
        raw_text=clean_text,
        url=raw.url,
        category=category,
        embedding=None if not verdict.allowed else embed_text(clean_text),
        match_score=score,
        pipeline_status=pipeline,
        content_hash=h,
        tos_rejection_reason=(verdict.reason[:500] if not verdict.allowed else None),
    )

    lead_or_existing, should_insert, acquired = begin_idempotent_insert(db, lead)
    try:
        if not should_insert:
            return lead_or_existing, False
        if verdict.allowed and user.portfolio_embedding is None:
            user.portfolio_embedding = embed_text(portfolio)
        persisted, inserted = insert_or_recover(db, lead)
        return persisted, inserted
    finally:
        if acquired:
            release(h)


@router.post("/manual", response_model=LeadPublic, status_code=status.HTTP_201_CREATED)
def ingest_manual(
    payload: LeadCreateManual,
    db: DbSession,
    user: CurrentUser,
    request: Request,
) -> LeadPublic:
    rate_limit(client_key(request, "ingest", str(user.id)), limit=30, window_seconds=60)
    raws = ManualPasteIngestor(
        text=payload.raw_text,
        title=payload.title,
        url=payload.url,
        category=payload.category,
    ).fetch()
    if not raws:
        raise HTTPException(status_code=400, detail="Empty job text")
    lead, created = _persist_raw(db, user, raws[0])
    if not created:
        db.commit()
        return LeadPublic.model_validate(lead)
    db.commit()
    db.refresh(lead)
    return LeadPublic.model_validate(lead)


@router.post("/ingest", response_model=List[LeadPublic], status_code=status.HTTP_201_CREATED)
def ingest_public_source(
    payload: LeadIngestRemote,
    db: DbSession,
    user: CurrentUser,
    request: Request,
) -> List[LeadPublic]:
    rate_limit(client_key(request, "ingest-ext", str(user.id)), limit=5, window_seconds=60)
    if payload.source == "remoteok":
        ingestor = RemoteOKIngestor(limit=payload.limit, tags=payload.tags)
    elif payload.source == "weworkremotely":
        ingestor = WeWorkRemotelyRSSIngestor(limit=payload.limit)
    else:
        raise HTTPException(status_code=400, detail="Unsupported source")

    try:
        raws = ingestor.fetch()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Upstream source failed: {exc}") from exc

    leads: List[Lead] = []
    for raw in raws:
        lead, created = _persist_raw(db, user, raw)
        if created:
            leads.append(lead)
    db.commit()
    for lead in leads:
        db.refresh(lead)
    return [LeadPublic.model_validate(l) for l in leads]


@router.get("", response_model=List[LeadPublic])
def list_leads(
    db: DbSession,
    user: CurrentUser,
    min_score: Optional[float] = Query(default=None, ge=0.0, le=1.0),
    status_filter: Optional[str] = Query(default=None, alias="status"),
) -> List[LeadPublic]:
    stmt = select(Lead).where(Lead.user_id == user.id)
    if min_score is not None:
        stmt = stmt.where(Lead.match_score >= min_score)
    if status_filter:
        stmt = stmt.where(Lead.pipeline_status == status_filter)
    stmt = stmt.order_by(Lead.match_score.desc().nullslast(), Lead.ingested_at.desc())
    rows = db.scalars(stmt).all()
    return [LeadPublic.model_validate(r) for r in rows]


@router.get("/{lead_id}", response_model=LeadPublic)
def get_lead(lead_id: UUID, db: DbSession, user: CurrentUser) -> LeadPublic:
    lead = db.get(Lead, lead_id)
    if lead is None or lead.user_id != user.id:
        raise HTTPException(status_code=404, detail="Lead not found")
    return LeadPublic.model_validate(lead)


@router.patch("/{lead_id}/status", response_model=LeadPublic)
def update_lead_status(
    lead_id: UUID,
    payload: LeadStatusUpdate,
    db: DbSession,
    user: CurrentUser,
) -> LeadPublic:
    lead = db.get(Lead, lead_id)
    if lead is None or lead.user_id != user.id:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead.pipeline_status = payload.pipeline_status
    db.commit()
    db.refresh(lead)
    return LeadPublic.model_validate(lead)
