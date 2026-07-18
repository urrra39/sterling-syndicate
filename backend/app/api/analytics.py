from __future__ import annotations

"""Analytics from collected pipeline data."""

from collections import defaultdict
from datetime import timezone
from typing import Dict, List, Optional

from fastapi import APIRouter
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.models.lead import Lead, PipelineStatus
from app.models.proposal import Contract, Proposal
from app.schemas.crm import AnalyticsSummary

router = APIRouter()


@router.get("/summary", response_model=AnalyticsSummary)
def analytics_summary(db: DbSession, user: CurrentUser) -> AnalyticsSummary:
    leads = db.scalars(select(Lead).where(Lead.user_id == user.id)).all()
    lead_ids = [l.id for l in leads]
    total = len(leads)
    won = sum(1 for l in leads if l.pipeline_status in {
        PipelineStatus.WON.value,
        PipelineStatus.IN_PROGRESS.value,
        PipelineStatus.DELIVERED.value,
        PipelineStatus.PAID.value,
    })
    lost = sum(1 for l in leads if l.pipeline_status == PipelineStatus.LOST.value)
    decided = won + lost
    win_rate = round(won / decided, 4) if decided else 0.0

    proposals: List[Proposal] = []
    if lead_ids:
        proposals = list(
            db.scalars(select(Proposal).where(Proposal.lead_id.in_(lead_ids))).all()
        )
    sent = [p for p in proposals if p.status == "sent" and p.sent_at and p.created_at]
    proposals_sent = len([p for p in proposals if p.status == "sent"])

    hours: List[float] = []
    for p in sent:
        created = p.created_at
        sent_at = p.sent_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
        hours.append((sent_at - created).total_seconds() / 3600.0)
    avg_hours: Optional[float] = round(sum(hours) / len(hours), 2) if hours else None

    contracts: List[Contract] = []
    if lead_ids:
        contracts = list(
            db.scalars(select(Contract).where(Contract.lead_id.in_(lead_ids))).all()
        )
    lead_by_id = {l.id: l for l in leads}

    by_month: Dict[str, float] = defaultdict(float)
    by_cat: Dict[str, float] = defaultdict(float)
    for c in contracts:
        # Payment kill switch: only human-confirmed payments count as revenue.
        # Unverified contracts default to pending_payment_verification and would
        # otherwise inflate reported revenue with money never received.
        if not c.is_payment_verified:
            continue
        month = c.created_at.strftime("%Y-%m")
        by_month[month] += c.agreed_price
        cat = (lead_by_id.get(c.lead_id).category if lead_by_id.get(c.lead_id) else None) or "uncategorized"
        by_cat[cat] += c.agreed_price

    return AnalyticsSummary(
        total_leads=total,
        proposals_sent=proposals_sent,
        won=won,
        lost=lost,
        win_rate=win_rate,
        avg_hours_to_mark_sent=avg_hours,
        revenue_by_month=[{"month": k, "revenue": round(v, 2)} for k, v in sorted(by_month.items())],
        revenue_by_category=[{"category": k, "revenue": round(v, 2)} for k, v in sorted(by_cat.items())],
    )
