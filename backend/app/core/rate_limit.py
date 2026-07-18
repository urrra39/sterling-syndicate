from __future__ import annotations

"""Tiny in-memory rate limiter.

ponytail: process-local dict. Swap to Redis if multi-worker.

Two hardening concerns handled here:
  * Correct client identity behind a reverse proxy (X-Forwarded-For), instead of
    always using the raw socket peer (which, behind Nginx, is the proxy itself —
    collapsing every real client into one bucket).
  * Bounded memory: the `_hits` map is swept of stale keys periodically so a flood
    of unique keys (unique IPs / user-ids) can't grow the dict without limit.
"""

import time
from collections import defaultdict, deque
from threading import Lock
from typing import DefaultDict, Deque

from fastapi import HTTPException, Request, status

_lock = Lock()
_hits: DefaultDict[str, Deque[float]] = defaultdict(deque)

# Longest window we rate-limit on. Any key whose newest hit is older than this is
# dead weight and can be dropped. Kept comfortably above the largest per-endpoint
# window in use so we never evict a key that's still inside its window.
_MAX_WINDOW_SECONDS = 3600
# How often the sweeper actually walks the dict (amortized over calls).
_GC_INTERVAL_SECONDS = 60
_last_gc: float = 0.0


def _gc_locked(now: float) -> None:
    """Drop keys with no hits inside the max window. Caller must hold `_lock`."""
    global _last_gc
    if now - _last_gc < _GC_INTERVAL_SECONDS:
        return
    _last_gc = now
    cutoff = now - _MAX_WINDOW_SECONDS
    stale = [k for k, q in _hits.items() if not q or q[-1] < cutoff]
    for k in stale:
        del _hits[k]


def rate_limit(key: str, *, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        _gc_locked(now)
        q = _hits[key]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Try again shortly.",
            )
        q.append(now)


def resolve_client_ip(request: Request) -> str:
    """Best-effort real client IP.

    Prefer the left-most entry of X-Forwarded-For (the original client as recorded
    by the trusted Nginx front) so a single reverse-proxy socket address doesn't
    lump every user into one rate-limit bucket. Fall back to X-Real-IP, then to the
    raw socket peer.
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


def client_key(request: Request, suffix: str, user_id: str = "") -> str:
    return f"{suffix}:{user_id or resolve_client_ip(request)}"


def reset_state() -> None:
    """Test helper: clear all buckets and GC bookkeeping."""
    global _last_gc
    with _lock:
        _hits.clear()
        _last_gc = 0.0
