"""Requirement management (architecture §10).

Idempotent for the same reason as 0002: 0001 uses metadata.create_all, so on a fresh database these tables already exist.

Revision ID: 0003_requirements
Revises: 0002_planning
Create Date: 2026-11-05
"""
import uuid

import sqlalchemy as sa
from alembic import op

from app.core.db import Base
import app.models  # noqa: F401

revision = "0003_requirements"
down_revision = "0002_planning"
branch_labels = None
depends_on = None

NEW_TABLES = [
    "requirement_sources", "requirements", "requirement_revisions", "requirement_reviews", "requirement_links", "requirement_work_items", "requirement_documents", "requirement_events", "requirement_baselines", "requirement_baseline_items",
]
GRANTS = {"req.edit": ["PGD", "TD", "DIR_HEAD", "PE", "TEAM_MEMBER"], "req.baseline": ["PGD", "TD", "PE", "RELEASE_AUTH"]}


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[n] for n in NEW_TABLES if n not in existing])
    roles = sa.table("roles", sa.column("id", sa.Uuid), sa.column("code", sa.String))
    perms = sa.table("role_permissions", sa.column("id", sa.Uuid), sa.column("role_id", sa.Uuid), sa.column("permission", sa.String))
    for perm, codes in GRANTS.items():
        for rid in bind.execute(sa.select(roles.c.id).where(roles.c.code.in_(codes))).scalars().all():
            if not bind.execute(sa.select(perms.c.id).where(perms.c.role_id == rid, perms.c.permission == perm)).first():
                bind.execute(perms.insert().values(id=uuid.uuid4(), role_id=rid, permission=perm))


def downgrade():
    # DEV only, like 0001 and 0002: requirement records are dropped.
    bind = op.get_bind()
    perms = sa.table("role_permissions", sa.column("permission", sa.String))
    bind.execute(perms.delete().where(perms.c.permission.in_(list(GRANTS))))
    for name in reversed(NEW_TABLES):
        op.drop_table(name)
