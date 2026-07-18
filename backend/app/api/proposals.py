from __future__ import annotations

"""Proposal draft via multi-agent pipeline + human mark-sent / reject."""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.core.rate_limit import client_key, rate_limit
from app.models.agent_memory import AgentMemory
from app.models.lead import Lead, PipelineStatus
from app.models.proposal import Proposal
from app.schemas.crm import ProposalCreateRequest, ProposalPublic
from app.services.agents import reflector_learn, run_proposal_pipeline
from app.services.compliance import check_tos_compliance
from app.services.dlq import enqueue
from app.services.llm_router import LLMError
from app.services.notify import notify_high_match_draft
from app.services.payment_guard import assert_payment_cleared

router = APIRouter()


class ProposalPublicExt(ProposalPublic):
    outcome: Optional[str] = None
    recommended_bid: Optional[float] = None
    rag_citations: Optional[str] = None


class OutcomeUpdate(BaseModel):
    outcome: str = Field(..., pattern="^(accepted|rejected)$")


def _get_or_create_memory(db, user_id: UUID) -> AgentMemory:
    mem = db.scalar(select(AgentMemory).where(AgentMemory.user_id == user_id))
    if mem is None:
        mem = AgentMemory(user_id=user_id)
        db.add(mem)
        db.flush()
    return mem


@router.post(
    "/leads/{lead_id}/draft-proposal",
    response_model=ProposalPublicExt,
    status_code=status.HTTP_201_CREATED,
)
def create_draft_proposal(
    lead_id: UUID,
    payload: ProposalCreateRequest,
    db: DbSession,
    user: CurrentUser,
    request: Request,
) -> ProposalPublicExt:
    rate_limit(client_key(request, "llm", str(user.id)), limit=10, window_seconds=60)
    lead = db.get(Lead, lead_id)
    if lead is None or lead.user_id != user.id:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.pipeline_status == PipelineStatus.REJECTED_TOS_VIOLATION.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Lead rejected for ToS violation: {lead.tos_rejection_reason or 'prohibited'}",
        )
    verdict = check_tos_compliance(f"{lead.title}\n{lead.raw_text}")
    if not verdict.allowed:
        lead.pipeline_status = PipelineStatus.REJECTED_TOS_VIOLATION.value
        lead.tos_rejection_reason = verdict.reason[:500]
        db.commit()
        raise HTTPException(status_code=403, detail=verdict.reason)
    assert_payment_cleared(db, lead_id)

    mem = _get_or_create_memory(db, user.id)
    if lead.pipeline_status == PipelineStatus.NEW.value:
        lead.pipeline_status = PipelineStatus.DRAFTING.value
        db.flush()
    try:
        result = run_proposal_pipeline(
            {
                "user_id": str(user.id),
                "name": user.name,
                "skills": user.skills or [],
                "portfolio_summary": user.portfolio_summary or "",
                "lead_text": lead.raw_text,
                "lead_title": lead.title,
                "tone": payload.tone,
                "writer_instructions": mem.writer_instructions,
            }
        )
    except (LLMError, TimeoutError, ConnectionError, OSError) as exc:
        enqueue(
            db,
            task_type="proposal_draft",
            payload={"lead_id": str(lead_id), "tone": payload.tone, "user_id": str(user.id)},
            user_id=user.id,
            lead_id=lead.id,
            error=str(exc),
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "LLM provider failed — task queued in Dead Letter Queue for retry "
                f"(exponential backoff, max 5). Error: {exc}"
            ),
        ) from exc

    draft = result.get("proposal_draft") or ""
    price = result.get("price") or {}
    chunks = result.get("rag_chunks") or []
    scout = result.get("scout") or {}

    # Prefer scout score when LLM scored; else keep existing
    if isinstance(scout.get("match_score"), (int, float)):
        lead.match_score = float(scout["match_score"])
    if scout.get("category") and not lead.category:
        lead.category = str(scout["category"])[:120]

    citations = "; ".join(
        f"[{i}] {c.get('title')} ({c.get('source')})" for i, c in enumerate(chunks, 1)
    )
    bid = price.get("recommended_bid")

    proposal = Proposal(
        lead_id=lead.id,
        draft_text=draft,
        status="draft",
        generated_by="ai_generated",
        tone=payload.tone,
        recommended_bid=float(bid) if bid is not None else None,
        rag_citations=citations or None,
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)

    score = lead.match_score or 0.0
    if score >= settings.high_match_threshold:
        notify_high_match_draft(
            title=lead.title,
            match_score=score,
            lead_id=str(lead.id),
            recommended_bid=proposal.recommended_bid,
        )

    return ProposalPublicExt.model_validate(proposal)


