from __future__ import annotations

"""Negotiation copilot — paste client message, get draft reply options."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.core.rate_limit import client_key, rate_limit
from app.models.agent_memory import AgentMemory
from app.models.lead import Lead, PipelineStatus
from app.models.proposal import Contract, Conversation, Proposal
from app.schemas.crm import ConversationPublic, IncomingMessage, ReplySuggestion
from app.services.agents import negotiator_drafts
from app.services.payment_guard import assert_payment_cleared

router = APIRouter()


def _memory(db, user_id: UUID) -> AgentMemory:
    mem = db.scalar(select(AgentMemory).where(AgentMemory.user_id == user_id))
    if mem is None:
        mem = AgentMemory(user_id=user_id)
        db.add(mem)
        db.flush()
    return mem


@router.post("/{lead_id}/incoming", response_model=ConversationPublic, status_code=201)
def log_incoming(
    lead_id: UUID,
    payload: IncomingMessage,
    db: DbSession,
    user: CurrentUser,
) -> ConversationPublic:
    lead = db.get(Lead, lead_id)
    if lead is None or lead.user_id != user.id:
        raise HTTPException(status_code=404, detail="Lead not found")
    msg = Conversation(
        lead_id=lead.id,
        direction="incoming",
        body=payload.body.strip(),
        generated_by="human",
    )
    if lead.pipeline_status in {
        PipelineStatus.SENT.value,
        PipelineStatus.DRAFTING.value,
        PipelineStatus.NEW.value,
    }:
        lead.pipeline_status = PipelineStatus.NEGOTIATING.value
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return ConversationPublic.model_validate(msg)


@router.post("/{lead_id}/suggest-replies", response_model=List[ReplySuggestion])
def suggest(
    lead_id: UUID,
    payload: IncomingMessage,
    db: DbSession,
    user: CurrentUser,
    request: Request,
) -> List[ReplySuggestion]:
    rate_limit(client_key(request, "llm-reply", str(user.id)), limit=10, window_seconds=60)
    lead = db.get(Lead, lead_id)
    if lead is None or lead.user_id != user.id:
        raise HTTPException(status_code=404, detail="Lead not found")
    assert_payment_cleared(db, lead_id)

    incoming = Conversation(
        lead_id=lead.id,
        direction="incoming",
        body=payload.body.strip(),
        generated_by="human",
    )
    db.add(incoming)

    mem = _memory(db, user.id)
    latest = db.scalar(
        select(Proposal)
        .where(Proposal.lead_id == lead.id)
        .order_by(Proposal.created_at.desc())
        .limit(1)
    )
    floor = latest.recommended_bid if latest and latest.recommended_bid else None
    contract = db.scalar(select(Contract).where(Contract.lead_id == lead.id))
    agreed_scope = contract.agreed_scope if contract else None
    agreed_price = contract.agreed_price if contract else None

    suggestions = negotiator_drafts(
        lead_text=lead.raw_text,
        incoming=payload.body,
        name=user.name,
        skills=user.skills or [],
        negotiator_instructions=mem.negotiator_instructions,
        floor_price=floor,
        agreed_scope=agreed_scope,
        agreed_price=agreed_price,
    )
    out: List[ReplySuggestion] = []
    for s in suggestions:
        creep = str(s.get("scope_creep_detected", "")).lower() in {"true", "1", "yes"}
        draft = Conversation(
            lead_id=lead.id,
            direction="outgoing_draft",
            body=s["body"],
            label=s["label"],
            generated_by="ai_generated",
        )
        db.add(draft)
        out.append(
            ReplySuggestion(
                label=s["label"],
                body=s["body"],
                scope_creep_detected=creep,
                out_of_scope_summary=s.get("out_of_scope_summary") or None,
            )
        )

    # State-machine guard: suggesting replies must never regress a lead that has
    # already advanced past negotiation (won, in_progress, delivered, paid, ...).
    # Only pre-negotiation statuses may transition forward to "negotiating".
    if lead.pipeline_status in {
        PipelineStatus.NEW.value,
        PipelineStatus.DRAFTING.value,
        PipelineStatus.SENT.value,
    }:
        lead.pipeline_status = PipelineStatus.NEGOTIATING.value
    db.commit()
    return out


@router.get("/{lead_id}", response_model=List[ConversationPublic])
def list_conversations(
    lead_id: UUID, db: DbSession, user: CurrentUser
) -> List[ConversationPublic]:
    lead = db.get(Lead, lead_id)
    if lead is None or lead.user_id != user.id:
        raise HTTPException(status_code=404, detail="Lead not found")
    rows = db.scalars(
        select(Conversation)
        .where(Conversation.lead_id == lead_id)
        .order_by(Conversation.created_at.asc())
    ).all()
    return [ConversationPublic.model_validate(r) for r in rows]
