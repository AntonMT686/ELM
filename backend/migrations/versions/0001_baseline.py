"""Baseline schema (session 1).

Creates all tables from the SQLAlchemy metadata. From the next schema change onward, generate explicit,
reviewed migrations with `alembic revision --autogenerate -m "..."` (see HANDOFF.md).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-03
"""
from alembic import op

from app.core.db import Base
import app.models  # noqa: F401

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind())


def downgrade():
    # Controlled records must never be dropped silently in UAT/PROD; downgrade is DEV-only.
    Base.metadata.drop_all(bind=op.get_bind())
