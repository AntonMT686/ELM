"""Requirement management (architecture §10): register, review, links, traceability, baselines, impact, RTM, CSV exchange.
Scope is enforced on every endpoint; every mutation is audited in the same transaction."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.core.db import utcnow
from app.core.deps import Ctx, get_ctx, get_or_404
from app.core.errors import AppError, Conflict, Forbidden
from app.models import (
    Document,
    FileObject,
    DocumentRevision,
    EngineeringItem,
    OrgUnit,
    Project,
    Requirement,
    RequirementBaseline,
    RequirementBaselineItem,
    RequirementDocument,
    RequirementEvent,
    RequirementLink,
    RequirementReview,
    RequirementRevision,
    RequirementSource,
    RequirementWorkItem,
    SystemSetting,
    TaskChecklistItem,
    User,
    WorkItem,
    WorkItemEvent,
)
from app.services import req_tagging as tagging
from app.services import requirements as svc
from app.services.authz import can_on_document, can_view_document
from app.services.notify import notify
from app.services.numbering import next_seq
from app.services.planning import can_manage_task, can_view_task, require_view_project
from app.services.serial import iso, org_brief, user_brief
from app.services.task_lifecycle import get_lifecycle as task_lifecycle
from app.services.task_lifecycle import initial_state

router = APIRouter(tags=["requirements"])

PRIORITIES = r"^(LOW|MEDIUM|HIGH|CRITICAL)$"
MAX_CSV_BYTES = 5_000_000
CSV_COLUMNS = ["external_id", "title", "description", "acceptance_criteria", "type", "priority"]


def _safe(v):
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def _project(ctx: Ctx, pid: uuid.UUID) -> Project:
    p = get_or_404(ctx.db, Project, pid, "Project")
    require_view_project(ctx.db, ctx.p, pid)
    return p


def _req(ctx: Ctx, rid: uuid.UUID) -> Requirement:
    r = get_or_404(ctx.db, Requirement, rid, "Requirement")
    if not svc.can_view(ctx.db, ctx.p, r):
        raise Forbidden("You do not have access to this requirement.")
    return r


def _require_edit(ctx: Ctx, r: Requirement) -> None:
    if not svc.can_edit(ctx.db, ctx.p, r):
        raise Forbidden("Only the owner or someone with requirement edit permission in this scope can change this.", details={"permission": "req.edit"})


def _brief(r: Requirement, users: dict, sources: dict) -> dict:
    src = sources.get(r.source_id)
    return {"id": str(r.id), "key": r.key, "title": r.title, "status": r.status, "req_type": r.req_type, "priority": r.priority, "revision": r.revision, "parent_id": str(r.parent_id) if r.parent_id else None,
            "owner": user_brief(users.get(r.owner_id)), "source": {"id": str(src.id), "name": src.name} if src else None, "external_id": r.external_id, "updated_at": iso(r.updated_at), "version": r.version}


# ------------------------------------------------------------------ configuration
class LifecycleIn(BaseModel):
    states: list[dict]
    transitions: list[dict]
    mandatory_fields: list[str] | None = None


@router.get("/requirement-lifecycle")
def get_lifecycle(project_id: uuid.UUID | None = None, ctx: Ctx = Depends(get_ctx)):
    if project_id:
        require_view_project(ctx.db, ctx.p, project_id)
    return {**svc.get_lifecycle(ctx.db, project_id), "mandatory_fields": svc.mandatory_fields(ctx.db), "default": svc.DEFAULT_LIFECYCLE}


@router.put("/requirement-lifecycle")
def set_lifecycle(body: LifecycleIn, project_id: uuid.UUID | None = None, ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("workflow.configure")
    new = {"states": body.states, "transitions": body.transitions}
    errors = svc.validate_requirement_lifecycle(new)
    q = select(Requirement.status).distinct()
    if project_id:
        q = q.where(Requirement.project_id == project_id)
    for code in sorted(set(ctx.db.execute(q).scalars()) - {s.get("code") for s in body.states}):
        errors.append(f"State {code} cannot be removed because requirements are using it.")
    if errors:
        raise AppError("The requirement lifecycle is not valid.", code="LIFECYCLE_INVALID", details={"errors": errors})

    def put(key: str, value, description: str) -> None:
        row = ctx.db.get(SystemSetting, key)
        if row:
            row.value = json.dumps(value)
        else:
            ctx.db.add(SystemSetting(key=key, value=json.dumps(value), description=description))

    put(f"requirement.lifecycle.{project_id}" if project_id else "requirement.lifecycle", new, "Requirement lifecycle")
    if body.mandatory_fields is not None:
        unknown = set(body.mandatory_fields) - set(svc.DEFAULT_MANDATORY)
        if unknown:
            raise AppError(f"Unknown field: {', '.join(sorted(unknown))}.")
        put("requirement.mandatory_fields", body.mandatory_fields, "Fields required before a requirement can be submitted for review")
    ctx.audit("requirement.lifecycle.update", "system_setting", None, "Requirement lifecycle updated", {"project_id": str(project_id) if project_id else None, "mandatory": body.mandatory_fields})
    ctx.db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ sources
class SourceIn(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    source_system: str = Field(default="ELM", max_length=40)
    external_ref: str | None = Field(default=None, max_length=300)
    external_version: str | None = Field(default=None, max_length=80)
    key_prefix: str = Field(pattern=r"^[A-Za-z0-9_.-]{2,40}$")
    tag_format: str = Field(default="{PREFIX}-{SEQ:4}", max_length=120)
    document_id: uuid.UUID | None = None
    org_unit_id: uuid.UUID | None = None


def _source_dict(ctx: Ctx, s: RequirementSource) -> dict:
    d = ctx.db.get(Document, s.document_id) if s.document_id else None
    n = ctx.db.execute(select(func.count(Requirement.id)).where(Requirement.source_id == s.id)).scalar()
    return {"id": str(s.id), "name": s.name, "source_system": s.source_system, "external_ref": s.external_ref, "external_version": s.external_version, "key_prefix": s.key_prefix, "tag_format": s.tag_format or tagging.DEFAULT_FORMAT,
            "document": {"id": str(d.id), "number": d.number} if d else None, "org": org_brief(ctx.db.get(OrgUnit, s.org_unit_id)) if s.org_unit_id else None, "file_sha256": s.file_sha256, "last_synced_at": iso(s.last_synced_at), "requirements": n, "created_at": iso(s.created_at)}


@router.get("/projects/{pid}/requirement-sources")
def list_sources(pid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    _project(ctx, pid)
    rows = ctx.db.execute(select(RequirementSource).where(RequirementSource.project_id == pid).order_by(RequirementSource.name)).scalars().all()
    return [_source_dict(ctx, s) for s in rows]


@router.post("/projects/{pid}/requirement-sources")
def create_source(pid: uuid.UUID, body: SourceIn, ctx: Ctx = Depends(get_ctx)):
    p = _project(ctx, pid)
    ctx.p.require("req.edit", project_id=pid)
    if ctx.db.execute(select(RequirementSource.id).where(RequirementSource.project_id == pid, RequirementSource.name == body.name)).first():
        raise Conflict("A source with this name already exists in the project.")
    if body.document_id:
        doc = get_or_404(ctx.db, Document, body.document_id, "Document")
        if not can_view_document(ctx.db, ctx.p, doc):
            raise Forbidden("You do not have access to that document.")
    tagging.validate_format(body.tag_format)
    s = RequirementSource(project_id=pid, created_by_id=ctx.user.id, **body.model_dump())
    ctx.db.add(s)
    ctx.db.flush()
    ctx.audit("requirement.source.create", "requirement_source", s.id, f"Requirement source {s.name} added to {p.code}", {"tag_format": s.tag_format})
    ctx.db.commit()
    return _source_dict(ctx, s)


class SourcePatch(BaseModel):
    tag_format: str | None = Field(default=None, max_length=120)
    document_id: uuid.UUID | None = None
    external_version: str | None = Field(default=None, max_length=80)


@router.patch("/requirement-sources/{sid}")
def update_source(sid: uuid.UUID, body: SourcePatch, ctx: Ctx = Depends(get_ctx)):
    s = get_or_404(ctx.db, RequirementSource, sid, "Source")
    _project(ctx, s.project_id)
    ctx.p.require("req.edit", project_id=s.project_id)
    changes = body.model_dump(exclude_unset=True)
    if "tag_format" in changes and changes["tag_format"]:
        tagging.validate_format(changes["tag_format"])
    if changes.get("document_id"):
        doc = get_or_404(ctx.db, Document, changes["document_id"], "Document")
        if not can_view_document(ctx.db, ctx.p, doc):
            raise Forbidden("You do not have access to that document.")
    for k, v in changes.items():
        setattr(s, k, v)
    ctx.audit("requirement.source.update", "requirement_source", s.id, f"Requirement source {s.name} updated", {k: str(v) for k, v in changes.items()})
    ctx.db.commit()
    return _source_dict(ctx, s)


# ------------------------------------------------------------------ requirements tagged in documents
class ScanIn(BaseModel):
    document_id: uuid.UUID | None = None
    detect: str = Field(default="both", pattern=r"^(tags|shall|both)$")


def _scan(ctx: Ctx, s: RequirementSource, document_id, detect: str):
    doc_id = document_id or s.document_id
    if not doc_id:
        raise AppError("Choose the document to scan, or set it on the source.")
    doc = get_or_404(ctx.db, Document, doc_id, "Document")
    if not can_view_document(ctx.db, ctx.p, doc):
        raise Forbidden("You do not have access to that document.")
    if doc.project_id and doc.project_id != s.project_id:
        raise AppError("The document belongs to another project.")
    rev = ctx.db.get(DocumentRevision, doc.current_revision_id)
    if not rev or not rev.file_id:
        raise AppError("The document has no content yet.")
    from app.services import storage

    data = storage.read_bytes(ctx.db.get(FileObject, rev.file_id), verify=True)
    rx = tagging.tag_regex(s)
    existing = {r.key: r for r in ctx.db.execute(select(Requirement).where(Requirement.project_id == s.project_id)).scalars()}
    out = []
    for para in tagging.paragraphs(data):
        if para["heading"] or len(para["text"]) < 8:
            continue
        m = rx.search(para["text"])
        if not m and not (detect in ("shall", "both") and tagging.SHALL.search(para["text"])):
            continue
        if m and detect == "shall":
            continue
        tag = m.group(1) if m else None
        body = tagging.strip_tag(para["text"], rx)
        cur = existing.get(tag) if tag else None
        state = "new"
        if cur:
            same = svc.hash_of(cur) == svc.content_hash(tagging.title_of(body), body, cur.acceptance_criteria, cur.req_type, cur.priority)
            state = "unchanged" if same else ("locked" if cur.status in svc.RELEASED_STATES or cur.status in svc.LOCKED_WHILE else "changed")
        out.append({"paragraph": para["index"], "section": para["section"], "text": body, "tag": tag, "state": state, "requirement": {"id": str(cur.id), "key": cur.key, "status": cur.status} if cur else None})
    return doc, rev, data, out


@router.post("/requirement-sources/{sid}/document-scan")
def scan_document(sid: uuid.UUID, body: ScanIn, ctx: Ctx = Depends(get_ctx)):
    """Preview: which paragraphs of the document are (or look like) requirements, and what importing would do."""
    s = get_or_404(ctx.db, RequirementSource, sid, "Source")
    _project(ctx, s.project_id)
    doc, rev, _, items = _scan(ctx, s, body.document_id, body.detect)
    return {"document": {"id": str(doc.id), "number": doc.number, "title": doc.title, "revision": rev.label, "iteration": rev.iteration, "status": rev.status},
            "tag_format": s.tag_format or tagging.DEFAULT_FORMAT, "example": tagging.render(s.tag_format or tagging.DEFAULT_FORMAT, tagging._context(ctx.db, s, None), 1),
            "can_write_tags": can_on_document(ctx.db, ctx.p, doc, "doc.edit") and not rev.locked and rev.status in ("DRAFT", "CHANGES_REQUESTED", "REJECTED"),
            "items": items, "counts": {k: sum(1 for i in items if i["state"] == k) for k in ("new", "changed", "unchanged", "locked")}}


class DocImportIn(ScanIn):
    paragraphs: list[int] = Field(min_length=1)
    item_id: uuid.UUID | None = None
    req_type: str = Field(default="FUNCTIONAL", max_length=30)
    priority: str = Field(default="MEDIUM", pattern=PRIORITIES)
    write_tags: bool = True
    reason: str | None = Field(default=None, max_length=1000)


@router.post("/requirement-sources/{sid}/document-import")
def import_from_document(sid: uuid.UUID, body: DocImportIn, ctx: Ctx = Depends(get_ctx)):
    """Create or update the chosen requirements from the document, link them to it with their section and, if asked,
    write the newly assigned tags back into the document as a new iteration."""
    s = get_or_404(ctx.db, RequirementSource, sid, "Source")
    p = _project(ctx, s.project_id)
    if not ctx.p.has("req.edit", project_id=s.project_id):
        raise Forbidden("Importing requirements needs requirement edit permission in this project.", details={"permission": "req.edit"})
    if body.item_id and get_or_404(ctx.db, EngineeringItem, body.item_id, "Item").project_id != s.project_id:
        raise AppError("The breakdown item belongs to another project.")
    doc, rev, data, items = _scan(ctx, s, body.document_id, body.detect)
    chosen = [i for i in items if i["paragraph"] in set(body.paragraphs)]
    created, updated, unchanged, skipped, new_tags = [], [], [], [], {}
    for it in chosen:
        title = tagging.title_of(it["text"])
        if it["state"] == "locked":
            skipped.append({"tag": it["tag"], "reason": f"{it['tag']} is {it['requirement']['status'].lower().replace('_', ' ')}; change it in ELM with a reason"})
            continue
        if it["requirement"]:
            r = ctx.db.get(Requirement, uuid.UUID(it["requirement"]["id"]))
            if it["state"] == "changed":
                svc.apply_content(ctx.db, r, {"title": title, "description": it["text"]}, actor=ctx.user.id, reason=body.reason or f"Updated from {doc.number}")
                svc.add_event(ctx.db, r, "IMPORTED", ctx.user.id, comment=f"Updated from {doc.number} rev {rev.label}, {it['section'] or 'no section'}")
                updated.append(r.key)
            else:
                unchanged.append(r.key)
        else:
            if it["tag"]:
                key = it["tag"]
                tagging.note_used(ctx.db, s, key, body.item_id)
            else:
                key = tagging.next_tag(ctx.db, s, body.item_id)
                new_tags[it["paragraph"]] = key
            r = Requirement(project_id=s.project_id, source_id=s.id, key=key, title=title, description=it["text"], req_type=body.req_type, priority=body.priority, status="DRAFT",
                            owner_id=ctx.user.id, item_id=body.item_id, content_sha256=svc.content_hash(title, it["text"], None, body.req_type, body.priority))
            ctx.db.add(r)
            ctx.db.flush()
            svc.write_revision(ctx.db, r, ctx.user.id, f"Tagged in {doc.number}")
            svc.add_event(ctx.db, r, "IMPORTED", ctx.user.id, to="DRAFT", comment=f"From {doc.number} rev {rev.label}, {it['section'] or 'no section'}")
            created.append(r.key)
        link = ctx.db.execute(select(RequirementDocument).where(RequirementDocument.requirement_id == r.id, RequirementDocument.document_id == doc.id)).scalar_one_or_none()
        if link is None:
            link = RequirementDocument(requirement_id=r.id, document_id=doc.id, link_type="specified_in", created_by_id=ctx.user.id)
            ctx.db.add(link)
        link.section, link.paragraph = it["section"], it["paragraph"]
    tags_written = None
    if new_tags and body.write_tags:
        if not (can_on_document(ctx.db, ctx.p, doc, "doc.edit") and not rev.locked and rev.status in ("DRAFT", "CHANGES_REQUESTED", "REJECTED")):
            tags_written = {"written": False, "reason": f"{doc.number} rev {rev.label} is {rev.status.lower().replace('_', ' ')} or you cannot edit it; put the tags in by hand", "tags": new_tags}
        else:
            from app.services import documents as docsvc

            fo = ctx.db.get(FileObject, rev.file_id)
            it_row = docsvc.add_iteration(ctx.db, ctx.user, doc, rev, fo.original_name, tagging.write_tags(data, new_tags), source="TAGGING", note=f"{len(new_tags)} requirement tag(s) added from {s.name}")
            tags_written = {"written": True, "iteration": it_row.iteration, "count": len(new_tags)}
    src_sha = rev.sha256
    s.last_synced_at, s.file_sha256 = utcnow(), src_sha
    if not s.document_id:
        s.document_id = doc.id
    ctx.audit("requirement.document_import", "requirement_source", s.id, f"{p.code}: {len(created)} new, {len(updated)} updated requirement(s) from {doc.number}",
              {"created": created, "updated": updated, "skipped": skipped, "tags_written": tags_written})
    ctx.db.commit()
    return {"created": created, "updated": updated, "unchanged": unchanged, "skipped": skipped, "tags_written": tags_written}


# ------------------------------------------------------------------ list / read
@router.get("/projects/{pid}/requirements")
def list_requirements(pid: uuid.UUID, q: str | None = None, status: str | None = None, req_type: str | None = None, priority: str | None = None, source_id: uuid.UUID | None = None, ctx: Ctx = Depends(get_ctx)):
    _project(ctx, pid)
    stmt = select(Requirement).where(Requirement.project_id == pid)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Requirement.key).like(like), func.lower(Requirement.title).like(like), func.lower(func.coalesce(Requirement.external_id, "")).like(like)))
    if status:
        stmt = stmt.where(Requirement.status.in_(status.split(",")))
    if req_type:
        stmt = stmt.where(Requirement.req_type == req_type)
    if priority:
        stmt = stmt.where(Requirement.priority == priority)
    if source_id:
        stmt = stmt.where(Requirement.source_id == source_id)
    rows = sorted(ctx.db.execute(stmt.order_by(Requirement.key).limit(2000)).scalars().all(), key=lambda r: (r.sort_order, svc.natural_key(r.key)))
    users = {u.id: u for u in ctx.db.execute(select(User).where(User.id.in_({r.owner_id for r in rows} | {uuid.uuid4()}))).scalars()}
    sources = {s.id: s for s in ctx.db.execute(select(RequirementSource).where(RequirementSource.project_id == pid)).scalars()}
    project_scope = ctx.p.has("req.edit", project_id=pid)
    return {"can_edit": project_scope, "can_baseline": ctx.p.has("req.baseline", project_id=pid), "lifecycle": svc.get_lifecycle(ctx.db, pid), "items": [_brief(r, users, sources) for r in rows]}


@router.get("/projects/{pid}/rtm")
def rtm(pid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    _project(ctx, pid)
    return svc.rtm(ctx.db, pid)


@router.get("/projects/{pid}/rtm.csv")
def rtm_csv(pid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    p = _project(ctx, pid)
    data = svc.rtm(ctx.db, pid)
    buf = io.StringIO()
    out = csv.writer(buf)
    out.writerow(["key", "title", "status", "revision", "priority", "type", "tasks", "documents", "traces_to", "traced_by", "baselines", "designs", "merge_requests", "tests", "defects"])
    for r in data["rows"]:
        out.writerow([_safe(x) for x in [r["key"], r["title"], r["status"], r["revision"], r["priority"], r["req_type"], " ".join(t["key"] for t in r["tasks"]), " ".join(d["number"] for d in r["documents"]),
                                          " ".join(f"{t['type']}:{t['key']}" for t in r["traces_to"]), " ".join(f"{t['type']}:{t['key']}" for t in r["traced_by"]), " ".join(str(s) for s in r["baselines"]),
                                          " ".join(d["key"] for d in r["designs"]), " ".join(f"{c['ref']}:{c['state']}" for c in r["code"]), " ".join(f"{t['key']}:{t['last_result'] or 'not run'}" for t in r["tests"]),
                                          " ".join(f"{d['key']}:{d['status']}" for d in r["defects"])]])
    ctx.audit("requirement.rtm.export", "project", p.id, f"RTM of {p.code} exported", {"rows": len(data["rows"])})
    ctx.db.commit()
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="rtm-{p.code}.csv"'})


def _detail(ctx: Ctx, r: Requirement) -> dict:
    db = ctx.db
    users_seen: dict = {}

    def who(uid):
        if not uid:
            return None
        if uid not in users_seen:
            users_seen[uid] = db.get(User, uid)
        return user_brief(users_seen[uid])

    src = db.get(RequirementSource, r.source_id) if r.source_id else None
    parent = db.get(Requirement, r.parent_id) if r.parent_id else None
    project = db.get(Project, r.project_id)
    kids = db.execute(select(Requirement).where(Requirement.parent_id == r.id).order_by(Requirement.key)).scalars().all()
    out_links = db.execute(select(RequirementLink, Requirement).join(Requirement, Requirement.id == RequirementLink.to_id).where(RequirementLink.from_id == r.id)).all()
    in_links = db.execute(select(RequirementLink, Requirement).join(Requirement, Requirement.id == RequirementLink.from_id).where(RequirementLink.to_id == r.id)).all()
    tasks = db.execute(select(RequirementWorkItem, WorkItem).join(WorkItem, WorkItem.id == RequirementWorkItem.work_item_id).where(RequirementWorkItem.requirement_id == r.id)).all()
    docs = db.execute(select(RequirementDocument, Document).join(Document, Document.id == RequirementDocument.document_id).where(RequirementDocument.requirement_id == r.id)).all()
    reviews = db.execute(select(RequirementReview).where(RequirementReview.requirement_id == r.id).order_by(RequirementReview.cycle.desc(), RequirementReview.role.desc(), RequirementReview.created_at)).scalars().all()
    revisions = db.execute(select(RequirementRevision).where(RequirementRevision.requirement_id == r.id).order_by(RequirementRevision.revision.desc())).scalars().all()
    events = db.execute(select(RequirementEvent).where(RequirementEvent.requirement_id == r.id).order_by(RequirementEvent.at.desc()).limit(200)).scalars().all()
    baselines = db.execute(select(RequirementBaseline, RequirementBaselineItem.revision).join(RequirementBaselineItem, RequirementBaselineItem.baseline_id == RequirementBaseline.id).where(RequirementBaselineItem.requirement_id == r.id).order_by(RequirementBaseline.seq.desc())).all()
    lc = svc.get_lifecycle(db, r.project_id)
    manager = svc.has_scope(db, ctx.p, "req.edit", r)
    mine = {"owner"} if r.owner_id == ctx.user.id else set()
    if manager:
        mine.add("manager")
    labels = {s["code"]: s["label"] for s in lc["states"]}
    pending = [x for x in reviews if x.status == "PENDING"]
    my_review = next((x for x in pending if x.reviewer_id == ctx.user.id and x.role == "REVIEWER"), None) or next((x for x in pending if x.reviewer_id == ctx.user.id), None)
    waiting_for_reviewers = bool(my_review and my_review.role == "APPROVER" and any(x.role == "REVIEWER" for x in pending))
    visible = lambda x: svc.can_view(db, ctx.p, x)  # noqa: E731
    return {
        "id": str(r.id), "key": r.key, "title": r.title, "description": r.description, "acceptance_criteria": r.acceptance_criteria, "req_type": r.req_type, "priority": r.priority, "status": r.status, "status_label": labels.get(r.status, r.status),
        "revision": r.revision, "content_sha256": r.content_sha256, "version": r.version, "external_id": r.external_id, "external_version": r.external_version,
        "project": {"id": str(project.id), "code": project.code, "name": project.name}, "owner": who(r.owner_id), "org_unit_id": str(r.org_unit_id) if r.org_unit_id else None, "item_id": str(r.item_id) if r.item_id else None,
        "source": {"id": str(src.id), "name": src.name, "source_system": src.source_system, "external_ref": src.external_ref, "external_version": src.external_version} if src else None,
        "parent": {"id": str(parent.id), "key": parent.key, "title": parent.title} if parent else None,
        "children": [{"id": str(k.id), "key": k.key, "title": k.title, "status": k.status} for k in kids],
        "links_out": [{"id": str(x.id), "type": x.link_type, "req": {"id": str(o.id), "key": o.key, "title": o.title, "status": o.status}} for x, o in out_links if visible(o)],
        "links_in": [{"id": str(x.id), "type": x.link_type, "req": {"id": str(o.id), "key": o.key, "title": o.title, "status": o.status}} for x, o in in_links if visible(o)],
        "tasks": [{"link_id": str(x.id), "type": x.link_type, "id": str(t.id), "key": t.key, "title": t.title, "status": t.status, "progress": t.progress} for x, t in tasks if can_view_task(db, ctx.p, t)],
        "documents": [{"link_id": str(x.id), "type": x.link_type, "section": x.section, "paragraph": x.paragraph, "id": str(d.id), "number": d.number, "title": d.title, "status": d.status} for x, d in docs if can_view_document(db, ctx.p, d)],
        "reviews": [{"id": str(x.id), "cycle": x.cycle, "revision": x.revision, "role": x.role, "status": x.status, "comment": x.comment, "decided_at": iso(x.decided_at), "reviewer": who(x.reviewer_id), "content_sha256": x.content_sha256} for x in reviews],
        "revisions": [{"revision": x.revision, "title": x.title, "description": x.description, "acceptance_criteria": x.acceptance_criteria, "content_sha256": x.content_sha256, "change_reason": x.change_reason, "created_at": iso(x.created_at), "created_by": who(x.created_by_id)} for x in revisions],
        "history": [{"id": str(e.id), "kind": e.kind, "from": e.from_value, "to": e.to_value, "comment": e.comment, "at": iso(e.at), "actor": who(e.actor_id)} for e in events],
        "baselines": [{"id": str(b.id), "seq": b.seq, "label": b.label, "revision": rev} for b, rev in baselines],
        "can_edit": svc.can_edit(db, ctx.p, r),
        "transitions": [{"to": t["to"], "label": t.get("label") or t["to"], "reason_required": bool(t.get("reason"))} for t in lc["transitions"] if t["from"] == r.status and mine & set(t["actors"])],
        "submit_blockers": svc.submit_blockers(db, r) if r.status == "UNDER_ANALYSIS" else [],
        "can_decide": bool(my_review) and not waiting_for_reviewers, "my_review_role": my_review.role if my_review else None, "waiting_for_reviewers": waiting_for_reviewers,
    }


@router.get("/requirements/{rid}")
def get_requirement(rid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    return _detail(ctx, _req(ctx, rid))


@router.get("/requirements/{rid}/impact")
def requirement_impact(rid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    return svc.impact(ctx.db, _req(ctx, rid), ctx.p)


# ------------------------------------------------------------------ create / update
class RequirementIn(BaseModel):
    title: str = Field(min_length=3, max_length=500)
    description: str | None = None
    acceptance_criteria: str | None = None
    req_type: str = Field(default="FUNCTIONAL", pattern=r"^[A-Za-z0-9_ -]{2,40}$")
    priority: str = Field(default="MEDIUM", pattern=PRIORITIES)
    source_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    org_unit_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    change_reason: str | None = Field(default=None, max_length=4000)


def _validate_links(ctx: Ctx, project_id: uuid.UUID, body: RequirementIn, rid: uuid.UUID | None = None) -> None:
    db = ctx.db
    if body.source_id and get_or_404(db, RequirementSource, body.source_id, "Source").project_id != project_id:
        raise AppError("The source belongs to a different project.")
    if body.item_id and get_or_404(db, EngineeringItem, body.item_id, "Item").project_id != project_id:
        raise AppError("The engineering item belongs to a different project.")
    if body.owner_id:
        u = get_or_404(db, User, body.owner_id, "Owner")
        if not u.is_active:
            raise AppError("The owner's account is not active.")
    if body.parent_id:
        parent = get_or_404(db, Requirement, body.parent_id, "Parent requirement")
        if parent.project_id != project_id:
            raise AppError("A parent requirement must be in the same project.")
        cur, seen = parent, set()
        while cur is not None and cur.id not in seen:
            if cur.id == rid:
                raise AppError("A requirement cannot be placed under itself or one of its children.", code="CYCLE")
            seen.add(cur.id)
            cur = db.get(Requirement, cur.parent_id) if cur.parent_id else None


@router.post("/projects/{pid}/requirements")
def create_requirement(pid: uuid.UUID, body: RequirementIn, ctx: Ctx = Depends(get_ctx)):
    p = _project(ctx, pid)
    probe = Requirement(project_id=pid, org_unit_id=body.org_unit_id, item_id=body.item_id)
    if not svc.has_scope(ctx.db, ctx.p, "req.edit", probe):
        raise Forbidden("You do not have requirement edit permission in this scope.", details={"permission": "req.edit"})
    _validate_links(ctx, pid, body)
    src = ctx.db.get(RequirementSource, body.source_id) if body.source_id else None
    values = body.model_dump(exclude={"change_reason"})
    values["owner_id"] = body.owner_id or ctx.user.id
    key = tagging.next_tag(ctx.db, src, body.item_id) if src else svc.next_key(ctx.db, f"{p.code}-REQ")
    r = Requirement(project_id=pid, key=key, status="DRAFT", content_sha256=svc.content_hash(body.title, body.description, body.acceptance_criteria, body.req_type, body.priority), **values)
    ctx.db.add(r)
    ctx.db.flush()
    svc.write_revision(ctx.db, r, ctx.user.id, "Created")
    svc.add_event(ctx.db, r, "CREATED", ctx.user.id, to="DRAFT")
    ctx.audit("requirement.create", "requirement", r.id, f"{r.key} created: {r.title[:150]}", {"sha256": r.content_sha256})
    ctx.db.commit()
    return _detail(ctx, r)


@router.put("/requirements/{rid}")
def update_requirement(rid: uuid.UUID, body: RequirementIn, version: int | None = None, ctx: Ctx = Depends(get_ctx)):
    r = _req(ctx, rid)
    _require_edit(ctx, r)
    if version is not None and version != r.version:
        raise Conflict("This requirement was updated by someone else. Refresh and try again.")
    _validate_links(ctx, r.project_id, body, r.id)
    old_rev, old_status = r.revision, r.status
    reopened = svc.apply_content(ctx.db, r, body.model_dump(exclude={"change_reason"}), actor=ctx.user.id, reason=body.change_reason)
    if reopened:
        # A change that voids approval tells everyone downstream, but alters nothing they own (architecture §19.3).
        reach = svc.impact(ctx.db, r, ctx.p)
        for t in reach["tasks"]:
            w = ctx.db.get(WorkItem, uuid.UUID(t["id"]))
            if w and w.assignee_id and w.assignee_id != ctx.user.id:
                notify(ctx.db, w.assignee_id, "requirement.changed", f"{r.key} changed; check {w.key}", body.change_reason, link=f"/requirements/{r.project_id}?open={r.id}", severity="warning")
        for x in reach["requirements"]:
            if x["owner_id"] and x["owner_id"] != str(ctx.user.id):
                notify(ctx.db, uuid.UUID(x["owner_id"]), "requirement.changed", f"{r.key} changed; check {x['key']}", body.change_reason, link=f"/requirements/{r.project_id}?open={x['id']}", severity="warning")
    ctx.audit("requirement.update", "requirement", r.id, f"{r.key} updated" + (f" (revision {old_rev} → {r.revision}, was {old_status})" if reopened else ""), {"reason": body.change_reason, "sha256": r.content_sha256})
    ctx.db.commit()
    return _detail(ctx, r)


class TransitionIn(BaseModel):
    to: str = Field(min_length=1, max_length=30)
    comment: str | None = Field(default=None, max_length=4000)
    reviewers: list[uuid.UUID] = Field(default_factory=list)
    approvers: list[uuid.UUID] = Field(default_factory=list)


@router.post("/requirements/{rid}/transition")
def transition(rid: uuid.UUID, body: TransitionIn, version: int | None = None, ctx: Ctx = Depends(get_ctx)):
    r = _req(ctx, rid)
    if version is not None and version != r.version:
        raise Conflict("This requirement was updated by someone else. Refresh and try again.")
    old = svc.transition(ctx.db, r, body.to, actor=ctx.user.id, is_manager=svc.has_scope(ctx.db, ctx.p, "req.edit", r), comment=body.comment, reviewers=body.reviewers, approvers=body.approvers)
    ctx.audit("requirement.transition", "requirement", r.id, f"{r.key} {old} → {r.status}", {"reason": body.comment, "revision": r.revision, "sha256": r.content_sha256})
    ctx.db.commit()
    return _detail(ctx, r)


class DecisionIn(BaseModel):
    decision: str = Field(pattern=r"^(APPROVED|REJECTED)$")
    comment: str | None = Field(default=None, max_length=4000)


@router.post("/requirements/{rid}/decision")
def decision(rid: uuid.UUID, body: DecisionIn, ctx: Ctx = Depends(get_ctx)):
    r = _req(ctx, rid)
    new_status = svc.decide(ctx.db, r, user_id=ctx.user.id, decision=body.decision, comment=body.comment)
    ctx.audit("requirement.decision", "requirement", r.id, f"{r.key} {body.decision} by {ctx.user.username} (now {new_status})", {"revision": r.revision, "sha256": r.content_sha256, "comment": body.comment})
    ctx.db.commit()
    return _detail(ctx, r)


# ------------------------------------------------------------------ links
class LinkIn(BaseModel):
    to_id: uuid.UUID
    link_type: str


@router.post("/requirements/{rid}/links")
def add_link(rid: uuid.UUID, body: LinkIn, ctx: Ctx = Depends(get_ctx)):
    r = _req(ctx, rid)
    _require_edit(ctx, r)
    if body.link_type not in svc.LINK_TYPES:
        raise AppError(f"Link type must be one of: {', '.join(svc.LINK_TYPES)}.")
    other = _req(ctx, body.to_id)
    if other.id == r.id:
        raise AppError("A requirement cannot link to itself.", code="CYCLE")
    if ctx.db.execute(select(RequirementLink.id).where(RequirementLink.from_id == r.id, RequirementLink.to_id == other.id, RequirementLink.link_type == body.link_type)).first():
        raise Conflict("This link already exists.")
    if body.link_type in svc.PROPAGATING:
        stack, seen = [other.id], set()
        while stack:  # a dependency loop would make impact analysis meaningless
            cur = stack.pop()
            if cur == r.id:
                raise AppError(f"{other.key} already depends on {r.key}, so this would create a loop.", code="CYCLE")
            if cur not in seen:
                seen.add(cur)
                stack.extend(ctx.db.execute(select(RequirementLink.to_id).where(RequirementLink.from_id == cur, RequirementLink.link_type.in_(svc.PROPAGATING))).scalars())
    ctx.db.add(RequirementLink(from_id=r.id, to_id=other.id, link_type=body.link_type, created_by_id=ctx.user.id))
    ctx.audit("requirement.link.add", "requirement", r.id, f"{r.key} {body.link_type} {other.key}")
    ctx.db.commit()
    return _detail(ctx, r)


@router.delete("/requirements/{rid}/links/{link_id}")
def remove_link(rid: uuid.UUID, link_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    r = _req(ctx, rid)
    _require_edit(ctx, r)
    link = get_or_404(ctx.db, RequirementLink, link_id, "Link")
    if r.id not in (link.from_id, link.to_id):
        raise AppError("This link does not belong to this requirement.")
    ctx.audit("requirement.link.remove", "requirement", r.id, f"Link {link.link_type} removed from {r.key}")
    ctx.db.delete(link)
    ctx.db.commit()
    return _detail(ctx, r)


class TaskLinkIn(BaseModel):
    work_item_id: uuid.UUID
    link_type: str = Field(default="implements", pattern=r"^(implements|verifies|related_to)$")


class DocLinkIn(BaseModel):
    document_id: uuid.UUID
    link_type: str = Field(default="specified_in", pattern=r"^(specified_in|derived_from|related_to)$")


@router.post("/requirements/{rid}/tasks")
def link_task(rid: uuid.UUID, body: TaskLinkIn, ctx: Ctx = Depends(get_ctx)):
    r = _req(ctx, rid)
    w = get_or_404(ctx.db, WorkItem, body.work_item_id, "Task")
    if not can_view_task(ctx.db, ctx.p, w):
        raise Forbidden("You do not have access to that task.")
    if not svc.can_edit(ctx.db, ctx.p, r) and not can_manage_task(ctx.db, ctx.p, w):
        raise Forbidden("Linking needs requirement edit or task management permission in this scope.")
    if ctx.db.execute(select(RequirementWorkItem.id).where(RequirementWorkItem.requirement_id == r.id, RequirementWorkItem.work_item_id == w.id)).first():
        raise Conflict("This task is already linked.")
    ctx.db.add(RequirementWorkItem(requirement_id=r.id, work_item_id=w.id, link_type=body.link_type, created_by_id=ctx.user.id))
    ctx.audit("requirement.task.link", "requirement", r.id, f"{w.key} {body.link_type} {r.key}")
    ctx.db.commit()
    return _detail(ctx, r)


@router.delete("/requirements/{rid}/tasks/{link_id}")
def unlink_task(rid: uuid.UUID, link_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    r = _req(ctx, rid)
    _require_edit(ctx, r)
    x = get_or_404(ctx.db, RequirementWorkItem, link_id, "Link")
    if x.requirement_id != r.id:
        raise AppError("This link does not belong to this requirement.")
    ctx.audit("requirement.task.unlink", "requirement", r.id, f"Task link removed from {r.key}")
    ctx.db.delete(x)
    ctx.db.commit()
    return _detail(ctx, r)


@router.post("/requirements/{rid}/documents")
def link_document(rid: uuid.UUID, body: DocLinkIn, ctx: Ctx = Depends(get_ctx)):
    r = _req(ctx, rid)
    _require_edit(ctx, r)
    d = get_or_404(ctx.db, Document, body.document_id, "Document")
    if not can_view_document(ctx.db, ctx.p, d):
        raise Forbidden("You do not have access to that document.")
    if ctx.db.execute(select(RequirementDocument.id).where(RequirementDocument.requirement_id == r.id, RequirementDocument.document_id == d.id)).first():
        raise Conflict("This document is already linked.")
    ctx.db.add(RequirementDocument(requirement_id=r.id, document_id=d.id, link_type=body.link_type, created_by_id=ctx.user.id))
    ctx.audit("requirement.document.link", "requirement", r.id, f"{r.key} {body.link_type} {d.number}")
    ctx.db.commit()
    return _detail(ctx, r)


@router.delete("/requirements/{rid}/documents/{link_id}")
def unlink_document(rid: uuid.UUID, link_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    r = _req(ctx, rid)
    _require_edit(ctx, r)
    x = get_or_404(ctx.db, RequirementDocument, link_id, "Link")
    if x.requirement_id != r.id:
        raise AppError("This link does not belong to this requirement.")
    ctx.audit("requirement.document.unlink", "requirement", r.id, f"Document link removed from {r.key}")
    ctx.db.delete(x)
    ctx.db.commit()
    return _detail(ctx, r)


@router.post("/requirements/{rid}/impact-task")
def create_impact_task(rid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    """Impact analysis creates a review task for a person to decide; it never changes the linked records itself."""
    r = _req(ctx, rid)
    _require_edit(ctx, r)
    reach = svc.impact(ctx.db, r, ctx.p)
    lines = [f"Requirement {x['key']} ({x['because']})" for x in reach["requirements"]] + [f"Task {x['key']}" for x in reach["tasks"]] + [f"Document {x['number']}" for x in reach["documents"]] + [f"Baseline {x['seq']}: {x['label']}" for x in reach["baselines"]]
    if not lines:
        raise AppError("Nothing is linked to this requirement, so there is nothing to review.")
    p = ctx.db.get(Project, r.project_id)
    w = WorkItem(key=f"{p.code}-{next_seq(ctx.db, 'wi:' + p.code)}", title=f"Impact review for {r.key} revision {r.revision}"[:300], description=r.title, kind="CHANGE_REQUEST", status=initial_state(task_lifecycle(ctx.db, p.id)), project_id=p.id, item_id=r.item_id, org_unit_id=r.org_unit_id, assignee_id=r.owner_id or ctx.user.id, reporter_id=ctx.user.id)
    ctx.db.add(w)
    ctx.db.flush()
    for i, text in enumerate(lines[:100]):
        ctx.db.add(TaskChecklistItem(work_item_id=w.id, text=f"Assess: {text}"[:500], sort_order=i))
    ctx.db.add(WorkItemEvent(work_item_id=w.id, actor_id=ctx.user.id, kind="CREATED", to_value=w.status, comment=f"Created from the impact analysis of {r.key}"))
    ctx.db.add(RequirementWorkItem(requirement_id=r.id, work_item_id=w.id, link_type="related_to", created_by_id=ctx.user.id))
    ctx.audit("requirement.impact.task", "requirement", r.id, f"{w.key} created to review the impact of {r.key}", {"items": len(lines)})
    ctx.db.commit()
    return {"id": str(w.id), "key": w.key, "items": len(lines)}


# ------------------------------------------------------------------ baselines
class BaselineIn(BaseModel):
    label: str = Field(min_length=2, max_length=300)
    reason: str = Field(min_length=3, max_length=4000)
    requirement_ids: list[uuid.UUID] | None = None  # None = every approved requirement in the project


@router.get("/projects/{pid}/requirement-baselines")
def list_baselines(pid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    _project(ctx, pid)
    rows = ctx.db.execute(select(RequirementBaseline).where(RequirementBaseline.project_id == pid).order_by(RequirementBaseline.seq.desc())).scalars().all()
    out = []
    for b in rows:
        n = ctx.db.execute(select(func.count(RequirementBaselineItem.id)).where(RequirementBaselineItem.baseline_id == b.id)).scalar()
        out.append({"id": str(b.id), "seq": b.seq, "label": b.label, "reason": b.reason, "sha256": b.sha256, "items": n, "created_at": iso(b.created_at), "created_by": user_brief(ctx.db.get(User, b.created_by_id)) if b.created_by_id else None})
    return out


@router.post("/projects/{pid}/requirement-baselines")
def create_baseline(pid: uuid.UUID, body: BaselineIn, ctx: Ctx = Depends(get_ctx)):
    p = _project(ctx, pid)
    ctx.p.require("req.baseline", project_id=pid)
    q = select(Requirement).where(Requirement.project_id == pid)
    q = q.where(Requirement.id.in_(body.requirement_ids)) if body.requirement_ids else q.where(Requirement.status == "APPROVED")
    reqs = ctx.db.execute(q.order_by(Requirement.key)).scalars().all()
    if not reqs:
        raise AppError("There are no approved requirements to baseline.")
    if body.requirement_ids and len(reqs) != len(set(body.requirement_ids)):
        raise AppError("Some selected requirements are not in this project.")
    bad = [f"{r.key} is {r.status.replace('_', ' ').lower()}." for r in reqs if r.status not in svc.RELEASED_STATES]
    if bad:
        raise AppError("Only approved requirements can be baselined.", code="GATE_BLOCKED", details={"errors": bad[:50]})
    seq = (ctx.db.execute(select(func.max(RequirementBaseline.seq)).where(RequirementBaseline.project_id == pid)).scalar() or 0) + 1
    b = RequirementBaseline(project_id=pid, seq=seq, label=body.label, reason=body.reason, sha256="", created_by_id=ctx.user.id)
    ctx.db.add(b)
    ctx.db.flush()
    items = [svc.baseline_item(b.id, r) for r in reqs]
    ctx.db.add_all(items)
    b.sha256 = svc.seal_items(items)
    for r in reqs:
        if r.status == "APPROVED":
            r.status = "BASELINED"
            r.version += 1
            svc.add_event(ctx.db, r, "BASELINED", ctx.user.id, frm="APPROVED", to="BASELINED", comment=f"Baseline {seq}: {body.label}")
    ctx.audit("requirement.baseline", "requirement_baseline", b.id, f"Baseline {seq} ({body.label}) of {p.code}: {len(items)} requirement(s)", {"sha256": b.sha256, "reason": body.reason})
    ctx.db.commit()
    return {"id": str(b.id), "seq": seq, "sha256": b.sha256, "items": len(items)}


@router.get("/requirement-baselines/{bid}")
def baseline_detail(bid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    b = get_or_404(ctx.db, RequirementBaseline, bid, "Baseline")
    _project(ctx, b.project_id)
    items = ctx.db.execute(select(RequirementBaselineItem).where(RequirementBaselineItem.baseline_id == b.id).order_by(RequirementBaselineItem.key)).scalars().all()
    return {"id": str(b.id), "seq": b.seq, "label": b.label, "reason": b.reason, "sha256": b.sha256, "created_at": iso(b.created_at), "integrity_ok": svc.seal_items(items) == b.sha256,
            "items": [{"requirement_id": str(i.requirement_id) if i.requirement_id else None, "key": i.key, "revision": i.revision, "title": i.title, "description": i.description, "acceptance_criteria": i.acceptance_criteria, "req_type": i.req_type, "priority": i.priority, "content_sha256": i.content_sha256} for i in items]}


@router.get("/requirement-baselines/{bid}/compare")
def baseline_compare(bid: uuid.UUID, against: uuid.UUID | None = None, ctx: Ctx = Depends(get_ctx)):
    b = get_or_404(ctx.db, RequirementBaseline, bid, "Baseline")
    _project(ctx, b.project_id)
    old = ctx.db.execute(select(RequirementBaselineItem).where(RequirementBaselineItem.baseline_id == b.id)).scalars().all()
    if against:
        other = get_or_404(ctx.db, RequirementBaseline, against, "Baseline")
        if other.project_id != b.project_id:
            raise AppError("Those baselines belong to different projects.")
        rows = ctx.db.execute(select(RequirementBaselineItem).where(RequirementBaselineItem.baseline_id == other.id)).scalars().all()
        new = [{"key": i.key, "title": i.title, "revision": i.revision, "content_sha256": i.content_sha256} for i in rows]
        label = f"Baseline {other.seq}"
    else:
        rows = ctx.db.execute(select(Requirement).where(Requirement.project_id == b.project_id)).scalars().all()
        new = [{"key": r.key, "title": r.title, "revision": r.revision, "content_sha256": r.content_sha256} for r in rows]
        label = "current requirements"
    return {"baseline": {"seq": b.seq, "label": b.label}, "against": label, **svc.compare_items(old, new)}


# ------------------------------------------------------------------ CSV exchange
@router.post("/projects/{pid}/requirements/import")
def import_csv(pid: uuid.UUID, file: UploadFile = File(...), source_id: uuid.UUID = Form(...), external_version: str | None = Form(default=None), dry_run: bool = Query(True), ctx: Ctx = Depends(get_ctx)):
    """Architecture §10.3 on file exchange: preview new, changed, removed and conflicting records, then apply only with
    dry_run=false. Approved or baselined requirements are never overwritten. Removed records are reported, not deleted."""
    p = _project(ctx, pid)
    ctx.p.require("req.edit", project_id=pid)
    src = get_or_404(ctx.db, RequirementSource, source_id, "Source")
    if src.project_id != pid:
        raise AppError("The source belongs to a different project.")
    raw = file.file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise AppError("The CSV file is too large (limit 5 MB).")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise AppError("The file must be UTF-8 encoded CSV.") from None
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip() for h in (reader.fieldnames or [])]
    if "title" not in headers or "external_id" not in headers:
        raise AppError("The CSV needs 'external_id' and 'title' columns.", details={"errors": [f"Columns: {', '.join(CSV_COLUMNS)}"]})
    existing = {r.external_id: r for r in ctx.db.execute(select(Requirement).where(Requirement.source_id == src.id, Requirement.external_id.is_not(None))).scalars()}
    new, changed, unchanged, conflicts, errors = [], [], [], [], []
    seen: set[str] = set()
    for n, raw_row in enumerate(reader, 2):
        rec = {(k or "").strip(): (v or "").strip() for k, v in raw_row.items() if isinstance(v, str)}
        ext, title = rec.get("external_id", ""), rec.get("title", "")
        problems = []
        if not ext:
            problems.append("external_id is empty.")
        elif ext in seen:
            problems.append(f"external_id {ext} appears twice in the file.")
        if not 3 <= len(title) <= 500:
            problems.append("title must be 3 to 500 characters.")
        seen.add(ext)
        priority = (rec.get("priority") or "MEDIUM").upper()
        if priority not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            problems.append(f"priority {priority} is not valid.")
        req_type = rec.get("type") or "FUNCTIONAL"
        if problems:
            errors.append({"row": n, "errors": problems})
            continue
        values = {"title": title, "description": rec.get("description") or None, "acceptance_criteria": rec.get("acceptance_criteria") or None, "req_type": req_type[:40], "priority": priority}
        cur = existing.get(ext)
        if cur is None:
            new.append({"external_id": ext, **values})
        elif svc.hash_of(cur) == svc.content_hash(title, values["description"], values["acceptance_criteria"], values["req_type"], priority):
            unchanged.append(ext)
        elif cur.status in svc.RELEASED_STATES or cur.status in svc.LOCKED_WHILE:
            conflicts.append({"external_id": ext, "key": cur.key, "status": cur.status, "title": title})
        else:
            changed.append({"external_id": ext, "key": cur.key, "req": cur, "values": values})
    removed = [{"external_id": e, "key": r.key} for e, r in existing.items() if e not in seen]
    summary = {"new": [{"external_id": x["external_id"], "title": x["title"]} for x in new], "changed": [{"external_id": x["external_id"], "key": x["key"], "title": x["values"]["title"]} for x in changed], "unchanged": len(unchanged), "conflicts": conflicts, "removed": removed, "errors": errors}
    if dry_run or errors:
        return {**summary, "dry_run": True, "committed": False}
    for x in new:
        ext = x.pop("external_id")
        r = Requirement(project_id=pid, source_id=src.id, key=tagging.next_tag(ctx.db, src, x.get("item_id")), external_id=ext, external_version=external_version, owner_id=ctx.user.id, status="DRAFT", content_sha256=svc.content_hash(x["title"], x["description"], x["acceptance_criteria"], x["req_type"], x["priority"]), **x)
        ctx.db.add(r)
        ctx.db.flush()
        svc.write_revision(ctx.db, r, ctx.user.id, f"Imported from {src.name}")
        svc.add_event(ctx.db, r, "IMPORTED", ctx.user.id, to="DRAFT", comment=f"{src.name}: {ext}")
    for x in changed:
        svc.apply_content(ctx.db, x["req"], x["values"], actor=ctx.user.id, reason=f"Imported from {src.name}")
        x["req"].external_version = external_version
        svc.add_event(ctx.db, x["req"], "IMPORTED", ctx.user.id, comment=f"Updated from {src.name}")
    src.last_synced_at = utcnow()
    src.file_sha256 = hashlib.sha256(raw).hexdigest()
    src.external_version = external_version or src.external_version
    ctx.audit("requirement.import", "requirement_source", src.id, f"{len(new)} new and {len(changed)} changed requirement(s) imported into {p.code} from {src.name}", {"sha256": src.file_sha256, "conflicts": len(conflicts), "removed": len(removed), "filename": file.filename})
    ctx.db.commit()
    return {**summary, "dry_run": False, "committed": True}
