"""Central Release Register and release packages."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.core.deps import Ctx, get_ctx, get_or_404
from app.core.errors import AppError, Forbidden
from app.models import (
    Document,
    DocumentRevision,
    DocumentType,
    EngineeringItem,
    OrgUnit,
    Project,
    ReleasePackage,
    ReleasePackageItem,
    ReleaseRegisterEntry,
    User,
)
from app.services import release as relsvc
from app.services.authz import can_on_document, doc_scope, document_visibility_clause
from app.services.numbering import next_seq
from app.services.serial import iso, item_brief, org_brief, user_brief

router = APIRouter(tags=["release register"])


def _entry(ctx: Ctx, e: ReleaseRegisterEntry) -> dict:
    db = ctx.db
    d = db.get(Document, e.document_id)
    rev = db.get(DocumentRevision, e.revision_id)
    t = db.get(DocumentType, d.type_id)
    p = db.get(Project, e.project_id) if e.project_id else None
    pkg = db.get(ReleasePackage, e.package_id) if e.package_id else None
    return {
        "id": str(e.id), "release_no": e.release_no, "status": e.status, "status_reason": e.status_reason, "released_at": iso(e.released_at),
        "document": {"id": str(d.id), "number": d.number, "title": d.title, "classification": d.classification},
        "type": {"code": t.code, "name": t.name, "color": t.color}, "revision": {"id": str(rev.id), "label": rev.label, "ext": rev.file.extension if rev.file else None},
        "project": {"id": str(p.id), "code": p.code, "name": p.name} if p else None, "item": item_brief(db, db.get(EngineeringItem, e.item_id)) if e.item_id else None,
        "owner_org": org_brief(db.get(OrgUnit, e.owner_org_unit_id)) if e.owner_org_unit_id else None,
        "sha256": e.sha256, "signature_count": e.signature_count, "released_by": user_brief(db.get(User, e.released_by_id)),
        "package": {"id": str(pkg.id), "code": pkg.code} if pkg else None,
    }


@router.get("/release-register")
def register(
    q: str | None = None,
    project_id: uuid.UUID | None = None,
    org_unit_id: uuid.UUID | None = None,
    type_id: uuid.UUID | None = None,
    status: str | None = "RELEASED",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, le=200),
    ctx: Ctx = Depends(get_ctx),
):
    stmt = select(ReleaseRegisterEntry).join(Document, Document.id == ReleaseRegisterEntry.document_id)
    vis = document_visibility_clause(ctx.db, ctx.p)
    if vis is not None:
        stmt = stmt.where(vis)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Document.number).like(like), func.lower(Document.title).like(like), func.lower(ReleaseRegisterEntry.release_no).like(like)))
    if project_id:
        stmt = stmt.where(ReleaseRegisterEntry.project_id == project_id)
    if org_unit_id:
        ou = get_or_404(ctx.db, OrgUnit, org_unit_id, "Unit")
        stmt = stmt.where(ReleaseRegisterEntry.owner_org_unit_id.in_(select(OrgUnit.id).where(OrgUnit.path.like(f"{ou.path}%"))))
    if type_id:
        stmt = stmt.where(Document.type_id == type_id)
    if status:
        stmt = stmt.where(ReleaseRegisterEntry.status.in_(status.split(",")))
    total = ctx.db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = ctx.db.execute(stmt.order_by(ReleaseRegisterEntry.released_at.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"total": total, "items": [_entry(ctx, e) for e in rows]}


class WithdrawIn(BaseModel):
    reason: str = Field(min_length=5)


@router.post("/release-register/{eid}/withdraw")
def withdraw(eid: uuid.UUID, body: WithdrawIn, ctx: Ctx = Depends(get_ctx)):
    e = get_or_404(ctx.db, ReleaseRegisterEntry, eid, "Release entry")
    d = ctx.db.get(Document, e.document_id)
    ctx.p.require("doc.withdraw", **doc_scope(ctx.db, d))
    relsvc.withdraw_entry(ctx.db, ctx.user, e, body.reason)
    ctx.db.commit()
    return _entry(ctx, e)


# ------------------------------------------------------------------ packages
class PackageIn(BaseModel):
    title: str = Field(min_length=3)
    project_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    release_note: str | None = None
    document_ids: list[uuid.UUID] = Field(default_factory=list)


def _pkg(ctx: Ctx, p: ReleasePackage) -> dict:
    items = ctx.db.execute(select(ReleasePackageItem).where(ReleasePackageItem.package_id == p.id)).scalars().all()
    out = []
    for it in items:
        d = ctx.db.get(Document, it.document_id)
        r = ctx.db.get(DocumentRevision, it.revision_id)
        out.append({"document": {"id": str(d.id), "number": d.number, "title": d.title}, "revision": {"id": str(r.id), "label": r.label, "status": r.status, "sha256": r.sha256}})
    return {"id": str(p.id), "code": p.code, "title": p.title, "status": p.status, "release_note": p.release_note, "released_at": iso(p.released_at),
            "released_by": user_brief(ctx.db.get(User, p.released_by_id)) if p.released_by_id else None, "manifest_sha256": p.manifest_sha256,
            "created_by": user_brief(ctx.db.get(User, p.created_by_id)), "created_at": iso(p.created_at), "items": out}


@router.get("/release-packages")
def list_packages(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.execute(select(ReleasePackage).order_by(ReleasePackage.created_at.desc()).limit(200)).scalars().all()
    return [_pkg(ctx, p) for p in rows]


@router.post("/release-packages")
def create_package(body: PackageIn, ctx: Ctx = Depends(get_ctx)):
    if not ctx.p.has_any("doc.release"):
        raise Forbidden("Only release authorities can prepare release packages.")
    proj = ctx.db.get(Project, body.project_id) if body.project_id else None
    code = f"PKG-{proj.code if proj else 'GEN'}-{next_seq(ctx.db, 'pkg:' + (proj.code if proj else 'GEN')):04d}"
    p = ReleasePackage(code=code, title=body.title, project_id=body.project_id, item_id=body.item_id, release_note=body.release_note, created_by_id=ctx.user.id)
    ctx.db.add(p)
    ctx.db.flush()
    for did in body.document_ids:
        d = get_or_404(ctx.db, Document, did, "Document")
        if not can_on_document(ctx.db, ctx.p, d, "doc.view"):
            raise Forbidden(f"No access to {d.number}.")
        rev = ctx.db.get(DocumentRevision, d.current_revision_id)
        if rev.status != "APPROVED":
            raise AppError(f"{d.number} rev {rev.label} is not approved yet.")
        ctx.p.require("doc.release", **doc_scope(ctx.db, d))
        ctx.db.add(ReleasePackageItem(package_id=p.id, document_id=d.id, revision_id=rev.id))
    ctx.audit("release.package_create", "release_package", p.id, f"Release package {code} prepared")
    ctx.db.commit()
    return _pkg(ctx, p)


@router.post("/release-packages/{pid}/release")
def release_pkg(pid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    p = get_or_404(ctx.db, ReleasePackage, pid, "Package")
    for it in ctx.db.execute(select(ReleasePackageItem).where(ReleasePackageItem.package_id == p.id)).scalars():
        d = ctx.db.get(Document, it.document_id)
        ctx.p.require("doc.release", **doc_scope(ctx.db, d))
        if d.owner_id == ctx.user.id:
            raise Forbidden(f"Separation of duties: you own {d.number}.")
    relsvc.release_package(ctx.db, ctx.user, p)
    ctx.db.commit()
    return _pkg(ctx, p)
