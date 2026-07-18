from __future__ import annotations

"""FastAPI dependencies for auth and DB access."""

from typing import Annotated, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import TokenError, get_subject_and_version
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def _extract_token(
    credentials: Optional[HTTPAuthorizationCredentials],
    request: Request,
) -> str:
    """Extract JWT from Bearer header first, then fall back to HttpOnly cookie."""
    if credentials and credentials.credentials:
        return credentials.credentials
    cookie_token = request.cookies.get("sterling_access_token")
    if cookie_token:
        return cookie_token
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    request: Request,
    db: DbSession,
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials],
        Depends(bearer_scheme),
    ] = None,
) -> User:
    """Resolve the authenticated user from the Bearer JWT or HttpOnly cookie."""
    token = _extract_token(credentials, request)
    # Single decode: pull both the subject and the mandatory token-version claim.
    try:
        subject, token_version = get_subject_and_version(token)
        user_id = UUID(subject)
    except (TokenError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Session invalidation: a password reset bumps user.token_version, so every
    # token minted before it (with a lower tv) is rejected here.
    if token_version != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalidated. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


# Roles permitted to release the payment kill switch. "member" cannot.
_PAYMENT_APPROVER_ROLES = frozenset({"owner", "approver"})


def require_payment_approver(user: CurrentUser) -> User:
    """RBAC gate: only an owner/approver may confirm payments.

    Separates the ability to *confirm funds* (release the kill switch) from
    ordinary tenant ownership, so a compromised low-privilege session cannot
    unlock delivery work.
    """
    if getattr(user, "role", "owner") not in _PAYMENT_APPROVER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Payment confirmation requires an approver or owner role.",
        )
    return user


PaymentApprover = Annotated[User, Depends(require_payment_approver)]
