"""Scope-aware dashboards (Head Directorate oversight → directorate → engineer)."""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.core.db import aware, utcnow
from app.core.deps import Ctx, get_ctx
from app.models import (
    AuditEvent,
    Document,
    DocumentType,
    OrgUnit,
    Project,
    ReleaseRegisterEntry,
    User,
    WorkflowInstance,
    WorkflowTask,
    WorkItem,
)
from app.services.authz import document_visibility_clause
from app.services.progress import weights
from app.services.serial import iso, user_brief
from app.services.task_lifecycle import closed_statuses


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(project_id: uuid.UUID | None = None, ctx: Ctx = Depends(get_ctx)):
    db, me = ctx.db, ctx.user
    now = utcnow()
    vis = document_visibility_clause(db, ctx.p)

    def scoped(q):
        q = q.where(vis) if vis is not None else q
        return q.where(Document.project_id == project_id) if project_id else q

    status_counts = dict(db.execute(scoped(select(Document.status, func.count())).group_by(Document.status)).all())
    my_pending = db.execute(select(WorkflowTask).where(WorkflowTask.assignee_id == me.id, WorkflowTask.status == "PENDING")).scalars().all()
    overdue = sum(1 for t in my_pending if t.due_at and aware(t.due_at) < now)
    my_drafts = db.execute(select(func.count(Document.id)).where(Document.owner_id == me.id, Document.status.in_(["DRAFT", "CHANGES_REQUESTED", "REJECTED"]))).scalar()
    rel_q = select(func.count(ReleaseRegisterEntry.id)).join(Document, Document.id == ReleaseRegisterEntry.document_id).where(ReleaseRegisterEntry.released_at >= now - timedelta(days=30))
    released_30 = db.execute(scoped(rel_q)).scalar()
    my_tasks_open = db.execute(select(func.count(WorkItem.id)).where(WorkItem.assignee_id == me.id, WorkItem.status.not_in(closed_statuses(db)))).scalar()

    # weekly release throughput (12 weeks)
    weeks = defaultdict(int)
    for (at,) in db.execute(scoped(select(ReleaseRegisterEntry.released_at).join(Document, Document.id == ReleaseRegisterEntry.document_id).where(ReleaseRegisterEntry.released_at >= now - timedelta(weeks=12)))).all():
        a = aware(at)
        weeks[(now - a).days // 7] += 1
    throughput = [{"week": f"W-{i}" if i else "This wk", "released": weeks.get(i, 0)} for i in range(11, -1, -1)]

    # review aging across visible scope
    vis_docs = select(Document.id)
    vis_docs = scoped(vis_docs)
    aging = {"0-2 d": 0, "3-7 d": 0, "8-14 d": 0, ">14 d": 0}
    pend = db.execute(select(WorkflowTask.created_at).join(WorkflowInstance, WorkflowInstance.id == WorkflowTask.instance_id).where(WorkflowTask.status == "PENDING", WorkflowInstance.document_id.in_(vis_docs))).all()
    for (c,) in pend:
        d = (now - aware(c)).days
        aging["0-2 d" if d <= 2 else "3-7 d" if d <= 7 else "8-14 d" if d <= 14 else ">14 d"] += 1

    # per-project & per-directorate
    w = weights(db)
    projects = []
    for p in db.execute(select(Project).order_by(Project.code)).scalars():
        c = dict(db.execute(scoped(select(Document.status, func.count()).where(Document.project_id == p.id)).group_by(Document.status)).all())
        total = sum(c.values())
        if not total and vis is not None:
            continue
        prog = round(sum(w.get(k, 0) * v for k, v in c.items()) / total, 1) if total else 0
        projects.append({"id": str(p.id), "code": p.code, "name": p.name, "color": p.color, "total": total, "released": c.get("RELEASED", 0), "in_review": c.get("IN_REVIEW", 0), "progress": prog})

    directorates = []
    for o in db.execute(select(OrgUnit).where(OrgUnit.unit_type.in_(["DIRECTORATE", "HEAD_DIRECTORATE"]), OrgUnit.active.is_(True)).order_by(OrgUnit.name)).scalars():
        sub = select(OrgUnit.id).where(OrgUnit.path.like(f"{o.path}%"))
        c = dict(db.execute(scoped(select(Document.status, func.count()).where(Document.owner_org_unit_id.in_(sub))).group_by(Document.status)).all())
        total = sum(c.values())
        if total:
            directorates.append({"id": str(o.id), "code": o.code, "name": o.name, "total": total, "counts": c, "progress": round(sum(w.get(k, 0) * v for k, v in c.items()) / total, 1)})

    recent_rel = db.execute(scoped(select(ReleaseRegisterEntry, Document).join(Document, Document.id == ReleaseRegisterEntry.document_id)).order_by(ReleaseRegisterEntry.released_at.desc()).limit(6)).all()
    recent_docs = [str(x) for x in db.execute(scoped(select(Document.id)).order_by(Document.updated_at.desc()).limit(80)).scalars()]
    acts = db.execute(select(AuditEvent).where(AuditEvent.entity_type == "document", AuditEvent.entity_id.in_(recent_docs or ["-"])).order_by(AuditEvent.seq.desc()).limit(12)).scalars().all()
    by_type = db.execute(scoped(select(DocumentType.name, DocumentType.color, func.count(Document.id)).join(Document, Document.type_id == DocumentType.id)).group_by(DocumentType.name, DocumentType.color).order_by(func.count(Document.id).desc()).limit(8)).all()

    return {
        "kpis": {"my_pending": len(my_pending), "my_overdue": overdue, "my_drafts": my_drafts, "in_review": status_counts.get("IN_REVIEW", 0),
                 "awaiting_release": status_counts.get("APPROVED", 0), "released_30d": released_30, "my_open_tasks": my_tasks_open, "total_docs": sum(status_counts.values())},
        "pipeline": [{"status": s, "count": status_counts.get(s, 0)} for s in ["DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED", "RELEASED"]],
        "throughput": throughput, "aging": [{"bucket": k, "count": v} for k, v in aging.items()],
        "projects": projects, "directorates": directorates,
        "by_type": [{"name": n, "color": c, "count": k} for n, c, k in by_type],
        "recent_releases": [{"release_no": e.release_no, "released_at": iso(e.released_at), "document": {"id": str(d.id), "number": d.number, "title": d.title}} for e, d in recent_rel],
        "activity": [{"at": iso(a.at), "summary": a.summary, "action": a.action, "actor": user_brief(db.get(User, a.actor_id)) if a.actor_id else None, "document_id": a.entity_id} for a in acts],
    }
