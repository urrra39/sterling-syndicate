"""Field-level encryption (Fernet) round-trip + no-op behavior."""

from cryptography.fernet import Fernet

import app.core.config as config_mod
from app.core.encryption import decrypt_field, encrypt_field


def test_encrypt_roundtrip_with_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(config_mod.settings, "field_encryption_key", key)
    plaintext = "Acme Corp — Confidential Client Name"
    ct = encrypt_field(plaintext)
    assert ct != plaintext  # actually encrypted at rest
    assert "Acme" not in ct
    assert decrypt_field(ct) == plaintext  # round-trips


def test_decrypt_passes_through_legacy_plaintext(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(config_mod.settings, "field_encryption_key", key)
    # Rows written before encryption was enabled are not valid Fernet tokens.
    assert decrypt_field("legacy plaintext name") == "legacy plaintext name"


def test_no_key_is_noop(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "field_encryption_key", "")
    assert encrypt_field("x") == "x"
    assert decrypt_field("x") == "x"
