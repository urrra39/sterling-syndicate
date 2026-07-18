"""Docker-free SQLite fallback + CORS defaults."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select, text

from app.core.config import Settings, get_settings
from app.core.database import (
    Base,
    create_db_engine,
    ensure_schema,
    init_engine,
    resolve_database_url,
    using_sqlite,
)
from app.core.security import hash_password
from app.models.user import User


def test_cors_includes_vite_origins() -> None:
    s = Settings(
        JWT_SECRET_KEY="test-secret-key-at-least-32-characters",
        CORS_ORIGINS="http://localhost:5173",
    )
    origins = s.cors_origins_list
    assert "http://localhost:5173" in origins
    assert "http://127.0.0.1:5173" in origins


def test_resolve_falls_back_to_sqlite(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("FORCE_SQLITE", "true")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-at-least-32-characters")
    get_settings.cache_clear()
    # Point fallback into tmp by patching constant via resolve path mkdir
    from app.core import database as dbmod

    monkeypatch.setattr(dbmod, "SQLITE_FALLBACK_URL", f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    url = resolve_database_url()
    assert url.startswith("sqlite")
    get_settings.cache_clear()


def test_sqlite_schema_and_user_roundtrip(tmp_path) -> None:
    db_path = tmp_path / "sterling_test.db"
    url = f"sqlite:///{db_path.as_posix()}"
    eng = create_db_engine(url)
    # Bind global for ensure_schema path
    from app.core import database as dbmod

    dbmod._engine = eng
    dbmod._SessionLocal = __import__("sqlalchemy.orm", fromlist=["sessionmaker"]).sessionmaker(
        bind=eng, autocommit=False, autoflush=False, expire_on_commit=False
    )
    dbmod._using_sqlite = True
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=eng)
    Session = dbmod._SessionLocal
    assert Session is not None
    with Session() as db:
        u = User(
            name="Exec",
            email="exec@sterling.test",
            password_hash=hash_password("password123"),
            skills=["python", "fastapi"],
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        found = db.scalar(select(User).where(User.email == "exec@sterling.test"))
        assert found is not None
        assert found.skills == ["python", "fastapi"]
        assert found.id is not None
    with eng.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
        assert n == 1
