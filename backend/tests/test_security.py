from __future__ import annotations

"""Unit tests for password hashing and JWT helpers (no DB required)."""

from datetime import timedelta
from uuid import uuid4

import pytest
from jwt.exceptions import PyJWTError as JWTError

from app.core.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    get_subject_from_token,
    hash_password,
    verify_password,
)


def test_hash_password_is_not_plaintext() -> None:
    password = "SecurePass123!"
    hashed = hash_password(password)
    assert hashed != password
    assert hashed.startswith("$2")  # bcrypt


def test_verify_password_roundtrip() -> None:
    password = "SecurePass123!"
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_create_and_decode_access_token() -> None:
    user_id = uuid4()
    token = create_access_token(subject=user_id)
    payload = decode_access_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["type"] == "access"


def test_get_subject_from_token() -> None:
    user_id = uuid4()
    token = create_access_token(subject=user_id, expires_delta=timedelta(minutes=5))
    assert get_subject_from_token(token) == str(user_id)


def test_expired_token_raises() -> None:
    user_id = uuid4()
    token = create_access_token(subject=user_id, expires_delta=timedelta(seconds=-1))
    with pytest.raises((TokenError, JWTError)):
        get_subject_from_token(token)


def test_tampered_token_raises() -> None:
    user_id = uuid4()
    token = create_access_token(subject=user_id)
    tampered = token[:-4] + "xxxx"
    with pytest.raises(TokenError):
        get_subject_from_token(tampered)
