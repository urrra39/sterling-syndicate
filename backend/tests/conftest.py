from __future__ import annotations

"""Pytest configuration and shared fixtures."""

import os

# Ensure tests never accidentally hit a real production DB / secrets
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://sterling:change_me_strong_password@localhost:5432/sterling",
)
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-at-least-32-characters-long")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("TESTING", "true")
os.environ.setdefault("FORCE_SQLITE", "true")
os.environ.setdefault(
    "FIELD_ENCRYPTION_KEY", "u-mVc6PRVzrLQk8ZZXGK8WpvIjRTpsQ2AG6-iiqIKvk="
)

# Clear settings cache so env overrides take effect
from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()
