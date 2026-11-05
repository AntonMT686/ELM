"""Scope-aware authorization (RBAC + organization / project / engineering-item scope). Deny by default."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import Forbidden
from app.models import (
    Document,
    DocumentAccessGrant,
    EngineeringItem,
    OrgUnit,
    RoleAssignment,
    RolePermission,
    User,
    UserOrgAssignment,
    WorkflowInstance,
    WorkflowTask,
)

ADMIN_PERMS = {"admin.org", "admin.users", "admin.config", "audit.view", "workflow.configure", "project.view"}


@dataclass
class Grant:
    perms: set[str]
    scope_type: str
    scope_id: uuid.UUID | None
    include_descendants: bool
    role_code: str


@dataclass
class Principal:
    user: User
    grants: list[Grant] = field(default_factory=list)
    org_ids: set[uuid.UUID] = field(default_factory=set)
    org_paths: list[str] = field(default_factory=list)

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    def all_perms(self) -> set[str]:
        out: set[str] = set()
        for g in self.grants:
            out |= g.perms
        return out

    def role_codes(self) -> set[str]:
        return {g.role_code for g in self.grants}

    def has_any(self, perm: str) -> bool:
        return any(perm in g.perms for g in self.grants)

    def has_global(self, perm: str) -> bool:
        return any(perm in g.perms and g.scope_type == "GLOBAL" for g in self.grants)

    def has(
        self,
        perm: str,
        *,
        project_id: uuid.UUID | None = None,
        item_path: str | None = None,
        org_path: str | None = None,
    ) -> bool:
        for g in self.grants:
            if perm not in g.perms:
                continue
            if g.scope_type == "GLOBAL":
                return True
            sid = str(g.scope_id)
            if g.scope_type == "PROJECT" and project_id and g.scope_id == project_id:
                return True
            if g.scope_type == "ORG_UNIT" and org_path:
                if (g.include_descendants and f"/{sid}/" in org_path) or org_path.endswith(f"/{sid}/"):
                    return True
            if g.scope_type == "ENG_ITEM" and item_path:
                if (g.include_descendants and f"/{sid}/" in item_path) or item_path.endswith(f"/{sid}/"):
                    return True
        return False

    def require(self, perm: str, **scope) -> None:
        if not self.has(perm, **scope):
            raise Forbidden("You do not have permission to perform this action in this scope.", details={"permission": perm})


def load_principal(db: Session, user: User) -> Principal:
    now = utcnow()
    rows = db.execute(
        select(RoleAssignment).where(
            RoleAssignment.user_id == user.id,
            or_(RoleAssignment.valid_from.is_(None), RoleAssignment.valid_from <= now),
            or_(RoleAssignment.valid_to.is_(None), RoleAssignment.valid_to >= now),
        )
    ).scalars().all()
    role_ids = {r.role_id for r in rows}
    perms_by_role: dict[uuid.UUID, set[str]] = {}
    if role_ids:
        for rp in db.execute(select(RolePermission).where(RolePermission.role_id.in_(role_ids))).scalars():
            perms_by_role.setdefault(rp.role_id, set()).add(rp.permission)
    p = Principal(user=user)
    for r in rows:
        if r.role and not r.role.active:
            continue
        p.grants.append(Grant(perms_by_role.get(r.role_id, set()), r.scope_type, r.scope_id, r.include_descendants, r.role.code))
    if user.is_system_admin:
        # Platform administration only — no document approval or release authority is implied.
        p.grants.append(Grant(set(ADMIN_PERMS), "GLOBAL", None, True, "SYSADMIN"))
    memberships = db.execute(
        select(OrgUnit).join(UserOrgAssignment, UserOrgAssignment.org_unit_id == OrgUnit.id).where(UserOrgAssignment.user_id == user.id)
    ).scalars().all()
    p.org_ids = {o.id for o in memberships}
    p.org_paths = [o.path for o in memberships]
    return p


# ---------------------------------------------------------------- scope expansion helpers

def _expand_org(db: Session, ids: set[uuid.UUID]) -> set[uuid.UUID]:
    if not ids:
        return set()
    conds = [OrgUnit.path.like(f"%/{i}/%") for i in ids]
    return set(db.execute(select(OrgUnit.id).where(or_(*conds))).scalars()) | ids


def _expand_items(db: Session, ids: set[uuid.UUID]) -> set[uuid.UUID]:
    if not ids:
        return set()
    conds = [EngineeringItem.path.like(f"%/{i}/%") for i in ids]
    return set(db.execute(select(EngineeringItem.id).where(or_(*conds))).scalars()) | ids


def user_org_ancestors(db: Session, p: Principal) -> set[uuid.UUID]:
    """Org units the user belongs to plus their ancestors (a grant to a directorate reaches its departments' members)."""
    out: set[uuid.UUID] = set()
    for path in p.org_paths:
        out |= {uuid.UUID(x) for x in path.strip("/").split("/") if x}
    return out


def document_visibility_clause(db: Session, p: Principal, perm: str = "doc.view"):
    """SQL filter for documents the principal may see. Server-side; never trust the UI."""
    if p.has_global(perm):
        return None
    project_ids, org_ids, item_ids = set(), set(), set()
    for g in p.grants:
        if perm not in g.perms or g.scope_id is None:
            continue
        if g.scope_type == "PROJECT":
            project_ids.add(g.scope_id)
        elif g.scope_type == "ORG_UNIT":
            org_ids.add(g.scope_id)
        elif g.scope_type == "ENG_ITEM":
            item_ids.add(g.scope_id)
    org_ids = _expand_org(db, org_ids)
    item_ids = _expand_items(db, item_ids)
    now = utcnow()
    my_orgs = user_org_ancestors(db, p)
    grant_q = select(DocumentAccessGrant.document_id).where(
        DocumentAccessGrant.revoked_at.is_(None),
        or_(DocumentAccessGrant.valid_to.is_(None), DocumentAccessGrant.valid_to >= now),
        or_(DocumentAccessGrant.user_id == p.id, DocumentAccessGrant.org_unit_id.in_(my_orgs or {uuid.uuid4()})),
    )
    task_q = (
        select(WorkflowInstance.document_id)
        .join(WorkflowTask, WorkflowTask.instance_id == WorkflowInstance.id)
        .where(WorkflowTask.assignee_id == p.id)
    )
    conds = [Document.owner_id == p.id, Document.id.in_(grant_q), Document.id.in_(task_q)]
    if project_ids:
        conds.append(Document.project_id.in_(project_ids))
    if org_ids:
        conds.append(Document.owner_org_unit_id.in_(org_ids))
    if item_ids:
        conds.append(Document.item_id.in_(item_ids))
    if p.has_any("release.view_all"):
        conds.append(and_(Document.released_revision_id.is_not(None)))
    return or_(*conds)


def can_view_document(db: Session, p: Principal, doc: Document) -> bool:
    clause = document_visibility_clause(db, p)
    if clause is None:
        return True
    return db.execute(select(Document.id).where(Document.id == doc.id, clause)).first() is not None


def doc_scope(db: Session, doc: Document) -> dict:
    item_path = None
    org_path = None
    if doc.item_id:
        it = db.get(EngineeringItem, doc.item_id)
        item_path = it.path if it else None
    if doc.owner_org_unit_id:
        ou = db.get(OrgUnit, doc.owner_org_unit_id)
        org_path = ou.path if ou else None
    return {"project_id": doc.project_id, "item_path": item_path, "org_path": org_path}


def can_on_document(db: Session, p: Principal, doc: Document, perm: str) -> bool:
    if perm in ("doc.edit",) and doc.owner_id == p.id:
        return True
    if p.has(perm, **doc_scope(db, doc)):
        return True
    if perm in ("doc.view", "doc.download", "doc.edit"):
        now = utcnow()
        my_orgs = user_org_ancestors(db, p)
        grants = db.execute(
            select(DocumentAccessGrant).where(
                DocumentAccessGrant.document_id == doc.id,
                DocumentAccessGrant.revoked_at.is_(None),
                or_(DocumentAccessGrant.valid_to.is_(None), DocumentAccessGrant.valid_to >= now),
                or_(DocumentAccessGrant.user_id == p.id, DocumentAccessGrant.org_unit_id.in_(my_orgs or {uuid.uuid4()})),
            )
        ).scalars().all()
        short = perm.split(".")[1]
        if any(short in g.permissions.split(",") for g in grants):
            return True
        if perm in ("doc.view", "doc.download"):
            return can_view_document(db, p, doc)
    return False
