"""Design and engineering artefacts (architecture §11): configurable types, design records, immutable versions
(draw.io diagram source + SVG preview, uploaded files, external links), controlled restore, hash-bound review and
approval, baseline, links to requirements / documents / tasks with section mapping, and a PDF record report.

Lifecycle (§11.1): DRAFT → IN_PROGRESS → SUBMITTED → UNDER_REVIEW → APPROVED → BASELINED, with CHANGES_REQUESTED → IN_PROGRESS.
The record is locked while SUBMITTED / UNDER_REVIEW. Changing APPROVED or BASELINED content needs a reason and starts
a new version; the baselined version and its hash stay as they were."""
from __future__ import annotations

import hashlib
import io
import json
import uuid
from xml.etree import ElementTree

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.deps import Ctx, get_ctx, get_or_404
from app.core.errors import AppError, Conflict, Forbidden
from app.models import Document, EngineeringItem, FileObject, OrgUnit, Project, Requirement, User, WorkItem
from app.models.artifacts import ArtifactReview
from app.models.design import DesignRecord, DesignType, DesignVersion
from app.services import artifacts as art
from app.services import storage
from app.services.authz import Principal, can_view_document
from app.services.numbering import next_seq
from app.services.planning import can_view_project, can_view_task, require_view_project
from app.services.requirements import can_view as can_view_requirement
from app.services.serial import iso, user_brief

router = APIRouter(tags=["design"])
A = "DESIGN"
LOCKED = {"SUBMITTED", "UNDER_REVIEW"}
RELEASED = {"APPROVED", "BASELINED"}
LINK_TYPES = r"^(satisfies|describes|implements|related_to|verified_by)$"
STATES = [
    {"code": "DRAFT", "label": "Draft", "color": "gray"}, {"code": "IN_PROGRESS", "label": "In progress", "color": "blue"}, {"code": "SUBMITTED", "label": "Submitted", "color": "indigo"},
    {"code": "UNDER_REVIEW", "label": "Under review", "color": "violet"}, {"code": "CHANGES_REQUESTED", "label": "Changes requested", "color": "orange"},
    {"code": "APPROVED", "label": "Approved", "color": "cyan"}, {"code": "BASELINED", "label": "Baselined", "color": "teal"},
]
MAX_DIAGRAM_BYTES = 20_000_000


# ------------------------------------------------------------------ access
def _path(db, model, oid):
    o = db.get(model, oid) if oid else None
    return o.path if o else None


def can_view(db, p: Principal, d: DesignRecord) -> bool:
    return can_view_project(db, p, d.project_id) or d.owner_id == p.id or art.is_reviewer(db, A, d.id, p.id)


def can_edit(db, p: Principal, d: DesignRecord) -> bool:
    return d.owner_id == p.id or p.has("design.edit", project_id=d.project_id, org_path=_path(db, OrgUnit, d.org_unit_id), item_path=_path(db, EngineeringItem, d.item_id))


def _design(ctx: Ctx, did: uuid.UUID) -> DesignRecord:
    d = get_or_404(ctx.db, DesignRecord, did, "Design record")
    if not can_view(ctx.db, ctx.p, d):
        raise Forbidden("You do not have access to this design record.")
    return d


def _require_edit(ctx: Ctx, d: DesignRecord) -> None:
    if not can_edit(ctx.db, ctx.p, d):
        raise Forbidden("Only the owner or someone with design edit permission in this scope can change this.", details={"permission": "design.edit"})


def _see(ctx: Ctx):
    def check(t: str, oid) -> bool:
        db = ctx.db
        if t == "REQUIREMENT":
            o = db.get(Requirement, oid)
            return bool(o) and can_view_requirement(db, ctx.p, o)
        if t == "DOCUMENT":
            o = db.get(Document, oid)
            return bool(o) and can_view_document(db, ctx.p, o)
        if t == "TASK":
            o = db.get(WorkItem, oid)
            return bool(o) and can_view_task(db, ctx.p, o)
        o = art.target_summary(db, t, oid)
        return bool(o) and bool(o.get("project_id")) and can_view_project(db, ctx.p, uuid.UUID(o["project_id"]))
    return check


def _set_status(ctx: Ctx, d: DesignRecord, to: str, comment: str | None = None) -> None:
    if d.status != to:
        art.add_event(ctx.db, A, d.id, "STATUS", ctx.user.id, d.status, to, comment)
        d.status = to


def _cur(db, d: DesignRecord) -> DesignVersion | None:
    if not d.current_version:
        return None
    return db.execute(select(DesignVersion).where(DesignVersion.design_id == d.id, DesignVersion.version_no == d.current_version)).scalar_one_or_none()


