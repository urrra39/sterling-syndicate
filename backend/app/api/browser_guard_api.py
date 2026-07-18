from __future__ import annotations

"""CAPTCHA/MFA pause control plane — resume after human solves challenge."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.deps import CurrentUser
from app.models.lead import Lead, PipelineStatus
from app.core.deps import DbSession
from app.services.browser_guard import (
    get_pause,
    html_looks_like_captcha,
    intercept_page_content,
    list_open_pauses,
    resume_pause,
)
from app.services.playwright_stealth import proxy_status
from uuid import UUID

router = APIRouter(prefix="/browser", tags=["browser-guard"])


@router.get("/proxy/status")
def residential_proxy_status(_user: CurrentUser) -> dict:
    """Residential proxy + stealth posture (no secrets returned)."""
    return proxy_status()


class CaptchaPausePublic(BaseModel):
    pause_id: str
    lead_id: Optional[str] = None
    reason: str
    page_url: str
    screenshot_path: Optional[str] = None
    resolved: bool
    created_at: str


class DetectRequest(BaseModel):
    html: str = Field(..., min_length=1, max_length=200_000)
    page_url: str = Field(default="", max_length=2048)
    lead_id: Optional[UUID] = None
    wait: bool = False  # API default: don't block the HTTP worker


class DetectResponse(BaseModel):
    captcha_detected: bool
    pause_id: Optional[str] = None
    reason: Optional[str] = None
    pipeline_status: Optional[str] = None


@router.get("/captcha/open", response_model=List[CaptchaPausePublic])
def open_pauses(db: DbSession, user: CurrentUser) -> List[CaptchaPausePublic]:
    from sqlalchemy import select

    # Scope to the caller's own leads — the pause registry is global and
    # CaptchaPause has no user_id, so return only pauses whose lead is owned here.
    # Pauses with no lead_id are un-attributable and never exposed to a tenant.
    owned = {str(lid) for lid in db.scalars(select(Lead.id).where(Lead.user_id == user.id))}
    return [
        CaptchaPausePublic(
            pause_id=p.pause_id,
            lead_id=p.lead_id,
            reason=p.reason,
            page_url=p.page_url,
            screenshot_path=p.screenshot_path,
            resolved=p.resolved,
            created_at=p.created_at.isoformat(),
        )
        for p in list_open_pauses()
        if p.lead_id and p.lead_id in owned
    ]


@router.post("/captcha/{pause_id}/resume")
def resume_captcha(pause_id: str, db: DbSession, user: CurrentUser) -> dict:
    pause = get_pause(pause_id)
    if pause is None:
        raise HTTPException(status_code=404, detail="Pause not found")

    # Verify ownership BEFORE any state mutation — resume_pause() releases the
    # blocked flow, so calling it for another tenant's pause defeats the gate.
    lead = None
    if pause.lead_id:
        try:
            lead = db.get(Lead, UUID(pause.lead_id))
        except Exception:
            lead = None
    if lead is None or lead.user_id != user.id:
        raise HTTPException(status_code=404, detail="Pause not found")

    if not resume_pause(pause_id):
        raise HTTPException(status_code=404, detail="Pause not found")

    if lead.pipeline_status == PipelineStatus.PAUSED_FOR_CAPTCHA.value:
        lead.pipeline_status = PipelineStatus.IN_PROGRESS.value
        db.commit()
    return {"ok": True, "pause_id": pause_id, "resumed": True}


@router.post("/captcha/detect", response_model=DetectResponse)
def detect_captcha(
    payload: DetectRequest,
    db: DbSession,
    user: CurrentUser,
) -> DetectResponse:
    """State interceptor entry — call after fetching a page (Playwright or HTTP)."""
    reason = html_looks_like_captcha(payload.html)
    if not reason:
        return DetectResponse(captcha_detected=False)

    lead = None
    if payload.lead_id:
        lead = db.get(Lead, payload.lead_id)
        if lead is None or lead.user_id != user.id:
            raise HTTPException(status_code=404, detail="Lead not found")
        lead.pipeline_status = PipelineStatus.PAUSED_FOR_CAPTCHA.value
        db.commit()

    pause = intercept_page_content(
        html=payload.html,
        page_url=payload.page_url,
        lead_id=str(payload.lead_id) if payload.lead_id else None,
        wait=payload.wait,
    )
    return DetectResponse(
        captcha_detected=True,
        pause_id=pause.pause_id if pause else None,
        reason=reason,
        pipeline_status=PipelineStatus.PAUSED_FOR_CAPTCHA.value if lead else None,
    )
