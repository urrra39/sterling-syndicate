from __future__ import annotations

"""Transactional email via SMTP (Gmail). Dev-safe: logs link if unconfigured."""

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger("sterling.email")


def _smtp_configured() -> bool:
    return bool(settings.smtp_username and settings.smtp_password)


def send_email(*, to: str, subject: str, body_text: str, body_html: str = "") -> bool:
    """Send an email. Returns True if dispatched, False if only logged (dev)."""
    if not _smtp_configured():
        logger.warning(
            "SMTP not configured — email to %s NOT sent. Subject=%r. Body:\n%s",
            to,
            subject,
            body_text,
        )
        return False

    msg = EmailMessage()
    msg["From"] = settings.smtp_from or settings.smtp_username
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
        logger.info("Password-reset email dispatched to %s", to)
        return True
    except Exception as exc:  # noqa: BLE001 — never crash the request on email failure
        logger.error("Failed to send email to %s: %s", to, exc)
        return False


def send_password_reset_email(*, to: str, reset_link: str) -> bool:
    subject = "The Sterling Syndicate — Password Reset"
    body_text = (
        "You requested a password reset for The Sterling Syndicate.\n\n"
        f"Reset your password using this link (valid for "
        f"{settings.password_reset_token_ttl_minutes} minutes):\n{reset_link}\n\n"
        "If you did not request this, you can safely ignore this email."
    )
    body_html = f"""\
<div style="font-family:Georgia,serif;background:#0a0a0a;color:#e5e5e5;padding:32px;border-radius:8px">
  <h1 style="color:#d4af37;font-weight:600;letter-spacing:.5px">The Sterling Syndicate</h1>
  <p style="color:#cbd5e1">You requested a password reset.</p>
  <p style="margin:24px 0">
    <a href="{reset_link}"
       style="background:#27272a;color:#f59e0b;border:1px solid rgba(180,120,20,.5);
              padding:12px 20px;border-radius:6px;text-decoration:none;font-weight:600">
      Reset your password
    </a>
  </p>
  <p style="color:#71717a;font-size:13px">
    This link is valid for {settings.password_reset_token_ttl_minutes} minutes.
    If you didn't request it, ignore this email.
  </p>
</div>"""
    return send_email(to=to, subject=subject, body_text=body_text, body_html=body_html)
