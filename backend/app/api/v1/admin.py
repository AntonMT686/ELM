"""Organization structure, users, roles & scoped assignments, delegations, document types, domains."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.core.deps import Ctx, get_ctx, get_or_404
from app.core.errors import AppError, Conflict, NotFound
from app.core.permissions import PERMISSIONS
from app.core.security import hash_password
from app.models import (
    Delegation,
    DocumentType,
    EngineeringItem,
    OrgUnit,
    ProcessDomain,
    Project,
    Role,
    RoleAssignment,
    RolePermission,
    User,
    UserOrgAssignment,
)
from app.services.serial import doc_type_dict, iso, org_brief, user_brief

router = APIRouter(tags=["administration"])


# ------------------------------------------------------------------ organization
class OrgIn(BaseModel):
    parent_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=200)
    unit_type: str = Field(pattern=r"^(ORGANIZATION|HEAD_DIRECTORATE|DIRECTORATE|DIVISION|DEPARTMENT|GROUP)$")
    description: str | None = None
    is_oversight: bool = False
    active: bool = True


@router.get("/org-units")
def org_tree(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.execute(select(OrgUnit).order_by(OrgUnit.sort_order, OrgUnit.name)).scalars().all()
    counts = dict(ctx.db.execute(select(UserOrgAssignment.org_unit_id, func.count()).group_by(UserOrgAssignment.org_unit_id)).all())
    return [{**org_brief(o), "parent_id": str(o.parent_id) if o.parent_id else None, "description": o.description, "is_oversight": o.is_oversight, "active": o.active, "members": counts.get(o.id, 0)} for o in rows]


def _path(ctx: Ctx, o: OrgUnit) -> str:
    if o.parent_id:
        par = ctx.db.get(OrgUnit, o.parent_id)
        return f"{par.path}{o.id}/"
    return f"/{o.id}/"


@router.post("/org-units")
def create_org(body: OrgIn, ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("admin.org")
    if ctx.db.execute(select(OrgUnit.id).where(OrgUnit.code == body.code)).first():
        raise Conflict("Code already in use.")
    o = OrgUnit(**body.model_dump())
    o.id = uuid.uuid4()
    o.path = _path(ctx, o)
    ctx.db.add(o)
    ctx.audit("org.create", "org_unit", o.id, f"Created {o.unit_type.lower()} {o.name}")
    ctx.db.commit()
    return org_brief(o)


@router.put("/org-units/{oid}")
def update_org(oid: uuid.UUID, body: OrgIn, ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("admin.org")
    o = get_or_404(ctx.db, OrgUnit, oid, "Organization unit")
    before = org_brief(o)
    moved = body.parent_id != o.parent_id
    if moved and body.parent_id and f"/{o.id}/" in (ctx.db.get(OrgUnit, body.parent_id).path):
        raise AppError("Cannot move a unit under its own descendant.")
    for k, v in body.model_dump().items():
        setattr(o, k, v)
    if moved:
        old = o.path
        o.path = _path(ctx, o)
        for d in ctx.db.execute(select(OrgUnit).where(OrgUnit.path.like(f"{old}%"), OrgUnit.id != o.id)).scalars():
            d.path = o.path + d.path[len(old):]
    ctx.audit("org.update", "org_unit", o.id, f"Updated {o.name}", {"before": before, "after": org_brief(o)})
    ctx.db.commit()
    return org_brief(o)


# ------------------------------------------------------------------ users
class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    full_name: str = Field(min_length=2, max_length=200)
    email: str | None = None
    employee_no: str | None = None
    designation: str | None = None
    primary_org_unit_id: uuid.UUID | None = None
    is_active: bool = True
    password: str | None = Field(default=None, min_length=10)
    org_unit_ids: list[uuid.UUID] = Field(default_factory=list)


def _user_full(ctx: Ctx, u: User) -> dict:
    orgs = ctx.db.execute(select(OrgUnit, UserOrgAssignment.position).join(UserOrgAssignment, UserOrgAssignment.org_unit_id == OrgUnit.id).where(UserOrgAssignment.user_id == u.id)).all()
    ras = ctx.db.execute(select(RoleAssignment).where(RoleAssignment.user_id == u.id)).scalars().all()
    return {
        **user_brief(u), "employee_no": u.employee_no, "is_active": u.is_active, "is_system_admin": u.is_system_admin, "auth_source": u.auth_source,
        "primary_org": org_brief(u.primary_org_unit), "last_login_at": iso(u.last_login_at),
        "orgs": [{**org_brief(o), "position": pos} for o, pos in orgs],
        "roles": [{"id": str(r.id), "role": {"id": str(r.role.id), "code": r.role.code, "name": r.role.name}, "scope_type": r.scope_type, "scope_id": str(r.scope_id) if r.scope_id else None, "scope_label": _scope_label(ctx, r.scope_type, r.scope_id), "valid_to": iso(r.valid_to)} for r in ras],
    }


def _scope_label(ctx: Ctx, st: str, sid) -> str:
    if st == "GLOBAL" or not sid:
        return "All (global)"
    m = {"ORG_UNIT": OrgUnit, "PROJECT": Project, "ENG_ITEM": EngineeringItem}.get(st)
    obj = ctx.db.get(m, sid) if m else None
    return f"{getattr(obj, 'code', '')} {getattr(obj, 'name', '')}".strip() if obj else str(sid)


@router.get("/users")
def list_users(q: str | None = None, org_unit_id: uuid.UUID | None = None, active: bool | None = None, limit: int = Query(200, le=1000), ctx: Ctx = Depends(get_ctx)):
    stmt = select(User).order_by(User.full_name)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(User.full_name).like(like), func.lower(User.username).like(like), func.lower(func.coalesce(User.employee_no, "")).like(like)))
    if org_unit_id:
        stmt = stmt.join(UserOrgAssignment, UserOrgAssignment.user_id == User.id).where(UserOrgAssignment.org_unit_id == org_unit_id)
    if active is not None:
        stmt = stmt.where(User.is_active.is_(active))
    users = ctx.db.execute(stmt.limit(limit)).scalars().all()
    if not ctx.p.has_any("admin.users"):
        return [{**user_brief(u), "primary_org": org_brief(u.primary_org_unit)} for u in users if u.is_active]
    return [_user_full(ctx, u) for u in users]


@router.post("/users")
def create_user(body: UserIn, ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("admin.users")
    if ctx.db.execute(select(User.id).where(func.lower(User.username) == body.username.lower())).first():
        raise Conflict("Username already exists.")
    u = User(username=body.username, full_name=body.full_name, email=body.email, employee_no=body.employee_no, designation=body.designation,
             primary_org_unit_id=body.primary_org_unit_id, is_active=body.is_active, password_hash=hash_password(body.password) if body.password else None)
    ctx.db.add(u)
    ctx.db.flush()
    for oid in set(body.org_unit_ids) | ({body.primary_org_unit_id} if body.primary_org_unit_id else set()):
        ctx.db.add(UserOrgAssignment(user_id=u.id, org_unit_id=oid))
    ctx.audit("user.create", "user", u.id, f"Created user {u.username}")
    ctx.db.commit()
    return _user_full(ctx, u)


@router.put("/users/{uid}")
def update_user(uid: uuid.UUID, body: UserIn, ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("admin.users")
    u = ctx.db.get(User, uid)
    if not u:
        raise NotFound("User not found")
    for k in ("full_name", "email", "employee_no", "designation", "primary_org_unit_id", "is_active"):
        setattr(u, k, getattr(body, k))
    if body.password:
        u.password_hash = hash_password(body.password)
    existing = {a.org_unit_id: a for a in ctx.db.execute(select(UserOrgAssignment).where(UserOrgAssignment.user_id == u.id)).scalars()}
    want = set(body.org_unit_ids) | ({body.primary_org_unit_id} if body.primary_org_unit_id else set())
    for oid, a in existing.items():
        if oid not in want:
            ctx.db.delete(a)
    for oid in want - set(existing):
        ctx.db.add(UserOrgAssignment(user_id=u.id, org_unit_id=oid))
    ctx.audit("user.update", "user", u.id, f"Updated user {u.username}", {"active": u.is_active, "orgs": [str(x) for x in want], "password_reset": bool(body.password)})
    ctx.db.commit()
    return _user_full(ctx, u)


# ------------------------------------------------------------------ roles & assignments
@router.get("/permissions")
def permission_catalogue(ctx: Ctx = Depends(get_ctx)):
    return [{"code": k, "description": v} for k, v in PERMISSIONS.items()]


class RoleIn(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Z0-9_]+$")
    name: str
    description: str | None = None
    permissions: list[str] = Field(default_factory=list)
    active: bool = True


@router.get("/roles")
def list_roles(ctx: Ctx = Depends(get_ctx)):
    roles = ctx.db.execute(select(Role).order_by(Role.name)).scalars().all()
    perms: dict = {}
    for rp in ctx.db.execute(select(RolePermission)).scalars():
        perms.setdefault(rp.role_id, []).append(rp.permission)
    counts = dict(ctx.db.execute(select(RoleAssignment.role_id, func.count()).group_by(RoleAssignment.role_id)).all())
    return [{"id": str(r.id), "code": r.code, "name": r.name, "description": r.description, "active": r.active, "is_system": r.is_system, "permissions": sorted(perms.get(r.id, [])), "assignments": counts.get(r.id, 0)} for r in roles]


@router.post("/roles")
def upsert_role(body: RoleIn, ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("admin.users")
    bad = [p for p in body.permissions if p not in PERMISSIONS]
    if bad:
        raise AppError(f"Unknown permissions: {', '.join(bad)}")
    r = ctx.db.execute(select(Role).where(Role.code == body.code)).scalar_one_or_none()
    if not r:
        r = Role(code=body.code, name=body.name)
        ctx.db.add(r)
        ctx.db.flush()
    r.name, r.description, r.active = body.name, body.description, body.active
    for rp in ctx.db.execute(select(RolePermission).where(RolePermission.role_id == r.id)).scalars():
        ctx.db.delete(rp)
    ctx.db.flush()
    for p in set(body.permissions):
        ctx.db.add(RolePermission(role_id=r.id, permission=p))
    ctx.audit("role.upsert", "role", r.id, f"Role {r.code} saved", {"permissions": sorted(set(body.permissions))})
    ctx.db.commit()
    return {"id": str(r.id)}


class AssignIn(BaseModel):
    user_id: uuid.UUID
    role_id: uuid.UUID
    scope_type: str = Field(pattern=r"^(GLOBAL|ORG_UNIT|PROJECT|ENG_ITEM)$")
    scope_id: uuid.UUID | None = None
    valid_to: datetime | None = None


@router.post("/role-assignments")
def assign_role(body: AssignIn, ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("admin.users")
    if body.scope_type != "GLOBAL" and not body.scope_id:
        raise AppError("Choose the scope (directorate / project / item) for this role.")
    ra = RoleAssignment(user_id=body.user_id, role_id=body.role_id, scope_type=body.scope_type, scope_id=body.scope_id if body.scope_type != "GLOBAL" else None, valid_to=body.valid_to, granted_by_id=ctx.user.id)
    ctx.db.add(ra)
    role = ctx.db.get(Role, body.role_id)
    u = ctx.db.get(User, body.user_id)
    ctx.audit("role.assign", "user", body.user_id, f"Granted {role.code} to {u.username} ({_scope_label(ctx, body.scope_type, body.scope_id)})")
    ctx.db.commit()
    return {"id": str(ra.id)}


@router.delete("/role-assignments/{aid}")
def revoke_role(aid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("admin.users")
    ra = ctx.db.get(RoleAssignment, aid)
    if not ra:
        raise NotFound("Assignment not found")
    ctx.audit("role.revoke", "user", ra.user_id, f"Revoked {ra.role.code} ({_scope_label(ctx, ra.scope_type, ra.scope_id)})")
    ctx.db.delete(ra)
    ctx.db.commit()
    return {"ok": True}


class DelegationIn(BaseModel):
    to_user_id: uuid.UUID
    valid_from: datetime
    valid_to: datetime
    reason: str = Field(min_length=3)


@router.get("/delegations")
def my_delegations(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.execute(select(Delegation).where(or_(Delegation.from_user_id == ctx.user.id, Delegation.to_user_id == ctx.user.id)).order_by(Delegation.valid_from.desc())).scalars().all()
    return [{"id": str(d.id), "from": user_brief(ctx.db.get(User, d.from_user_id)), "to": user_brief(ctx.db.get(User, d.to_user_id)), "valid_from": iso(d.valid_from), "valid_to": iso(d.valid_to), "reason": d.reason, "active": d.active} for d in rows]


@router.post("/delegations")
def delegate(body: DelegationIn, ctx: Ctx = Depends(get_ctx)):
    if body.to_user_id == ctx.user.id or body.valid_to <= body.valid_from:
        raise AppError("Choose another person and a valid period.")
    d = Delegation(from_user_id=ctx.user.id, to_user_id=body.to_user_id, valid_from=body.valid_from, valid_to=body.valid_to, reason=body.reason)
    ctx.db.add(d)
    ctx.audit("delegation.create", "user", ctx.user.id, f"Delegated workflow tasks to {ctx.db.get(User, body.to_user_id).full_name}")
    ctx.db.commit()
    return {"id": str(d.id)}


# ------------------------------------------------------------------ document types & domains
class DocTypeIn(BaseModel):
    code: str = Field(min_length=2, max_length=30, pattern=r"^[A-Z0-9_-]+$")
    name: str
    category: str = Field(default="ENGINEERING", pattern=r"^(ENGINEERING|MANAGEMENT|NON_ENGINEERING)$")
    description: str | None = None
    numbering_pattern: str = "{PROJECT}-{TYPE}-{SEQ:4}"
    revision_scheme: str = Field(default="ALPHA", pattern=r"^(ALPHA|NUMERIC)$")
    allowed_extensions: str = "docx,xlsx,pptx,pdf"
    default_template: str | None = None
    requires_signature: bool = True
    applicable_levels: str | None = None
    icon: str | None = None
    color: str | None = None
    active: bool = True


@router.get("/document-types")
def list_doc_types(ctx: Ctx = Depends(get_ctx)):
    return [doc_type_dict(t) for t in ctx.db.execute(select(DocumentType).order_by(DocumentType.category, DocumentType.name)).scalars()]


@router.post("/document-types")
def upsert_doc_type(body: DocTypeIn, ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("admin.config")
    t = ctx.db.execute(select(DocumentType).where(DocumentType.code == body.code)).scalar_one_or_none() or DocumentType(code=body.code)
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    ctx.db.add(t)
    ctx.audit("doctype.upsert", "document_type", body.code, f"Document type {body.code} saved", body.model_dump())
    ctx.db.commit()
    return doc_type_dict(t)


@router.get("/process-domains")
def list_domains(ctx: Ctx = Depends(get_ctx)):
    return [{"id": str(d.id), "code": d.code, "name": d.name, "is_engineering": d.is_engineering, "color": d.color} for d in ctx.db.execute(select(ProcessDomain).where(ProcessDomain.active.is_(True)).order_by(ProcessDomain.name)).scalars()]
