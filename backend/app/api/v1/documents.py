"""Document register, revisions, content, sharing, relations, comments, workflow submit, release."""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.core.db import utcnow
from app.core.deps import Ctx, get_ctx, get_or_404
from app.core.errors import AppError, Forbidden
from app.models import (
    AuditEvent,
    Document,
    DocumentAccessGrant,
    DocumentAccessLog,
    DocumentComment,
    DocumentRelation,
    DocumentRevision,
    DocumentType,
    EngineeringItem,
    OrgUnit,
    ReleaseRegisterEntry,
    RevisionIteration,
    SignatureRecord,
    User,
    WorkflowInstance,
    WorkflowStageRun,
    WorkflowTask,
    WorkflowVersion,
)
from app.services import documents as docsvc
from app.services import release as relsvc
from app.services import storage
from app.services import workflow_engine as wf
from app.services.authz import can_on_document, doc_scope, document_visibility_clause
from app.services.serial import doc_dict, iso, org_brief, revision_dict, user_brief
from app.services.signature import get_provider

router = APIRouter(prefix="/documents", tags=["documents"])


def _doc(ctx: Ctx, did: uuid.UUID, perm: str = "doc.view") -> Document:
    d = get_or_404(ctx.db, Document, did, "Document")
    if not can_on_document(ctx.db, ctx.p, d, perm):
        # 404-style message would hide existence; ADA policy TBD — we return forbidden without metadata.
        raise Forbidden("You do not have access to this document.")
    return d


@router.get("")
def list_documents(
    q: str | None = None,
    project_id: uuid.UUID | None = None,
    item_id: uuid.UUID | None = None,
    subtree: bool = True,
    type_id: uuid.UUID | None = None,
    status: str | None = None,
    category: str | None = None,
    owner_org_unit_id: uuid.UUID | None = None,
    mine: bool = False,
    sort: str = "-updated_at",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    ctx: Ctx = Depends(get_ctx),
):
    stmt = select(Document)
    vis = document_visibility_clause(ctx.db, ctx.p)
    if vis is not None:
        stmt = stmt.where(vis)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Document.number).like(like), func.lower(Document.title).like(like), func.lower(func.coalesce(Document.keywords, "")).like(like)))
    if project_id:
        stmt = stmt.where(Document.project_id == project_id)
    if item_id:
        if subtree:
            it = get_or_404(ctx.db, EngineeringItem, item_id, "Item")
            sub = select(EngineeringItem.id).where(EngineeringItem.path.like(f"{it.path}%"))
            stmt = stmt.where(Document.item_id.in_(sub))
        else:
            stmt = stmt.where(Document.item_id == item_id)
    if type_id:
        stmt = stmt.where(Document.type_id == type_id)
    if status:
        stmt = stmt.where(Document.status.in_(status.split(",")))
    if category:
        stmt = stmt.join(DocumentType, DocumentType.id == Document.type_id).where(DocumentType.category == category)
    if owner_org_unit_id:
        stmt = stmt.where(Document.owner_org_unit_id == owner_org_unit_id)
    if mine:
        stmt = stmt.where(Document.owner_id == ctx.user.id)
    total = ctx.db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    col = {"updated_at": Document.updated_at, "number": Document.number, "title": Document.title, "status": Document.status, "created_at": Document.created_at}.get(sort.lstrip("-"), Document.updated_at)
    stmt = stmt.order_by(col.desc() if sort.startswith("-") else col.asc()).offset((page - 1) * page_size).limit(page_size)
    rows = ctx.db.execute(stmt).scalars().all()
    return {"total": total, "page": page, "page_size": page_size, "items": [doc_dict(ctx.db, d) for d in rows]}


