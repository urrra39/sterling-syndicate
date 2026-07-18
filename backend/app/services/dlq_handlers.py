from __future__ import annotations

"""Register DLQ task handlers (called once at app startup)."""

from typing import Any, Dict
from uuid import UUID

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.agent_memory import AgentMemory
from app.models.lead import Lead, PipelineStatus
from app.models.proposal import Proposal
from app.models.user import User
from app.services.agents import run_proposal_pipeline
from app.services.dlq import register_handler


def _handle_proposal_draft(payload: Dict[str, Any]) -> None:
    lead_id = UUID(payload["lead_id"])
    user_id = UUID(payload["user_id"])
    tone = payload.get("tone") or "confident"
    db = SessionLocal()
    try:
        lead = db.get(Lead, lead_id)
        user = db.get(User, user_id)
        if lead is None or user is None:
            raise RuntimeError("lead or user missing for DLQ proposal_draft")
        if lead.pipeline_status == PipelineStatus.REJECTED_TOS_VIOLATION.value:
            return  # drop — do not retry prohibited work
        # Idempotency: a prior retry may have committed its draft (own session)
        # before the outer DLQ bookkeeping rolled back. Skip if a draft already
        # exists so a re-run cannot produce a duplicate proposal.
        existing = db.scalar(
            select(Proposal.id).where(
                Proposal.lead_id == lead.id,
                Proposal.generated_by == "ai_generated",
                Proposal.status == "draft",
            )
        )
        if existing is not None:
            return
        mem = db.scalar(select(AgentMemory).where(AgentMemory.user_id == user_id))
        result = run_proposal_pipeline(
            {
                "user_id": str(user.id),
                "name": user.name,
                "skills": user.skills or [],
                "portfolio_summary": user.portfolio_summary or "",
                "lead_text": lead.raw_text,
                "lead_title": lead.title,
                "tone": tone,
                "writer_instructions": (mem.writer_instructions if mem else "") or "",
            }
        )
        draft = result.get("proposal_draft") or ""
        if not draft:
            raise RuntimeError("empty draft from pipeline retry")
        price = result.get("price") or {}
        bid = price.get("recommended_bid")
        db.add(
            Proposal(
                lead_id=lead.id,
                draft_text=draft,
                status="draft",
                generated_by="ai_generated",
                tone=tone,
                recommended_bid=float(bid) if bid is not None else None,
            )
        )
        if lead.pipeline_status in {PipelineStatus.NEW.value, PipelineStatus.DRAFTING.value}:
            lead.pipeline_status = PipelineStatus.DRAFTING.value
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def register_all_handlers() -> None:
    register_handler("proposal_draft", _handle_proposal_draft)