@router.get("/leads/{lead_id}/proposals", response_model=List[ProposalPublicExt])
def list_proposals(lead_id: UUID, db: DbSession, user: CurrentUser) -> List[ProposalPublicExt]:
    lead = db.get(Lead, lead_id)
    if lead is None or lead.user_id != user.id:
        raise HTTPException(status_code=404, detail="Lead not found")
    rows = db.scalars(
        select(Proposal).where(Proposal.lead_id == lead_id).order_by(Proposal.created_at.desc())
    ).all()
    return [ProposalPublicExt.model_validate(r) for r in rows]


@router.post("/proposals/{proposal_id}/mark-sent", response_model=ProposalPublicExt)
def mark_proposal_sent(
    proposal_id: UUID,
    db: DbSession,
    user: CurrentUser,
) -> ProposalPublicExt:
    """Human confirms they copied & sent the draft themselves. App never sends."""
    proposal = db.get(Proposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    lead = db.get(Lead, proposal.lead_id)
    if lead is None or lead.user_id != user.id:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status == "sent":
        return ProposalPublicExt.model_validate(proposal)

    proposal.status = "sent"
    proposal.sent_at = datetime.now(timezone.utc)
    if lead.pipeline_status in {PipelineStatus.NEW.value, PipelineStatus.DRAFTING.value}:
        lead.pipeline_status = PipelineStatus.SENT.value
    db.commit()
    db.refresh(proposal)
    return ProposalPublicExt.model_validate(proposal)


@router.post("/proposals/{proposal_id}/outcome", response_model=ProposalPublicExt)
def set_proposal_outcome(
    proposal_id: UUID,
    payload: OutcomeUpdate,
    db: DbSession,
    user: CurrentUser,
    request: Request,
) -> ProposalPublicExt:
    """Mark accepted/rejected. Rejection triggers Reflector_Agent instruction update."""
    rate_limit(client_key(request, "reflect", str(user.id)), limit=20, window_seconds=60)
    proposal = db.get(Proposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    lead = db.get(Lead, proposal.lead_id)
    if lead is None or lead.user_id != user.id:
        raise HTTPException(status_code=404, detail="Proposal not found")

    proposal.outcome = payload.outcome
    if payload.outcome == "rejected":
        # Only downgrade to LOST from a still-open state. A stale proposal marked
        # rejected must not drag a lead that another proposal already advanced to
        # WON/IN_PROGRESS/DELIVERED/PAID back to lost.
        if lead.pipeline_status in {
            PipelineStatus.NEW.value,
            PipelineStatus.DRAFTING.value,
            PipelineStatus.SENT.value,
            PipelineStatus.NEGOTIATING.value,
        }:
            lead.pipeline_status = PipelineStatus.LOST.value
        mem = _get_or_create_memory(db, user.id)
        update = reflector_learn(
            proposal_text=proposal.draft_text,
            lead_text=lead.raw_text,
            current_instructions=mem.writer_instructions,
        )
        mem.last_lesson = update.lesson
        # Append delta; keep last ~4k chars
        combined = (mem.writer_instructions + "\n" + update.instruction_delta).strip()
        mem.writer_instructions = combined[-4000:]
    elif payload.outcome == "accepted":
        if lead.pipeline_status in {
            PipelineStatus.SENT.value,
            PipelineStatus.NEGOTIATING.value,
            PipelineStatus.DRAFTING.value,
        }:
            lead.pipeline_status = PipelineStatus.WON.value

    db.commit()
    db.refresh(proposal)
    return ProposalPublicExt.model_validate(proposal)