@router.post("")
async def create_document(
    meta: str = Form(..., description="JSON metadata"),
    file: UploadFile | None = File(None),
    ctx: Ctx = Depends(get_ctx),
):
    try:
        m = json.loads(meta)
    except ValueError as e:
        raise AppError("Invalid metadata.") from e
    title = (m.get("title") or "").strip()
    if len(title) < 3:
        raise AppError("Title must be at least 3 characters.", code="VALIDATION_ERROR", details={"fields": [{"loc": ["title"], "msg": "Too short"}]})
    pid = uuid.UUID(m["project_id"]) if m.get("project_id") else None
    iid = uuid.UUID(m["item_id"]) if m.get("item_id") else None
    oid = uuid.UUID(m["owner_org_unit_id"]) if m.get("owner_org_unit_id") else None
    scope = {"project_id": pid}
    if iid:
        it = get_or_404(ctx.db, EngineeringItem, iid, "Item")
        scope = {"project_id": it.project_id, "item_path": it.path}
    if oid:
        scope["org_path"] = get_or_404(ctx.db, OrgUnit, oid, "Organization unit").path
    elif ctx.user.primary_org_unit:
        scope["org_path"] = ctx.user.primary_org_unit.path
    ctx.p.require("doc.create", **scope)
    content = None
    if file is not None and file.filename:
        content = (file.filename, await file.read())
    d = docsvc.create_document(
        ctx.db, ctx.user, type_id=uuid.UUID(m["type_id"]), title=title, project_id=pid, item_id=iid, owner_org_unit_id=oid,
        domain_id=uuid.UUID(m["domain_id"]) if m.get("domain_id") else None, classification=m.get("classification") or "RESTRICTED",
        description=m.get("description"), keywords=m.get("keywords"), content=content, from_template=bool(m.get("from_template", True)),
        parent_id=uuid.UUID(m["parent_id"]) if m.get("parent_id") else None,
    )
    ctx.db.commit()
    return doc_dict(ctx.db, d, full=True)


