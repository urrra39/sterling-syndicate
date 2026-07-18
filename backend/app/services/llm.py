from __future__ import annotations

"""Legacy facade — delegates to multi-agent pipeline."""

from typing import List, Optional

from app.services.agents import negotiator_drafts, writer_draft_proposal


def draft_proposal(
    *,
    lead_text: str,
    name: str,
    skills: List[str],
    portfolio_summary: Optional[str],
    tone: str = "confident",
    user_id: str = "anon",
    writer_instructions: str = "",
) -> str:
    text, _chunks, _price = writer_draft_proposal(
        lead_text=lead_text,
        name=name,
        skills=skills,
        portfolio_summary=portfolio_summary or "",
        tone=tone,
        writer_instructions=writer_instructions
        or "Cite RAG evidence. Stay under 280 words. Never auto-send.",
        user_id=user_id,
    )
    return text


def suggest_replies(
    *,
    lead_text: str,
    incoming: str,
    name: str,
    skills: List[str],
    negotiator_instructions: str = "",
    floor_price: Optional[float] = None,
    agreed_scope: Optional[str] = None,
    agreed_price: Optional[float] = None,
) -> List[dict]:
    return negotiator_drafts(
        lead_text=lead_text,
        incoming=incoming,
        name=name,
        skills=skills,
        negotiator_instructions=negotiator_instructions
        or "Hold firm on price; offer scope trades. Never do out-of-scope work for free.",
        floor_price=floor_price,
        agreed_scope=agreed_scope,
        agreed_price=agreed_price,
    )