# ------------------------------------------------------------------ types
class TypeIn(BaseModel):
    code: str = Field(pattern=r"^[A-Z0-9_]{2,30}$")
    name: str = Field(min_length=2, max_length=150)
    category: str = Field(default="SOFTWARE", pattern=r"^(SOFTWARE|ENGINEERING|SYSTEMS|OTHER)$")
    description: str | None = None
    allowed_extensions: str = Field(default="drawio,svg,png,jpg,pdf", max_length=200)
    diagram_editor: bool = True
    fields: list[dict] = Field(default_factory=list)
    color: str | None = Field(default=None, max_length=20)
    active: bool = True


def _type_dict(t: DesignType) -> dict:
    return {"id": str(t.id), "code": t.code, "name": t.name, "category": t.category, "description": t.description, "allowed_extensions": t.allowed_extensions, "diagram_editor": t.diagram_editor,
            "fields": json.loads(t.fields or "[]"), "color": t.color, "active": t.active}


def _check_fields(fields: list[dict]) -> None:
    keys = set()
    for f in fields:
        if not f.get("key") or not f.get("label") or f.get("type", "text") not in ("text", "textarea", "number", "select", "date", "checkbox"):
            raise AppError("Every field needs a key, a label and a type (text, textarea, number, select, date, checkbox).")
        if f["key"] in keys:
            raise AppError(f"Field key {f['key']} is used twice.")
        keys.add(f["key"])


@router.get("/design-types")
def list_types(ctx: Ctx = Depends(get_ctx)):
    return [_type_dict(t) for t in ctx.db.execute(select(DesignType).order_by(DesignType.category, DesignType.name)).scalars()]


