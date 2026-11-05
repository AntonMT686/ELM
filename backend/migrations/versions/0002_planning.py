"""Planning and task lifecycle (architecture §9) and legacy-import bookkeeping.

Written by hand and idempotent, because 0001 builds the schema with metadata.create_all: on a fresh database these
tables and columns already exist when this runs, while a database created at 0001 before this release needs them added.

Revision ID: 0002_planning
Revises: 0001_baseline
Create Date: 2026-11-04
"""
import uuid

import sqlalchemy as sa
from alembic import op

from app.core.db import Base
import app.models  # noqa: F401
from app.seed import PHASES

revision = "0002_planning"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

NEW_TABLES = [
    "plan_phases", "project_plans", "milestones", "work_packages", "work_package_orgs", "plan_activities", "task_dependencies", "task_participants",
    "task_checklist_items", "task_deliverables", "task_comments", "work_item_events", "plan_baselines", "legacy_import_runs", "legacy_import_map", "legacy_audit_records",
]
NEW_COLUMNS = [
    ("plan_id", sa.Uuid(), "project_plans.id", True), ("work_package_id", sa.Uuid(), "work_packages.id", True), ("activity_id", sa.Uuid(), "plan_activities.id", True),
    ("milestone_id", sa.Uuid(), "milestones.id", True), ("parent_id", sa.Uuid(), "work_items.id", True),
    ("reported_progress", sa.Float(), None, False), ("estimated_hours", sa.Float(), None, False), ("actual_hours", sa.Float(), None, False), ("weight", sa.Float(), None, False),
    ("actual_start", sa.Date(), None, False), ("actual_end", sa.Date(), None, False), ("sort_order", sa.Integer(), None, False),
    ("legacy_key", sa.String(80), None, False), ("legacy_type", sa.String(60), None, False),
]
NOT_NULL_DEFAULTS = {"reported_progress": "0", "estimated_hours": "0", "actual_hours": "0", "sort_order": "0"}
OLD_TO_NEW = {"TODO": "OPEN", "BLOCKED": "ON_HOLD", "DONE": "COMPLETED"}
NEW_TO_OLD = {"OPEN": "TODO", "ON_HOLD": "BLOCKED", "COMPLETED": "DONE", "REVIEW": "IN_PROGRESS", "CHANGES_REQUESTED": "IN_PROGRESS"}
PLAN_MANAGERS = ["PGD", "TD", "DIR_HEAD", "PE"]


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    wanted = [Base.metadata.tables[n] for n in NEW_TABLES if n not in existing]
    Base.metadata.create_all(bind=bind, tables=wanted)

    have = {c["name"] for c in inspector.get_columns("work_items")}
    with op.batch_alter_table("work_items") as batch:
        for name, typ, fk, indexed in NEW_COLUMNS:
            if name in have:
                continue
            batch.add_column(sa.Column(name, typ, nullable=name not in NOT_NULL_DEFAULTS, server_default=NOT_NULL_DEFAULTS.get(name)))
            if fk:
                batch.create_foreign_key(f"fk_work_items_{name}", fk.split(".")[0], [name], ["id"])
            if indexed:
                batch.create_index(f"ix_work_items_{name}", [name])

    items = sa.table("work_items", sa.column("status", sa.String), sa.column("progress", sa.Float), sa.column("reported_progress", sa.Float))
    for old, new in OLD_TO_NEW.items():
        bind.execute(items.update().where(items.c.status == old).values(status=new))
    # Keep what assignees reported; "progress" is calculated from status and this value from now on.
    bind.execute(items.update().where(items.c.reported_progress == 0).values(reported_progress=items.c.progress))

    roles = sa.table("roles", sa.column("id", sa.Uuid), sa.column("code", sa.String))
    role_permissions = sa.table("role_permissions", sa.column("id", sa.Uuid), sa.column("role_id", sa.Uuid), sa.column("permission", sa.String))
    for rid in bind.execute(sa.select(roles.c.id).where(roles.c.code.in_(PLAN_MANAGERS))).scalars().all():
        if not bind.execute(sa.select(role_permissions.c.id).where(role_permissions.c.role_id == rid, role_permissions.c.permission == "plan.manage")).first():
            bind.execute(role_permissions.insert().values(id=uuid.uuid4(), role_id=rid, permission="plan.manage"))

    # Only an upgraded install has users already; a fresh one gets its phases from app.seed.
    users = sa.table("users", sa.column("id", sa.Uuid))
    phases = sa.table(
        "plan_phases", sa.column("id", sa.Uuid), sa.column("project_id", sa.Uuid), sa.column("code", sa.String), sa.column("name", sa.String), sa.column("sort_order", sa.Integer),
        sa.column("weight", sa.Float), sa.column("active", sa.Boolean), sa.column("created_at", sa.DateTime), sa.column("updated_at", sa.DateTime),
    )
    if bind.execute(sa.select(users.c.id).limit(1)).first() and not bind.execute(sa.select(phases.c.id).where(phases.c.project_id.is_(None)).limit(1)).first():
        now = sa.func.now()
        for i, (code, name) in enumerate(PHASES):
            bind.execute(phases.insert().values(id=uuid.uuid4(), project_id=None, code=code, name=name, sort_order=i, weight=1.0, active=True, created_at=now, updated_at=now))


def downgrade():
    # DEV only, like 0001: planning records are dropped. REVIEW and CHANGES_REQUESTED tasks fall back to IN_PROGRESS.
    bind = op.get_bind()
    items = sa.table("work_items", sa.column("status", sa.String))
    for new, old in NEW_TO_OLD.items():
        bind.execute(items.update().where(items.c.status == new).values(status=old))
    # Constraint names differ by install path (create_all names them, upgrade uses fk_work_items_*), so look them up.
    inspector = sa.inspect(bind)
    fk_names = {f["constrained_columns"][0]: f["name"] for f in inspector.get_foreign_keys("work_items") if f.get("name")}
    index_names = {i["column_names"][0]: i["name"] for i in inspector.get_indexes("work_items") if len(i["column_names"]) == 1}
    with op.batch_alter_table("work_items") as batch:
        for name, _, _, _ in reversed(NEW_COLUMNS):
            if name in index_names:
                batch.drop_index(index_names[name])
            if name in fk_names:
                batch.drop_constraint(fk_names[name], type_="foreignkey")
            batch.drop_column(name)
    for name in reversed(NEW_TABLES):
        op.drop_table(name)
