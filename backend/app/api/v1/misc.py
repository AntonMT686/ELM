"""Notifications, global search (command palette), audit trail."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import func, or_, select, update

from app.core.db import utcnow
from app.core.deps import Ctx, get_ctx
from app.models import AuditEvent, Document, EngineeringItem, Notification, Project, User
from app.services import audit as auditsvc
from app.services.authz import document_visibility_clause
from app.services.serial import iso, user_brief

router = APIRouter(tags=["platform"])


# ------------------------------------------------------------------ notifications
@router.get("/notifications")
def notifications(unread_only: bool = False, limit: int = Query(50, le=200), ctx: Ctx = Depends(get_ctx)):
    q = select(Notification).where(Notification.user_id == ctx.user.id)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    rows = ctx.db.execute(q.order_by(Notification.created_at.desc()).limit(limit)).scalars().all()
    unread = ctx.db.execute(select(func.count(Notification.id)).where(Notification.user_id == ctx.user.id, Notification.read_at.is_(None))).scalar()
    return {"unread": unread, "items": [{"id": str(n.id), "kind": n.kind, "title": n.title, "body": n.body, "link": n.link, "severity": n.severity, "created_at": iso(n.created_at), "read": n.read_at is not None} for n in rows]}


@router.post("/notifications/read")
def mark_read(ids: list[uuid.UUID] | None = Body(default=None), ctx: Ctx = Depends(get_ctx)):
    q = update(Notification).where(Notification.user_id == ctx.user.id, Notification.read_at.is_(None))
    if ids:
        q = q.where(Notification.id.in_(ids))
    ctx.db.execute(q.values(read_at=utcnow()))
    ctx.db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ search
@router.get("/search")
def search(q: str = Query(min_length=1, max_length=100), ctx: Ctx = Depends(get_ctx)):
    like = f"%{q.lower()}%"
    vis = document_visibility_clause(ctx.db, ctx.p)
    dq = select(Document).where(or_(func.lower(Document.number).like(like), func.lower(Document.title).like(like)))
    if vis is not None:
        dq = dq.where(vis)
    docs = ctx.db.execute(dq.order_by(Document.updated_at.desc()).limit(8)).scalars().all()
    items = ctx.db.execute(select(EngineeringItem).where(or_(func.lower(EngineeringItem.code).like(like), func.lower(EngineeringItem.name).like(like), func.lower(func.coalesce(EngineeringItem.part_number, "")).like(like))).limit(8)).scalars().all()
    people = ctx.db.execute(select(User).where(User.is_active.is_(True), or_(func.lower(User.full_name).like(like), func.lower(User.username).like(like))).limit(5)).scalars().all()
    projects = {p.id: p for p in ctx.db.execute(select(Project)).scalars()}
    return {
        "documents": [{"id": str(d.id), "number": d.number, "title": d.title, "status": d.status} for d in docs],
        "items": [{"id": str(i.id), "code": i.code, "name": i.name, "level": i.level.name, "project_id": str(i.project_id), "project": projects[i.project_id].code} for i in items],
        "people": [user_brief(u) for u in people],
    }


# ------------------------------------------------------------------ audit
@router.get("/audit")
def audit_list(q: str | None = None, action: str | None = None, entity_type: str | None = None, actor_id: uuid.UUID | None = None, page: int = 1, page_size: int = Query(50, le=200), ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("audit.view")
    stmt = select(AuditEvent)
    if q:
        stmt = stmt.where(func.lower(AuditEvent.summary).like(f"%{q.lower()}%"))
    if action:
        stmt = stmt.where(AuditEvent.action.like(f"{action}%"))
    if entity_type:
        stmt = stmt.where(AuditEvent.entity_type == entity_type)
    if actor_id:
        stmt = stmt.where(AuditEvent.actor_id == actor_id)
    total = ctx.db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = ctx.db.execute(stmt.order_by(AuditEvent.seq.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    ctx.audit("audit.read", "audit", None, "Audit trail viewed", {"q": q, "action": action})
    ctx.db.commit()
    return {"total": total, "items": [{"seq": e.seq, "at": iso(e.at), "action": e.action, "entity_type": e.entity_type, "entity_id": e.entity_id, "summary": e.summary, "outcome": e.outcome, "ip": e.ip,
                                       "actor": user_brief(ctx.db.get(User, e.actor_id)) if e.actor_id else None, "on_behalf_of": user_brief(ctx.db.get(User, e.on_behalf_of_id)) if e.on_behalf_of_id else None, "hash": e.hash, "prev_hash": e.prev_hash, "data": e.data} for e in rows]}


@router.get("/audit/verify")
def audit_verify(ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("audit.view")
    return auditsvc.verify_chain(ctx.db)
