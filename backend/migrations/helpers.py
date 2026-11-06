"""Small helpers shared by the hand-reviewed migrations.

Data steps are written as single conditional SQL statements on MySQL/MariaDB, so they behave the same when Alembic runs
against the database and when it writes the SQL file for a DBA (`alembic upgrade head --sql`, see database/mysql)."""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import context, op


def _mysql() -> bool:
    return op.get_context().dialect.name in ("mysql", "mariadb")


def _q(v: str) -> str:
    return "'" + v.replace("\\", "\\\\").replace("'", "''") + "'"


def grant(role_codes: list[str], permission: str) -> None:
    """Give a permission to system roles that exist already (fresh installs get it from app.seed)."""
    if _mysql():
        codes = ", ".join(_q(c) for c in role_codes)
        op.execute(
            f"INSERT INTO elm_role_permissions (id, role_id, permission) SELECT REPLACE(UUID(), '-', ''), r.id, {_q(permission)} FROM elm_roles r "
            f"WHERE r.code IN ({codes}) AND NOT EXISTS (SELECT 1 FROM elm_role_permissions p WHERE p.role_id = r.id AND p.permission = {_q(permission)})"
        )
        return
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    roles = sa.table("elm_roles", sa.column("id", sa.Uuid), sa.column("code", sa.String))
    perms = sa.table("elm_role_permissions", sa.column("id", sa.Uuid), sa.column("role_id", sa.Uuid), sa.column("permission", sa.String))
    for rid in bind.execute(sa.select(roles.c.id).where(roles.c.code.in_(role_codes))).scalars().all():
        if not bind.execute(sa.select(perms.c.id).where(perms.c.role_id == rid, perms.c.permission == permission)).first():
            bind.execute(perms.insert().values(id=uuid.uuid4(), role_id=rid, permission=permission))


def revoke(permission: str) -> None:
    op.execute(f"DELETE FROM elm_role_permissions WHERE permission = {_q(permission)}")


def insert_if_installed(table: str, key_col: str, rows: list[dict]) -> None:
    """Add reference rows to a database that already has users (an upgrade). A fresh install gets them from app.seed.
    Each row is inserted only if no row with the same key exists."""
    if not _mysql():
        if context.is_offline_mode():
            return
        bind = op.get_bind()
        if not bind.execute(sa.text("SELECT 1 FROM elm_users LIMIT 1")).first():
            return
    for row in rows:
        cols = ["id", *row.keys(), "created_at", "updated_at"]
        vals = ["REPLACE(UUID(), '-', '')" if _mysql() else _q(uuid.uuid4().hex)]
        for v in row.values():
            vals.append("1" if v is True else "0" if v is False else _q(str(v)))
        vals += ["CURRENT_TIMESTAMP(6)" if _mysql() else "CURRENT_TIMESTAMP"] * 2
        cond = f"EXISTS (SELECT 1 FROM elm_users) AND NOT EXISTS (SELECT 1 FROM {table} WHERE {key_col} = {_q(str(row[key_col]))})"
        frm = " FROM DUAL" if _mysql() else ""
        op.execute(f"INSERT INTO {table} ({', '.join(cols)}) SELECT {', '.join(vals)}{frm} WHERE {cond}")


def drop_tables(names: list[str]) -> None:
    """Drop tables (children first). MySQL refuses to drop indexes that back foreign keys, so drop whole tables only."""
    if _mysql():
        op.execute("SET FOREIGN_KEY_CHECKS=0")
    for n in names:
        op.drop_table(n)
    if _mysql():
        op.execute("SET FOREIGN_KEY_CHECKS=1")
