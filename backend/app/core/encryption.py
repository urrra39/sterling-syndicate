from __future__ import annotations

"""Field-level encryption helpers (Fernet).

Wired into sensitive columns via the EncryptedStr TypeDecorator so every read and
write routes through encrypt/decrypt. With no FIELD_ENCRYPTION_KEY set it is a
transparent no-op (stores plaintext); decrypt_field also passes legacy plaintext
through, so enabling a key later is backward compatible with existing rows.
"""

from typing import Optional

import sqlalchemy as sa
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Optional[Fernet]:
    key = settings.field_encryption_key
    if not key:
        return None
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_field(plaintext: str) -> str:
    """Encrypt a string at rest. Returns plaintext unchanged if no key is set."""
    f = _fernet()
    if f is None:
        return plaintext
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_field(ciphertext: str) -> str:
    """Decrypt a previously encrypted field. Passes through if no key / not encrypted."""
    f = _fernet()
    if f is None:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        # Value may be legacy plaintext from before encryption was enabled
        return ciphertext


class EncryptedStr(sa.types.TypeDecorator):
    """Unbounded text column encrypted at rest via Fernet.

    Uses a Text impl because Fernet ciphertext is ~3x the plaintext length and must
    not be truncated. No-op passthrough when FIELD_ENCRYPTION_KEY is unset.
    """

    impl = sa.Text
    cache_ok = True

    def process_bind_param(self, value: Optional[str], dialect) -> Optional[str]:
        return None if value is None else encrypt_field(value)

    def process_result_value(self, value: Optional[str], dialect) -> Optional[str]:
        return None if value is None else decrypt_field(value)