@router.post("/design-types")
def create_type(body: TypeIn, ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("admin.config")
    _check_fields(body.fields)
    if ctx.db.execute(select(DesignType.id).where(DesignType.code == body.code)).first():
        raise AppError(f"Type code {body.code} exists already.", code="DUPLICATE")
    t = DesignType(**{**body.model_dump(), "fields": json.dumps(body.fields)})
    ctx.db.add(t)
    ctx.db.flush()
    ctx.audit("design.type.create", "design_type", t.id, f"Design type {t.code} created")
    ctx.db.commit()
    return _type_dict(t)


@router.put("/design-types/{tid}")
def update_type(tid: uuid.UUID, body: TypeIn, ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("admin.config")
    t = get_or_404(ctx.db, DesignType, tid, "Design type")
    _check_fields(body.fields)
    for k, v in body.model_dump().items():
        if k != "code":
            setattr(t, k, json.dumps(v) if k == "fields" else v)
    ctx.audit("design.type.update", "design_type", t.id, f"Design type {t.code} updated")
    ctx.db.commit()
    return _type_dict(t)


@router.get("/design/config")
def design_config(ctx: Ctx = Depends(get_ctx)):
    s = get_settings()
    return {"drawio_url": s.drawio_url.rstrip("/") if s.drawio_url else None, "states": STATES}


# ------------------------------------------------------------------ records
class DesignIn(BaseModel):
    type_id: uuid.UUID
    title: str = Field(min_length=3, max_length=300)
    description: str | None = None
    item_id: uuid.UUID | None = None
    org_unit_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    attributes: dict = Field(default_factory=dict)
    reason: str | None = Field(default=None, max_length=1000)


def _brief(db, d: DesignRecord, types: dict, users: dict) -> dict:
    t = types.get(d.type_id)
    return {"id": str(d.id), "key": d.key, "title": d.title, "status": d.status, "type": {"id": str(t.id), "code": t.code, "name": t.name, "color": t.color} if t else None,
            "current_version": d.current_version, "baselined_version": d.baselined_version, "item_id": str(d.item_id) if d.item_id else None, "owner": user_brief(users.get(d.owner_id)),
            "updated_at": iso(d.updated_at), "version": d.version}


def _validate(ctx: Ctx, pid: uuid.UUID, body: DesignIn) -> DesignType:
    t = get_or_404(ctx.db, DesignType, body.type_id, "Design type")
    if not t.active:
        raise AppError("That design type is switched off.")
    if body.item_id:
        it = get_or_404(ctx.db, EngineeringItem, body.item_id, "Item")
        if it.project_id != pid:
            raise AppError("The engineering item belongs to a different project.")
    for f in json.loads(t.fields or "[]"):
        if f.get("required") and body.attributes.get(f["key"]) in (None, "", []):
            raise AppError(f"{f['label']} is required for {t.name}.", code="FIELD_REQUIRED")
    return t


@router.get("/projects/{pid}/designs")
def list_designs(pid: uuid.UUID, q: str | None = None, status: str | None = None, type_id: uuid.UUID | None = None, item_id: uuid.UUID | None = None, ctx: Ctx = Depends(get_ctx)):
    require_view_project(ctx.db, ctx.p, pid)
    s = select(DesignRecord).where(DesignRecord.project_id == pid)
    if q:
        like = f"%{q}%"
        s = s.where(or_(DesignRecord.title.ilike(like), DesignRecord.key.ilike(like), DesignRecord.description.ilike(like)))
    if status:
        s = s.where(DesignRecord.status.in_(status.split(",")))
    if type_id:
        s = s.where(DesignRecord.type_id == type_id)
    if item_id:
        s = s.where(DesignRecord.item_id == item_id)
    rows = ctx.db.execute(s.order_by(DesignRecord.key)).scalars().all()
    types = {t.id: t for t in ctx.db.execute(select(DesignType)).scalars()}
    users = art._users(ctx.db, {d.owner_id for d in rows})
    return {"can_create": ctx.p.has("design.edit", project_id=pid), "states": STATES, "items": [_brief(ctx.db, d, types, users) for d in rows]}


@router.post("/projects/{pid}/designs")
def create_design(pid: uuid.UUID, body: DesignIn, ctx: Ctx = Depends(get_ctx)):
    p = get_or_404(ctx.db, Project, pid, "Project")
    require_view_project(ctx.db, ctx.p, pid)
    if not ctx.p.has("design.edit", project_id=pid, org_path=_path(ctx.db, OrgUnit, body.org_unit_id), item_path=_path(ctx.db, EngineeringItem, body.item_id)):
        raise Forbidden("Creating design records needs design edit permission in this project.", details={"permission": "design.edit"})
    t = _validate(ctx, pid, body)
    d = DesignRecord(project_id=pid, item_id=body.item_id, org_unit_id=body.org_unit_id, type_id=t.id, key=f"{p.code}-DES-{next_seq(ctx.db, 'des:' + p.code):04d}", title=body.title,
                     description=body.description, attributes=json.dumps(body.attributes), owner_id=body.owner_id or ctx.user.id, created_by_id=ctx.user.id)
    ctx.db.add(d)
    ctx.db.flush()
    art.add_event(ctx.db, A, d.id, "CREATED", ctx.user.id, to="DRAFT")
    ctx.audit("design.create", "design_record", d.id, f"{d.key} created: {d.title}")
    ctx.db.commit()
    return _detail(ctx, d)


def _detail(ctx: Ctx, d: DesignRecord) -> dict:
    db = ctx.db
    t = db.get(DesignType, d.type_id)
    versions = db.execute(select(DesignVersion).where(DesignVersion.design_id == d.id).order_by(DesignVersion.version_no.desc())).scalars().all()
    users = art._users(db, {d.owner_id, d.baselined_by_id} | {v.created_by_id for v in versions})
    files = {f.id: f for f in db.execute(select(FileObject).where(FileObject.id.in_({v.source_file_id for v in versions} | {v.preview_file_id for v in versions} | {uuid.uuid4()}))).scalars()}
    editable = can_edit(db, ctx.p, d)

    def fdict(fid):
        f = files.get(fid)
        return {"name": f.original_name, "extension": f.extension, "size": f.size_bytes, "sha256": f.sha256} if f else None

    return {
        **_brief(db, d, {t.id: t}, users), "description": d.description, "attributes": json.loads(d.attributes or "{}"), "type": _type_dict(t), "project_id": str(d.project_id),
        "org_unit_id": str(d.org_unit_id) if d.org_unit_id else None, "baseline_sha256": d.baseline_sha256, "baselined_at": iso(d.baselined_at), "baselined_by": user_brief(users.get(d.baselined_by_id)),
        "can_edit": editable, "can_baseline": ctx.p.has("design.baseline", project_id=d.project_id) and d.status == "APPROVED", "locked": d.status in LOCKED,
        "versions": [{"version_no": v.version_no, "kind": v.kind, "sha256": v.content_sha256, "note": v.note, "restored_from": v.restored_from, "external_url": v.external_url, "created_at": iso(v.created_at),
                      "created_by": user_brief(users.get(v.created_by_id)), "source": fdict(v.source_file_id), "preview": fdict(v.preview_file_id), "baselined": v.version_no == d.baselined_version} for v in versions],
        "reviews": art.reviews(db, A, d.id, ctx.user.id), "links": art.links(db, A, d.id, _see(ctx)), "history": art.history(db, A, d.id),
    }


@router.get("/designs/{did}")
def get_design(did: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    return _detail(ctx, _design(ctx, did))


def _reason_for_released(ctx: Ctx, d: DesignRecord, reason: str | None) -> None:
    if d.status in LOCKED:
        raise Conflict("This design record is locked while it is in review. Withdraw it first.", code="LOCKED")
    if d.status in RELEASED:
        if not (reason or "").strip():
            raise AppError(f"{d.key} is {d.status.lower()}. Give a reason for the change; the record goes back to In progress and the earlier version stays as it was.", code="REASON_REQUIRED")
        _set_status(ctx, d, "IN_PROGRESS", reason)
    elif d.status in ("DRAFT", "CHANGES_REQUESTED"):
        _set_status(ctx, d, "IN_PROGRESS")


@router.put("/designs/{did}")
def update_design(did: uuid.UUID, body: DesignIn, version: int | None = None, ctx: Ctx = Depends(get_ctx)):
    d = _design(ctx, did)
    _require_edit(ctx, d)
    if version is not None and version != d.version:
        raise Conflict("The record was changed by someone else. Refresh and try again.")
    _validate(ctx, d.project_id, body)
    if body.type_id != d.type_id and d.current_version:
        raise AppError("The type cannot change once versions exist.")
    content_changed = (body.title, body.description, json.dumps(body.attributes, sort_keys=True)) != (d.title, d.description, json.dumps(json.loads(d.attributes or "{}"), sort_keys=True))
    if content_changed:
        _reason_for_released(ctx, d, body.reason)
    elif d.status in LOCKED and (body.item_id != d.item_id or body.owner_id not in (None, d.owner_id)):
        raise Conflict("This design record is locked while it is in review.", code="LOCKED")
    d.title, d.description, d.attributes, d.item_id, d.org_unit_id, d.type_id = body.title, body.description, json.dumps(body.attributes), body.item_id, body.org_unit_id, body.type_id
    if body.owner_id:
        d.owner_id = body.owner_id
    d.version += 1
    ctx.audit("design.update", "design_record", d.id, f"{d.key} updated", {"reason": body.reason})
    ctx.db.commit()
    return _detail(ctx, d)


# ------------------------------------------------------------------ versions
def _new_version(ctx: Ctx, d: DesignRecord, *, kind: str, sha: str, base_version: int | None, reason: str | None, note: str | None, source=None, preview=None, url=None, restored_from=None) -> DesignVersion:
    _require_edit(ctx, d)
    if base_version is not None and base_version != d.current_version:
        raise Conflict(f"Version {d.current_version} was saved by someone else while you were editing version {base_version}. Your change was not saved; reload, then apply it again.", code="VERSION_CONFLICT")
    _reason_for_released(ctx, d, reason)
    v = DesignVersion(design_id=d.id, version_no=d.current_version + 1, kind=kind, source_file_id=source.id if source else None, preview_file_id=preview.id if preview else None, external_url=url,
                      content_sha256=sha, note=(note or reason or "")[:1000] or None, restored_from=restored_from, created_at=utcnow(), created_by_id=ctx.user.id)
    ctx.db.add(v)
    d.current_version = v.version_no
    d.version += 1
    art.add_event(ctx.db, A, d.id, "RESTORE" if restored_from else "VERSION", ctx.user.id, restored_from, v.version_no, v.note)
    ctx.db.flush()
    return v


class DiagramIn(BaseModel):
    xml: str = Field(min_length=10)
    svg: str | None = None
    base_version: int | None = None
    note: str | None = Field(default=None, max_length=1000)
    reason: str | None = Field(default=None, max_length=1000)


def _check_xml(text: str, root_names: tuple[str, ...], what: str) -> None:
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise AppError(f"The {what} contains a DOCTYPE or entity declaration, which is not allowed.", code="FILE_SIGNATURE")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        raise AppError(f"The {what} is not well-formed XML.", code="FILE_SIGNATURE") from None
    if root.tag.split("}")[-1] not in root_names:
        raise AppError(f"The {what} is not a {'/'.join(root_names)} document.", code="FILE_SIGNATURE")
    if what == "SVG preview" and ("<script" in text.lower() or "javascript:" in text.lower()):
        raise AppError("The SVG preview contains script, which is not allowed.", code="FILE_SIGNATURE")


@router.post("/designs/{did}/diagram")
def save_diagram(did: uuid.UUID, body: DiagramIn, ctx: Ctx = Depends(get_ctx)):
    """Save from the embedded draw.io editor. Optimistic: base_version must still be current, else nothing is saved."""
    d = _design(ctx, did)
    raw = body.xml.encode()
    if len(raw) > MAX_DIAGRAM_BYTES:
        raise AppError("The diagram is too large.", code="FILE_TOO_LARGE")
    _check_xml(body.xml, ("mxfile", "mxGraphModel"), "diagram")
    if body.svg:
        _check_xml(body.svg, ("svg",), "SVG preview")
    cur = _cur(ctx.db, d)
    sha = hashlib.sha256(raw).hexdigest()
    if cur and cur.content_sha256 == sha:
        raise AppError("Nothing changed since the current version.", code="NO_CHANGE")
    src = storage.put_bytes(ctx.db, raw, f"{d.key}-v{d.current_version + 1}.drawio", ctx.user.id)
    prev = storage.put_bytes(ctx.db, body.svg.encode(), f"{d.key}-v{d.current_version + 1}.svg", ctx.user.id) if body.svg else None
    v = _new_version(ctx, d, kind="DIAGRAM", sha=sha, base_version=body.base_version, reason=body.reason, note=body.note, source=src, preview=prev)
    ctx.audit("design.version", "design_record", d.id, f"{d.key} diagram saved as version {v.version_no}", {"sha256": sha})
    ctx.db.commit()
    return _detail(ctx, d)


@router.post("/designs/{did}/versions")
async def upload_version(did: uuid.UUID, file: UploadFile = File(...), preview: UploadFile | None = File(None), note: str | None = Form(None), reason: str | None = Form(None),
                         base_version: int | None = Form(None), ctx: Ctx = Depends(get_ctx)):
    d = _design(ctx, did)
    t = ctx.db.get(DesignType, d.type_id)
    data = await file.read()
    ext = storage.ext_of(file.filename or "")
    allowed = [x.strip() for x in (t.allowed_extensions or "").split(",") if x.strip()]
    storage.validate_content(data, ext, allowed)
    if ext in ("drawio", "xml"):
        _check_xml(data.decode("utf-8", "replace"), ("mxfile", "mxGraphModel"), "diagram")
    if ext == "svg":
        _check_xml(data.decode("utf-8", "replace"), ("svg",), "SVG preview")
    src = storage.put_bytes(ctx.db, data, file.filename or f"{d.key}.{ext}", ctx.user.id)
    prev = None
    if preview is not None and preview.filename:
        pdata = await preview.read()
        pext = storage.ext_of(preview.filename)
        storage.validate_content(pdata, pext, ["svg", "png", "jpg", "jpeg"])
        if pext == "svg":
            _check_xml(pdata.decode("utf-8", "replace"), ("svg",), "SVG preview")
        prev = storage.put_bytes(ctx.db, pdata, preview.filename, ctx.user.id)
    v = _new_version(ctx, d, kind="DIAGRAM" if ext in ("drawio", "xml") else "FILE", sha=src.sha256, base_version=base_version, reason=reason, note=note, source=src, preview=prev)
    ctx.audit("design.version", "design_record", d.id, f"{d.key} version {v.version_no} uploaded ({src.original_name})", {"sha256": src.sha256})
    ctx.db.commit()
    return _detail(ctx, d)


class LinkVersionIn(BaseModel):
    url: str = Field(pattern=r"^https?://", max_length=1000)
    note: str | None = Field(default=None, max_length=1000)
    reason: str | None = Field(default=None, max_length=1000)
    base_version: int | None = None


@router.post("/designs/{did}/link-version")
def link_version(did: uuid.UUID, body: LinkVersionIn, ctx: Ctx = Depends(get_ctx)):
    d = _design(ctx, did)
    v = _new_version(ctx, d, kind="LINK", sha=hashlib.sha256(body.url.encode()).hexdigest(), base_version=body.base_version, reason=body.reason, note=body.note, url=body.url)
    ctx.audit("design.version", "design_record", d.id, f"{d.key} version {v.version_no}: external link")
    ctx.db.commit()
    return _detail(ctx, d)


class RestoreIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/designs/{did}/versions/{n}/restore")
def restore_version(did: uuid.UUID, n: int, body: RestoreIn, ctx: Ctx = Depends(get_ctx)):
    """Controlled restore: a NEW version copying version n. Nothing is overwritten or deleted."""
    d = _design(ctx, did)
    old = ctx.db.execute(select(DesignVersion).where(DesignVersion.design_id == d.id, DesignVersion.version_no == n)).scalar_one_or_none()
    if not old:
        raise AppError(f"Version {n} does not exist.")
    if n == d.current_version:
        raise AppError("That is already the current version.")
    v = _new_version(ctx, d, kind=old.kind, sha=old.content_sha256, base_version=None, reason=body.reason, note=f"Restored from version {n}: {body.reason}", restored_from=n,
                     source=ctx.db.get(FileObject, old.source_file_id) if old.source_file_id else None, preview=ctx.db.get(FileObject, old.preview_file_id) if old.preview_file_id else None, url=old.external_url)
    ctx.audit("design.restore", "design_record", d.id, f"{d.key} version {n} restored as version {v.version_no}", {"reason": body.reason})
    ctx.db.commit()
    return _detail(ctx, d)


@router.get("/designs/{did}/versions/{n}/{part}")
def version_file(did: uuid.UUID, n: int, part: str, ctx: Ctx = Depends(get_ctx)):
    d = _design(ctx, did)
    if part not in ("source", "preview"):
        raise AppError("Part must be source or preview.")
    v = ctx.db.execute(select(DesignVersion).where(DesignVersion.design_id == d.id, DesignVersion.version_no == n)).scalar_one_or_none()
    fid = (v.source_file_id if part == "source" else v.preview_file_id) if v else None
    if not fid:
        raise AppError("This version has no such file.", status_code=404, code="NOT_FOUND")
    f = ctx.db.get(FileObject, fid)
    data = storage.read_bytes(f, verify=True)
    mime = "image/svg+xml" if f.extension == "svg" else ("application/xml" if f.extension in ("drawio", "xml") else f.mime_type)
    disp = "inline" if part == "preview" and f.extension in ("svg", "png", "jpg", "jpeg") else "attachment"
    headers = {"Content-Disposition": f'{disp}; filename="{storage.safe_name(f.original_name)}"', "X-Content-SHA256": f.sha256}
    if f.extension == "svg":
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
    return Response(content=data, media_type=mime, headers=headers)


# ------------------------------------------------------------------ review / approval / baseline
class SubmitIn(BaseModel):
    reviewers: list[uuid.UUID] = Field(default_factory=list)
    approvers: list[uuid.UUID] = Field(min_length=1)
    comment: str | None = Field(default=None, max_length=2000)


@router.post("/designs/{did}/submit")
def submit_design(did: uuid.UUID, body: SubmitIn, ctx: Ctx = Depends(get_ctx)):
    d = _design(ctx, did)
    _require_edit(ctx, d)
    v = _cur(ctx.db, d)
    if not v:
        raise AppError("Save at least one version (diagram, file or link) before submitting.", code="NO_CONTENT")
    if d.status not in ("IN_PROGRESS",):
        raise AppError(f"A {d.status.lower().replace('_', ' ')} record cannot be submitted. {'Save a new version first.' if d.status == 'CHANGES_REQUESTED' else ''}".strip(), code="INVALID_STATE")
    cycle = art.submit(ctx.db, a_type=A, a_id=d.id, revision=v.version_no, sha=v.content_sha256, submitter_id=ctx.user.id, reviewers=body.reviewers, approvers=body.approvers,
                       excluded={d.owner_id}, title=f"{d.key} {d.title}", link=f"/design/{d.project_id}?open={d.id}")
    _set_status(ctx, d, "SUBMITTED", body.comment)
    d.version += 1
    ctx.audit("design.submit", "design_record", d.id, f"{d.key} version {v.version_no} submitted (cycle {cycle})", {"sha256": v.content_sha256, "reviewers": [str(x) for x in body.reviewers], "approvers": [str(x) for x in body.approvers]})
    ctx.db.commit()
    return _detail(ctx, d)


@router.post("/designs/{did}/withdraw")
def withdraw_design(did: uuid.UUID, body: RestoreIn, ctx: Ctx = Depends(get_ctx)):
    d = _design(ctx, did)
    _require_edit(ctx, d)
    if d.status not in LOCKED:
        raise AppError("Only a record in review can be withdrawn.")
    art.withdraw(ctx.db, A, d.id)
    _set_status(ctx, d, "IN_PROGRESS", body.reason)
    d.version += 1
    ctx.audit("design.withdraw", "design_record", d.id, f"{d.key} withdrawn from review", {"reason": body.reason})
    ctx.db.commit()
    return _detail(ctx, d)


class DecisionIn(BaseModel):
    decision: str = Field(pattern=r"^(approve|request_changes)$")
    comment: str | None = Field(default=None, max_length=4000)


@router.post("/designs/{did}/reviews/{rid}/decide")
def decide_design(did: uuid.UUID, rid: uuid.UUID, body: DecisionIn, ctx: Ctx = Depends(get_ctx)):
    d = _design(ctx, did)
    r = get_or_404(ctx.db, ArtifactReview, rid, "Review")
    if r.artifact_type != A or r.artifact_id != d.id:
        raise AppError("That review belongs to another record.")
    v = _cur(ctx.db, d)
    outcome = art.decide(ctx.db, review=r, user_id=ctx.user.id, decision=body.decision, comment=body.comment, revision=v.version_no if v else 0, sha=v.content_sha256 if v else "",
                         title=f"{d.key} {d.title}", link=f"/design/{d.project_id}?open={d.id}", owner_id=d.owner_id)
    art.add_event(ctx.db, A, d.id, "DECISION", ctx.user.id, r.role, r.status, r.comment)
    if d.status == "SUBMITTED":
        _set_status(ctx, d, "UNDER_REVIEW")
    if outcome in ("APPROVED", "CHANGES_REQUESTED"):
        _set_status(ctx, d, outcome)
    d.version += 1
    ctx.audit("design.decide", "design_record", d.id, f"{d.key}: {r.role.lower()} {body.decision.replace('_', ' ')}", {"version": r.revision, "sha256": r.content_sha256, "outcome": outcome})
    ctx.db.commit()
    return _detail(ctx, d)


class BaselineIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/designs/{did}/baseline")
def baseline_design(did: uuid.UUID, body: BaselineIn, ctx: Ctx = Depends(get_ctx)):
    d = _design(ctx, did)
    if not ctx.p.has("design.baseline", project_id=d.project_id):
        raise Forbidden("Baselining needs the design baseline permission for this project.", details={"permission": "design.baseline"})
    if d.status != "APPROVED":
        raise AppError("Only an approved design record can be baselined.", code="INVALID_STATE")
    v = _cur(ctx.db, d)
    approved = ctx.db.execute(select(ArtifactReview.id).where(ArtifactReview.artifact_type == A, ArtifactReview.artifact_id == d.id, ArtifactReview.revision == v.version_no,
                                                          ArtifactReview.content_sha256 == v.content_sha256, ArtifactReview.status == "APPROVED", ArtifactReview.role == "APPROVER")).first()
    if not approved:
        raise AppError("The current version has no approval bound to its content.", code="GATE_BLOCKED")
    d.baselined_version, d.baseline_sha256, d.baselined_at, d.baselined_by_id = v.version_no, v.content_sha256, utcnow(), ctx.user.id
    _set_status(ctx, d, "BASELINED", body.reason)
    d.version += 1
    ctx.audit("design.baseline", "design_record", d.id, f"{d.key} version {v.version_no} baselined", {"sha256": v.content_sha256, "reason": body.reason})
    ctx.db.commit()
    return _detail(ctx, d)


# ------------------------------------------------------------------ links
class LinkIn(BaseModel):
    to_type: str = Field(pattern=r"^(REQUIREMENT|DOCUMENT|TASK|TEST_CASE)$")
    to_id: uuid.UUID
    link_type: str = Field(default="satisfies", pattern=LINK_TYPES)
    section: str | None = Field(default=None, max_length=200)


@router.post("/designs/{did}/links")
def add_design_link(did: uuid.UUID, body: LinkIn, ctx: Ctx = Depends(get_ctx)):
    d = _design(ctx, did)
    _require_edit(ctx, d)
    if not _see(ctx)(body.to_type, body.to_id):
        raise Forbidden("You do not have access to the record you are linking.")
    link = art.add_link(ctx.db, from_type=A, from_id=d.id, to_type=body.to_type, to_id=body.to_id, link_type=body.link_type, section=body.section, actor=ctx.user.id)
    s = art.target_summary(ctx.db, body.to_type, body.to_id)
    art.add_event(ctx.db, A, d.id, "LINK", ctx.user.id, None, f"{body.link_type} {s['key']}", body.section)
    ctx.audit("design.link", "design_record", d.id, f"{d.key} {body.link_type} {s['key']}", {"link": str(link.id), "section": body.section})
    ctx.db.commit()
    return _detail(ctx, d)


@router.delete("/designs/{did}/links/{lid}")
def remove_design_link(did: uuid.UUID, lid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    from app.models.artifacts import ArtifactLink

    d = _design(ctx, did)
    _require_edit(ctx, d)
    link = get_or_404(ctx.db, ArtifactLink, lid, "Link")
    if not ((link.from_type == A and link.from_id == d.id) or (link.to_type == A and link.to_id == d.id)):
        raise AppError("That link belongs to another record.")
    if d.status == "BASELINED":
        raise Conflict("Links of a baselined design record are part of the baseline.", code="LOCKED")
    art.add_event(ctx.db, A, d.id, "LINK", ctx.user.id, f"{link.link_type} {link.to_type}", None, "removed")
    ctx.db.delete(link)
    ctx.audit("design.unlink", "design_record", d.id, f"{d.key} link removed")
    ctx.db.commit()
    return _detail(ctx, d)


# ------------------------------------------------------------------ PDF report
@router.get("/designs/{did}/report.pdf")
def design_report(did: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    d = _design(ctx, did)
    det = _detail(ctx, d)
    ss = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm, title=f"{d.key} {d.title}")

    def esc(s):
        return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def table(rows, widths):
        t = Table(rows, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("FONT", (0, 1), (-1, -1), "Helvetica", 8), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return t

    proj = ctx.db.get(Project, d.project_id)
    story = [Paragraph(f"{esc(d.key)} — {esc(d.title)}", ss["Title"]),
             table([["Project", "Type", "Status", "Current version", "Baselined version"], [proj.code, det["type"]["name"], d.status, str(d.current_version), str(d.baselined_version or "—")]], [30 * mm, 45 * mm, 30 * mm, 30 * mm, 35 * mm]),
             Spacer(1, 6)]
    if d.description:
        story += [Paragraph("Description", ss["Heading3"]), Paragraph(esc(d.description).replace("\n", "<br/>"), ss["BodyText"])]
    attrs = det["attributes"]
    if attrs:
        labels = {f["key"]: f["label"] for f in det["type"]["fields"]}
        story += [Paragraph("Attributes", ss["Heading3"]), table([["Field", "Value"]] + [[esc(labels.get(k, k)), esc(v)] for k, v in attrs.items()], [50 * mm, 120 * mm])]
    cur = _cur(ctx.db, d)
    if cur and cur.preview_file_id:
        f = ctx.db.get(FileObject, cur.preview_file_id)
        if f.extension in ("png", "jpg", "jpeg"):
            img = Image(io.BytesIO(storage.read_bytes(f)))
            img._restrictSize(170 * mm, 150 * mm)
            story += [Paragraph(f"Preview of version {cur.version_no}", ss["Heading3"]), img]
        else:
            story += [Paragraph(f"Version {cur.version_no} preview is {f.extension.upper()} ({esc(f.original_name)}, SHA-256 {f.sha256[:16]}…); open it in ELM.", ss["BodyText"])]
    story += [Paragraph("Versions", ss["Heading3"]), table([["No.", "Kind", "SHA-256", "By", "When", "Note"]] + [[str(v["version_no"]), v["kind"], v["sha256"][:16] + "…", esc((v["created_by"] or {}).get("full_name")), (v["created_at"] or "")[:16], Paragraph(esc(v["note"]), ss["BodyText"])] for v in det["versions"]],
                                                     [12 * mm, 18 * mm, 32 * mm, 30 * mm, 28 * mm, 50 * mm])]
    if det["reviews"]:
        story += [Paragraph("Reviews and approvals", ss["Heading3"]), table([["Cycle", "Version", "Role", "Reviewer", "Decision", "When", "Comment"]] + [[str(r["cycle"]), str(r["revision"]), r["role"], esc((r["reviewer"] or {}).get("full_name")), r["status"], (r["decided_at"] or "")[:16], Paragraph(esc(r["comment"]), ss["BodyText"])] for r in det["reviews"]],
                                                                    [12 * mm, 14 * mm, 20 * mm, 30 * mm, 26 * mm, 26 * mm, 42 * mm])]
    if det["links"]:
        story += [Paragraph("Traceability", ss["Heading3"]), table([["Link", "Record", "Title", "Status", "Section"]] + [[x["link_type"], esc(x["target"]["key"]), Paragraph(esc(x["target"]["title"]), ss["BodyText"]), x["target"]["status"], esc(x["section"])] for x in det["links"]],
                                                          [22 * mm, 34 * mm, 64 * mm, 24 * mm, 26 * mm])]
    story += [Spacer(1, 8), Paragraph(f"Generated by ADA-ELM on {utcnow().strftime('%Y-%m-%d %H:%M UTC')} for {esc(ctx.user.full_name)}. Controlled copy only when printed from a released record.", ss["Italic"])]
    doc.build(story)
    ctx.audit("design.report", "design_record", d.id, f"{d.key} PDF report generated")
    ctx.db.commit()
    return Response(content=buf.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{d.key}.pdf"'})


@router.get("/designs/{did}/candidates")
def review_candidates(did: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    """People who can see the project and are not the owner, for the submit dialog."""
    d = _design(ctx, did)
    from app.services.authz import load_principal

    out = []
    for u in ctx.db.execute(select(User).where(User.is_active.is_(True)).order_by(User.full_name)).scalars():
        if u.id in (d.owner_id, ctx.user.id):
            continue
        if can_view_project(ctx.db, load_principal(ctx.db, u), d.project_id):
            out.append(user_brief(u))
    return out
