"""Alembic environment — URL comes from ELM_DATABASE_URL (never hard-coded)."""
from alembic import context

from app.core.config import get_settings
from app.core.db import Base, engine
import app.models  # noqa: F401  (register all tables)

target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=get_settings().database_url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
