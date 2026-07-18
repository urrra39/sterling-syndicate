from __future__ import annotations

"""Password hashing and JWT helpers."""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union
from uuid import UUID

import jwt
from jwt.exceptions import PyJWTError as JWTError
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt. Never log the plaintext."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Constant-time verification of a password against its hash."""
    return pwd_context.verify(plain_password, password_hash)


def create_access_token(
    subject: Union[str, UUID],
    expires_delta: Optional[timedelta] = None,
    extra_claims: Optional[dict[str, Any]] = None,
) -> str:
    """Create a signed JWT access token."""
    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT. Raises JWTError on failure."""
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )


class TokenError(Exception):
    """Raised when a token is missing, expired, or malformed."""


def get_subject_from_token(token: str) -> str:
    """Extract the `sub` claim or raise TokenError."""
    try:
        payload = decode_access_token(token)
    except JWTError as exc:
        raise TokenError("Invalid or expired token") from exc
    subject = payload.get("sub")
    if not subject or payload.get("type") != "access":
        raise TokenError("Invalid token payload")
    return str(subject)


def get_subject_and_version(token: str) -> tuple[str, int]:
    """Decode ONCE and return (subject, token_version).

    Avoids the double-decode the auth dependency used to do (decode for `sub`,
    then decode again for `tv`). The `tv` claim is mandatory — a token minted
    before token-versioning existed, or one with a forged/absent version, is
    rejected so a stale session can never satisfy the invalidation check by
    simply omitting the claim.
    """
    try:
        payload = decode_access_token(token)
    except JWTError as exc:
        raise TokenError("Invalid or expired token") from exc
    subject = payload.get("sub")
    if not subject or payload.get("type") != "access":
        raise TokenError("Invalid token payload")
    tv = payload.get("tv")
    if not isinstance(tv, int):
        raise TokenError("Missing token version claim")
    return str(subject), tv
