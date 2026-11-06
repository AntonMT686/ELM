"""Alembic environment — URL comes from ELM_DATABASE_URL (never hard-coded)."""
from alembic import context

from app.core.config import get_settings
from app.core.db import Base, engine
import app.models  # noqa: F401  (register all tables)

target_metadata = Base.metadata
# ELM shares the proflow_uat database with the legacy PMS tables, so its own tables (and this one) carry the elm_ prefix.
VERSION_TABLE = "elm_alembic_version"


def include_object(obj, name, type_, reflected, compare_to):
    """Ignore legacy PMS tables that live in the same database: never autogenerate a DROP for them."""
    if type_ == "table" and reflected and compare_to is None and not name.startswith("elm_"):
        return False
    return True


def run_migrations_offline():
    context.configure(url=get_settings().database_url, target_metadata=target_metadata, literal_binds=True, compare_type=True, version_table=VERSION_TABLE, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True, version_table=VERSION_TABLE, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
