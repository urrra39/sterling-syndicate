from __future__ import annotations

"""Alembic environment — uses app settings for the DB URL."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.database import Base, resolve_database_url
from app.models import (  # noqa: F401 — register models with metadata
    AgentMemory,
    Contract,
    Conversation,
    Deliverable,
    Lead,
    Proposal,
    User,
)

config = context.config
# Use the same resolver the app uses at startup so migrations get the
# normalized postgresql+psycopg:// (v3) URL — not the raw postgres:// scheme,
# which SQLAlchemy would route to the psycopg2 dialect.
config.set_main_option("sqlalchemy.url", resolve_database_url())

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL only)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