@router.get("/{did}")
def get_document(did: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    db = ctx.db
    d = _doc(ctx, did)
    revs = db.execute(select(DocumentRevision).where(DocumentRevision.document_id == d.id).order_by(DocumentRevision.revision_no.desc())).scalars().all()
    cur = db.get(DocumentRevision, d.current_revision_id) if d.current_revision_id else None
    iters = db.execute(select(RevisionIteration).where(RevisionIteration.revision_id == cur.id).order_by(RevisionIteration.iteration.desc())).scalars().all() if cur else []
    rels = db.execute(select(DocumentRelation).where(or_(DocumentRelation.source_id == d.id, DocumentRelation.target_id == d.id))).scalars().all()
    rel_out = []
    for r in rels:
        other_id = r.target_id if r.source_id == d.id else r.source_id
        other = db.get(Document, other_id)
        visible = can_on_document(db, ctx.p, other, "doc.view")
        rel_out.append({"id": str(r.id), "relation_type": r.relation_type, "direction": "out" if r.source_id == d.id else "in",
                        "document": doc_dict(db, other) if visible else {"id": str(other.id), "number": "Restricted", "title": "You do not have access", "status": None, "restricted": True}})
    grants = db.execute(select(DocumentAccessGrant).where(DocumentAccessGrant.document_id == d.id, DocumentAccessGrant.revoked_at.is_(None))).scalars().all()
    sigs = db.execute(select(SignatureRecord).where(SignatureRecord.revision_id.in_([r.id for r in revs] or [uuid.uuid4()])).order_by(SignatureRecord.signed_at)).scalars().all()
    regs = db.execute(select(ReleaseRegisterEntry).where(ReleaseRegisterEntry.document_id == d.id).order_by(ReleaseRegisterEntry.released_at.desc())).scalars().all()
    active = db.execute(select(WorkflowInstance).where(WorkflowInstance.document_id == d.id, WorkflowInstance.status == "ACTIVE")).scalars().first()
    can_edit = can_on_document(db, ctx.p, d, "doc.edit")
    scope = doc_scope(db, d)
    my_task = None
    if active:
        t = db.execute(select(WorkflowTask).where(WorkflowTask.instance_id == active.id, WorkflowTask.assignee_id == ctx.user.id, WorkflowTask.status == "PENDING")).scalars().first()
        my_task = str(t.id) if t else None
    db.add(DocumentAccessLog(document_id=d.id, revision_id=cur.id if cur else None, user_id=ctx.user.id, action="VIEW", at=utcnow()))
    db.commit()
    return {
        **doc_dict(db, d, full=True),
        "revisions": [revision_dict(db, r) for r in revs],
        "iterations": [{"iteration": i.iteration, "sha256": i.sha256, "source": i.source, "note": i.note, "created_at": iso(i.created_at), "by": user_brief(db.get(User, i.created_by_id)) if i.created_by_id else None, "size": i.file.size_bytes} for i in iters],
        "relations": rel_out,
        "grants": [{"id": str(g.id), "user": user_brief(db.get(User, g.user_id)) if g.user_id else None, "org": org_brief(db.get(OrgUnit, g.org_unit_id)) if g.org_unit_id else None, "permissions": g.permissions.split(","), "valid_to": iso(g.valid_to), "reason": g.reason, "granted_by": user_brief(db.get(User, g.granted_by_id))} for g in grants],
        "signatures": [{"id": str(s.id), "revision_id": str(s.revision_id), "signer": user_brief(db.get(User, s.signer_id)), "role": s.signer_role, "provider": s.provider, "algorithm": s.algorithm, "subject": s.certificate_subject, "serial": s.certificate_serial, "signed_at": iso(s.signed_at), "sha256": s.signed_sha256, "status": s.status, "is_cryptographic": s.is_cryptographic} for s in sigs],
        "releases": [{"id": str(e.id), "release_no": e.release_no, "revision_id": str(e.revision_id), "released_at": iso(e.released_at), "status": e.status, "by": user_brief(db.get(User, e.released_by_id)), "sha256": e.sha256} for e in regs],
        "active_workflow_id": str(active.id) if active else None,
        "my_task_id": my_task,
        "permissions": {
            "edit": can_edit and bool(cur and not cur.locked),
            "submit": can_edit and bool(cur and cur.status in wf.OPEN_REVISION_STATES and cur.file_id),
            "revise": can_edit and bool(cur and cur.status in ("RELEASED", "WITHDRAWN", "SUPERSEDED")),
            "release": ctx.p.has("doc.release", **scope) and bool(cur and cur.status == "APPROVED"),
            "withdraw": ctx.p.has("doc.withdraw", **scope),
            "share": d.owner_id == ctx.user.id or ctx.p.has("doc.share", **scope),
            "download": can_on_document(db, ctx.p, d, "doc.download"),
            "withdraw_submission": bool(active and active.initiator_id == ctx.user.id),
        },
    }


@router.get("/{did}/workflow")
def document_workflow(did: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    """All review cycles with stage runs and decisions (for the visual lifecycle tracker)."""
    db = ctx.db
    d = _doc(ctx, did)
    out = []
    for inst in db.execute(select(WorkflowInstance).where(WorkflowInstance.document_id == d.id).order_by(WorkflowInstance.created_at.desc())).scalars():
        v = db.get(WorkflowVersion, inst.version_id)
        spec = wf.spec_of(v)
        runs = {r.stage_key: r for r in db.execute(select(WorkflowStageRun).where(WorkflowStageRun.instance_id == inst.id)).scalars()}
        tasks = db.execute(select(WorkflowTask).where(WorkflowTask.instance_id == inst.id).order_by(WorkflowTask.created_at)).scalars().all()
        rev = db.get(DocumentRevision, inst.revision_id)
        stages = []
        for s in spec.stages:
            r = runs.get(s.key)
            stages.append({
                "key": s.key, "name": s.name, "type": s.type, "mode": s.mode, "checklist": s.checklist, "instructions": s.instructions,
                "status": r.status if r else ("PENDING" if inst.status == "ACTIVE" else "NOT_REACHED"),
                "started_at": iso(r.started_at) if r else None, "ended_at": iso(r.ended_at) if r else None, "due_at": iso(r.due_at) if r else None,
                "tasks": [{"id": str(t.id), "assignee": user_brief(db.get(User, t.assignee_id)), "acted_by": user_brief(db.get(User, t.acted_by_id)) if t.acted_by_id and t.acted_by_id != t.assignee_id else None,
                           "status": t.status, "comment": t.decision_comment, "acted_at": iso(t.acted_at), "due_at": iso(t.due_at), "sha256": t.revision_sha256} for t in tasks if t.stage_key == s.key],
            })
        out.append({"id": str(inst.id), "status": inst.status, "cycle_no": inst.cycle_no, "revision": {"id": str(rev.id), "label": rev.label}, "iteration": inst.iteration,
                    "sha256": inst.revision_sha256, "current_stage_key": inst.current_stage_key, "workflow": {"name": v.definition.name, "version_no": v.version_no},
                    "initiator": user_brief(db.get(User, inst.initiator_id)), "started_at": iso(inst.created_at), "completed_at": iso(inst.completed_at), "stages": stages})
    return out


@router.get("/{did}/history")
def document_history(did: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    _doc(ctx, did)
    evs = ctx.db.execute(select(AuditEvent).where(AuditEvent.entity_type == "document", AuditEvent.entity_id == str(did)).order_by(AuditEvent.seq.desc()).limit(300)).scalars().all()
    return [{"seq": e.seq, "at": iso(e.at), "action": e.action, "summary": e.summary, "actor": user_brief(ctx.db.get(User, e.actor_id)) if e.actor_id else None, "outcome": e.outcome, "hash": e.hash} for e in evs]


# ------------------------------------------------------------------ content
def _current(ctx: Ctx, d: Document) -> DocumentRevision:
    rev = ctx.db.get(DocumentRevision, d.current_revision_id)
    if not rev:
        raise AppError("Document has no revision.")
    return rev


@router.post("/{did}/content")
async def upload_content(did: uuid.UUID, file: UploadFile = File(...), note: str | None = Form(None), ctx: Ctx = Depends(get_ctx)):
    d = _doc(ctx, did, "doc.edit")
    rev = _current(ctx, d)
    docsvc.add_iteration(ctx.db, ctx.user, d, rev, file.filename or "upload", await file.read(), source="UPLOAD", note=note)
    ctx.db.commit()
    return revision_dict(ctx.db, rev)


class ReviseIn(BaseModel):
    change_summary: str = Field(min_length=3, max_length=2000)


@router.post("/{did}/revise")
def revise(did: uuid.UUID, body: ReviseIn, ctx: Ctx = Depends(get_ctx)):
    d = _doc(ctx, did, "doc.edit")
    rev = docsvc.revise(ctx.db, ctx.user, d, body.change_summary)
    ctx.db.commit()
    return revision_dict(ctx.db, rev)


@router.get("/{did}/revisions/{rid}/file")
def download(did: uuid.UUID, rid: uuid.UUID, inline: bool = False, iteration: int | None = None, ctx: Ctx = Depends(get_ctx)):
    d = _doc(ctx, did, "doc.view" if inline else "doc.download")
    rev = get_or_404(ctx.db, DocumentRevision, rid, "Revision")
    if rev.document_id != d.id:
        raise Forbidden("Revision does not belong to this document.")
    fo = rev.file
    if iteration is not None:
        it = ctx.db.execute(select(RevisionIteration).where(RevisionIteration.revision_id == rev.id, RevisionIteration.iteration == iteration)).scalar_one_or_none()
        fo = it.file if it else None
    if not fo:
        raise AppError("No file for this revision.", code="NO_CONTENT")
    ctx.db.add(DocumentAccessLog(document_id=d.id, revision_id=rev.id, user_id=ctx.user.id, action="VIEW" if inline else "DOWNLOAD", at=utcnow()))
    if not inline:
        ctx.audit("document.download", "document", d.id, f"Downloaded {d.number} rev {rev.label}")
    ctx.db.commit()
    name = f"{d.number}_Rev{rev.label}.{fo.extension}" if fo.extension else d.number
    return FileResponse(storage.file_path(fo), media_type=fo.mime_type, filename=name, content_disposition_type="inline" if inline else "attachment", headers={"Cache-Control": "private, no-store", "X-Content-SHA256": fo.sha256})


# ------------------------------------------------------------------ relations / sharing / comments
class RelationIn(BaseModel):
    target_id: uuid.UUID
    relation_type: str = Field(pattern=r"^(PARENT_OF|DERIVED_FROM|REFERENCES|SUPERSEDES|RELATED)$")
    note: str | None = None


@router.post("/{did}/relations")
def add_relation(did: uuid.UUID, body: RelationIn, ctx: Ctx = Depends(get_ctx)):
    d = _doc(ctx, did, "doc.edit")
    t = _doc(ctx, body.target_id)
    if t.id == d.id:
        raise AppError("A document cannot relate to itself.")
    if ctx.db.execute(select(DocumentRelation.id).where(DocumentRelation.source_id == d.id, DocumentRelation.target_id == t.id, DocumentRelation.relation_type == body.relation_type)).first():
        raise AppError("Relation already exists.")
    ctx.db.add(DocumentRelation(source_id=d.id, target_id=t.id, relation_type=body.relation_type, note=body.note, source_revision_id=d.current_revision_id, created_by_id=ctx.user.id))
    ctx.audit("document.relate", "document", d.id, f"{d.number} {body.relation_type.replace('_', ' ').lower()} {t.number}")
    ctx.db.commit()
    return {"ok": True}


class GrantIn(BaseModel):
    user_id: uuid.UUID | None = None
    org_unit_id: uuid.UUID | None = None
    permissions: list[str] = Field(default_factory=lambda: ["view"])
    valid_to: datetime | None = None
    reason: str = Field(min_length=3)


@router.post("/{did}/grants")
def share(did: uuid.UUID, body: GrantIn, ctx: Ctx = Depends(get_ctx)):
    d = _doc(ctx, did)
    if not (d.owner_id == ctx.user.id or ctx.p.has("doc.share", **doc_scope(ctx.db, d))):
        raise Forbidden("Only the owner or a user with share permission can share this document.")
    if bool(body.user_id) == bool(body.org_unit_id):
        raise AppError("Share with either a person or an organization unit.")
    bad = set(body.permissions) - {"view", "download", "comment", "edit"}
    if bad:
        raise AppError("Unsupported permission in share.")
    g = DocumentAccessGrant(document_id=d.id, user_id=body.user_id, org_unit_id=body.org_unit_id, permissions=",".join(sorted(set(body.permissions))), valid_to=body.valid_to, reason=body.reason, granted_by_id=ctx.user.id)
    ctx.db.add(g)
    target = ctx.db.get(User, body.user_id).full_name if body.user_id else ctx.db.get(OrgUnit, body.org_unit_id).name
    ctx.audit("document.share", "document", d.id, f"Shared {d.number} with {target} ({g.permissions})", {"reason": body.reason, "valid_to": iso(body.valid_to)})
    if body.user_id:
        from app.services.notify import notify

        notify(ctx.db, body.user_id, "document.shared", f"{ctx.user.full_name} shared {d.number}", d.title, link=f"/documents/{d.id}")
    ctx.db.commit()
    return {"id": str(g.id)}


@router.delete("/{did}/grants/{gid}")
def unshare(did: uuid.UUID, gid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    d = _doc(ctx, did)
    g = get_or_404(ctx.db, DocumentAccessGrant, gid, "Share")
    if not (d.owner_id == ctx.user.id or ctx.p.has("doc.share", **doc_scope(ctx.db, d))):
        raise Forbidden("Not allowed.")
    g.revoked_at = utcnow()
    ctx.audit("document.unshare", "document", d.id, f"Revoked share on {d.number}")
    ctx.db.commit()
    return {"ok": True}


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    anchor: str | None = None
    parent_id: uuid.UUID | None = None


@router.get("/{did}/comments")
def comments(did: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    d = _doc(ctx, did)
    rows = ctx.db.execute(select(DocumentComment).where(DocumentComment.document_id == d.id).order_by(DocumentComment.created_at)).scalars().all()
    revs = {r.id: r.label for r in ctx.db.execute(select(DocumentRevision).where(DocumentRevision.document_id == d.id)).scalars()}
    return [{"id": str(c.id), "parent_id": str(c.parent_id) if c.parent_id else None, "body": c.body, "anchor": c.anchor, "resolved": c.resolved, "revision": revs.get(c.revision_id), "author": user_brief(ctx.db.get(User, c.author_id)), "created_at": iso(c.created_at)} for c in rows]


@router.post("/{did}/comments")
def add_comment(did: uuid.UUID, body: CommentIn, ctx: Ctx = Depends(get_ctx)):
    d = _doc(ctx, did)
    c = DocumentComment(document_id=d.id, revision_id=d.current_revision_id, author_id=ctx.user.id, body=body.body, anchor=body.anchor, parent_id=body.parent_id)
    ctx.db.add(c)
    if d.owner_id != ctx.user.id:
        from app.services.notify import notify

        notify(ctx.db, d.owner_id, "document.comment", f"New comment on {d.number}", body.body[:200], link=f"/documents/{d.id}?tab=discussion")
    ctx.db.commit()
    return {"id": str(c.id)}


@router.post("/{did}/comments/{cid}/resolve")
def resolve_comment(did: uuid.UUID, cid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    d = _doc(ctx, did)
    c = get_or_404(ctx.db, DocumentComment, cid, "Comment")
    if c.document_id != d.id:
        raise Forbidden("Mismatch")
    c.resolved = not c.resolved
    c.resolved_by_id = ctx.user.id
    ctx.db.commit()
    return {"resolved": c.resolved}


# ------------------------------------------------------------------ workflow & release
@router.get("/{did}/workflow-plan")
def workflow_plan(did: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    d = _doc(ctx, did)
    return wf.plan_for_document(ctx.db, d)


class SubmitIn(BaseModel):
    picks: dict[str, list[str]] = Field(default_factory=dict)
    comment: str | None = None
    version: int | None = None  # optimistic concurrency


@router.post("/{did}/submit")
def submit(did: uuid.UUID, body: SubmitIn, ctx: Ctx = Depends(get_ctx)):
    d = _doc(ctx, did, "doc.edit")
    if body.version is not None and body.version != d.version:
        raise AppError("This document was changed by someone else. Refresh and try again.", code="STALE", status_code=409)
    inst = wf.start(ctx.db, ctx.user, d, _current(ctx, d), body.picks, body.comment)
    ctx.db.commit()
    return {"instance_id": str(inst.id)}


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


@router.post("/{did}/withdraw-submission")
def withdraw_submission(did: uuid.UUID, body: ReasonIn, ctx: Ctx = Depends(get_ctx)):
    d = _doc(ctx, did)
    inst = ctx.db.execute(select(WorkflowInstance).where(WorkflowInstance.document_id == d.id, WorkflowInstance.status == "ACTIVE")).scalars().first()
    if not inst:
        raise AppError("No active submission.")
    wf.withdraw(ctx.db, ctx.user, inst.id, body.reason)
    ctx.db.commit()
    return {"ok": True}


@router.get("/{did}/release-checks")
def release_checks(did: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    d = _doc(ctx, did)
    return relsvc.release_checks(ctx.db, d, _current(ctx, d))


class ReleaseIn(BaseModel):
    note: str | None = None


@router.post("/{did}/release")
def release(did: uuid.UUID, body: ReleaseIn, ctx: Ctx = Depends(get_ctx)):
    d = _doc(ctx, did)
    ctx.p.require("doc.release", **doc_scope(ctx.db, d))
    rev = _current(ctx, d)
    # SoD: the author cannot be the release authority for their own revision.
    if rev.created_by_id == ctx.user.id or d.owner_id == ctx.user.id:
        raise Forbidden("Separation of duties: the author/owner cannot release their own document.")
    entry = relsvc.release_revision(ctx.db, ctx.user, d, rev, body.note)
    ctx.db.commit()
    return {"release_no": entry.release_no}


@router.get("/{did}/signatures/{sid}/verify")
def verify_signature(did: uuid.UUID, sid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    d = _doc(ctx, did)
    s = get_or_404(ctx.db, SignatureRecord, sid, "Signature")
    rev = ctx.db.get(DocumentRevision, s.revision_id)
    if rev.document_id != d.id:
        raise Forbidden("Mismatch")
    content_ok = wf.file_hash_ok(rev) and rev.sha256 == s.signed_sha256
    res = get_provider().validate(s.signature_b64, s.certificate_pem, s.signed_sha256)
    ctx.audit("signature.verify", "document", d.id, f"Signature verification for {d.number} rev {rev.label}: {'valid' if res.valid and content_ok else 'INVALID'}")
    ctx.db.commit()
    return {"valid": res.valid and content_ok, "reason": res.reason if content_ok else "Document content no longer matches the signed hash.", "chain_ok": res.chain_ok, "content_ok": content_ok, "provider": s.provider, "is_cryptographic": s.is_cryptographic}
