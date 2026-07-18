from __future__ import annotations

"""Outbound notification webhooks — alert only, never send proposals to clients."""

from typing import Optional

import httpx

from app.core.config import settings


def notify_high_match_draft(
    *,
    title: str,
    match_score: float,
    lead_id: str,
    recommended_bid: Optional[float] = None,
) -> None:
    score_pct = f"{match_score * 100:.0f}%"
    bid = f" · suggested bid ${recommended_bid:.0f}" if recommended_bid else ""
    text = (
        f"The Sterling Syndicate draft ready\n"
        f"Lead: {title}\n"
        f"Match: {score_pct}{bid}\n"
        f"ID: {lead_id}\n"
        f"Action required: review draft in app — nothing was auto-sent."
    )
    _telegram(text)
    _discord(text)


def notify_payment_action_required(
    *,
    client_name: str,
    amount: float,
    currency: str = "USD",
    lead_id: str,
    lead_title: str = "",
) -> None:
    """High-priority alert — human must verify funds before any further work."""
    title = f" ({lead_title})" if lead_title else ""
    text = (
        f"🚨 ACTION REQUIRED: Client {client_name} initiated a payment of "
        f"{currency} ${amount:.2f}{title}.\n"
        f"Lead ID: {lead_id}\n"
        f"All agent/delivery actions are FROZEN until you Confirm Payment Received "
        f"in the Sterling Syndicate dashboard."
    )
    _telegram(text)
    _discord(text)


def notify_budget_warning(
    *,
    project_name: str,
    lead_id: str,
    spent: float,
    budget: float,
    pct: float,
) -> None:
    text = (
        f"⚠️ Budget WARNING: Project {project_name} at {pct:.0f}% of API budget "
        f"(${spent:.2f} / ${budget:.2f}).\n"
        f"Lead ID: {lead_id}\n"
        f"Falling back to Tier-2 models soon if spend continues."
    )
    _telegram(text)
    _discord(text)


def notify_profit_guard_triggered(
    *,
    project_name: str,
    lead_id: str,
    spent: float,
    budget: float,
) -> None:
    text = (
        f"🚨 Profit Guard Triggered: API budget depleted for Project {project_name}. "
        f"Execution paused to prevent financial loss.\n"
        f"Spent ${spent:.2f} / ${budget:.2f}. Lead ID: {lead_id}"
    )
    _telegram(text)
    _discord(text)


def notify_budget_pause(
    *,
    project_name: str,
    lead_id: str,
    completeness_pct: float,
    spent: float,
    budget: float,
) -> None:
    text = (
        f"⚠️ Budget limit reached for Project {project_name}. "
        f"Output is {completeness_pct:.0f}% complete. "
        f"Authorize an extra 5% budget to finish, or review the current draft manually?\n"
        f"Spent ${spent:.2f} / ${budget:.2f}. Lead ID: {lead_id}"
    )
    _telegram(text)
    _discord(text)


def notify_api_outage(
    *,
    task_id: str,
    task_type: str,
    attempts: int,
    error: str = "",
) -> None:
    text = (
        f"🚨 API Outage Alert: Task {task_id} ({task_type}) failed {attempts} retries. "
        f"Manual intervention required.\n"
        f"Last error: {(error or 'unknown')[:500]}"
    )
    _telegram(text)
    _discord(text)


def notify_captcha_intervention(
    *,
    pause_id: str,
    reason: str,
    page_url: str = "",
    lead_id: str = "",
    screenshot_path: Optional[str] = None,
) -> None:
    text = (
        f"🚨 INTERVENTION REQUIRED: CAPTCHA/MFA detected. Awaiting manual resolution.\n"
        f"Pause ID: {pause_id}\n"
        f"Reason: {reason}\n"
        f"URL: {page_url or 'n/a'}\n"
        f"Lead: {lead_id or 'n/a'}\n"
        f"Screenshot: {screenshot_path or 'none'}\n"
        f"Resume via POST /browser/captcha/{pause_id}/resume after solving."
    )
    _telegram(text)
    _discord(text)
    if screenshot_path and settings.telegram_bot_token and settings.telegram_chat_id:
        _telegram_photo(screenshot_path, caption=text[:900])


def _telegram_photo(path: str, *, caption: str = "") -> None:
    token = settings.telegram_bot_token
    chat = settings.telegram_chat_id
    if not token or not chat:
        return
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        with open(path, "rb") as f:
            with httpx.Client(timeout=30.0) as client:
                client.post(
                    url,
                    data={"chat_id": chat, "caption": caption[:1024]},
                    files={"photo": f},
                )
    except Exception:
        return


def _telegram(text: str) -> None:
    token = settings.telegram_bot_token
    chat = settings.telegram_chat_id
    if not token or not chat:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        with httpx.Client(timeout=15.0) as client:
            client.post(url, json={"chat_id": chat, "text": text})
    except Exception:
        return


def _discord(text: str) -> None:
    hook = settings.discord_webhook_url
    if not hook:
        return
    try:
        with httpx.Client(timeout=15.0) as client:
            client.post(hook, json={"content": text[:1900]})
    except Exception:
        return
