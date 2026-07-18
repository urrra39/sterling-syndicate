from __future__ import annotations

"""Step-up authorization for high-risk payment confirmation.

Two independent mechanisms satisfy the step-up requirement:

  * A human operator presenting a valid TOTP code (RFC 6238), verified against
    ``PAYMENT_STEPUP_TOTP_SECRET``. Implemented on the standard library so no
    extra dependency is pulled in.
  * A payment provider webhook whose raw body is signed with HMAC-SHA256 using
    ``PAYMENT_WEBHOOK_SECRET`` (constant-time compared). This lets funds be
    marked cleared by a trusted backend event rather than a mere tenant login.
"""

import base64
import hashlib
import hmac
import struct
import time

from app.core.config import settings


def _hotp(secret_b32: str, counter: int, digits: int = 6) -> str:
    key = base64.b32decode(_pad_b32(secret_b32), casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return str(code).zfill(digits)


def _pad_b32(s: str) -> str:
    s = s.strip().replace(" ", "").upper()
    return s + "=" * ((8 - len(s) % 8) % 8)


def verify_totp(code: str, *, secret_b32: str = "", step: int = 30, window: int = 1) -> bool:
    """Verify a TOTP code, tolerating +/- `window` steps of clock skew."""
    secret = secret_b32 or settings.payment_stepup_totp_secret
    code = (code or "").strip()
    if not secret or not code.isdigit():
        return False
    counter = int(time.time()) // step
    for drift in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret, counter + drift), code):
            return True
    return False


def verify_webhook_signature(raw_body: bytes, signature: str, *, secret: str = "") -> bool:
    """Constant-time HMAC-SHA256 verification of a payment-provider webhook."""
    key = secret or settings.payment_webhook_secret
    signature = (signature or "").strip()
    if not key or not signature:
        return False
    # Accept an optional "sha256=" prefix (common provider convention).
    if signature.startswith("sha256="):
        signature = signature[len("sha256=") :]
    expected = hmac.new(key.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
