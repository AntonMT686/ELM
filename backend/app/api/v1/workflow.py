"""Action inbox (review / approve / sign) and workflow designer configuration API."""
from __future__ import annotations

import hashlib
import json
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select

from app.core.db import aware, utcnow
from app.core.deps import Ctx, get_ctx, get_or_404
from app.core.errors import AppError
from app.models import (
    Document,
    DocumentRevision,
    DocumentType,
    Role,
    User,
    WorkflowBinding,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowTask,
    WorkflowVersion,
)
from app.services import workflow_engine as wf
from app.services.serial import doc_dict, iso, user_brief
from app.services.workflow_spec import WorkflowSpec, validate_spec

router = APIRouter(tags=["workflow"])


# ------------------------------------------------------------------ inbox
def _task_dict(ctx: Ctx, t: WorkflowTask) -> dict:
    db = ctx.db
    inst = db.get(WorkflowInstance, t.instance_id)
    doc = db.get(Document, inst.document_id)
    rev = db.get(DocumentRevision, inst.revision_id)
    spec = wf.spec_of(db.get(WorkflowVersion, inst.version_id))
    stage = next((s for s in spec.stages if s.key == t.stage_key), None)
    idx = next((i for i, s in enumerate(spec.stages) if s.key == t.stage_key), 0)
    due = aware(t.due_at)
    return {
        "id": str(t.id), "status": t.status, "stage": {"key": t.stage_key, "name": stage.name if stage else t.stage_key, "type": stage.type if stage else None,
                                                       "checklist": stage.checklist if stage else [], "instructions": stage.instructions if stage else None,
                                                       "allow_reject": stage.allow_reject if stage else True, "index": idx, "count": len(spec.stages)},
        "stages": [{"key": s.key, "name": s.name, "type": s.type} for s in spec.stages],
        "document": doc_dict(db, doc), "revision": {"id": str(rev.id), "label": rev.label, "iteration": inst.iteration, "sha256": inst.revision_sha256, "ext": rev.file.extension if rev.file else None},
        "initiator": user_brief(db.get(User, inst.initiator_id)), "submitted_at": iso(inst.created_at), "cycle_no": inst.cycle_no,
        "due_at": iso(t.due_at), "overdue": bool(due and due < utcnow() and t.status == "PENDING"),
        "delegated_from": user_brief(db.get(User, t.assignee_id)) if t.assignee_id != ctx.user.id else None,
        "acted_at": iso(t.acted_at), "comment": t.decision_comment, "created_at": iso(t.created_at),
        "doc_checklist": _doc_checklist(db, inst, t, stage),
    }


def _doc_checklist(db, inst: WorkflowInstance, t: WorkflowTask, stage) -> dict:
    """The preparer's checklist items this stage must answer, and what earlier stages of this cycle answered."""
    from app.services import doc_checklist as dc

    all_items = dc.active(dc.items(db, inst.revision_id))
    mine = dc.applicable(all_items, t.stage_key) if stage and stage.type in ("review", "approval") else []
    others = [x.id for x in db.execute(select(WorkflowTask).where(WorkflowTask.instance_id == inst.id, WorkflowTask.id != t.id)).scalars()]
    earlier = dc.results_for_tasks(db, others)
    return {"items": [dc.item_dict(i) for i in mine], "all_items": len(all_items), "my_answers": dc.results_for_tasks(db, [t.id]).get(t.id, []),
            "earlier": [{"task_id": str(k), "answers": v} for k, v in earlier.items()]}


@router.get("/inbox")
def inbox(ctx: Ctx = Depends(get_ctx)):
    from app.models import Delegation

    now = utcnow()
    delegators = list(ctx.db.execute(select(Delegation.from_user_id).where(Delegation.to_user_id == ctx.user.id, Delegation.active.is_(True), Delegation.valid_from <= now, Delegation.valid_to >= now)).scalars())
    pending = ctx.db.execute(select(WorkflowTask).where(WorkflowTask.assignee_id.in_([ctx.user.id, *delegators]), WorkflowTask.status == "PENDING").order_by(WorkflowTask.due_at.is_(None), WorkflowTask.due_at, WorkflowTask.created_at)).scalars().all()
    done = ctx.db.execute(select(WorkflowTask).where(WorkflowTask.acted_by_id == ctx.user.id, WorkflowTask.status.in_(["APPROVED", "CHANGES_REQUESTED", "REJECTED", "SIGNED"])).order_by(WorkflowTask.acted_at.desc()).limit(30)).scalars().all()
    submitted = ctx.db.execute(select(WorkflowInstance).where(WorkflowInstance.initiator_id == ctx.user.id, WorkflowInstance.status == "ACTIVE").order_by(WorkflowInstance.created_at.desc())).scalars().all()
    return {
        "pending": [_task_dict(ctx, t) for t in pending],
        "completed": [_task_dict(ctx, t) for t in done if t.stage_key and not _is_prepare(ctx, t)],
        "submitted": [{"instance_id": str(i.id), "document": doc_dict(ctx.db, ctx.db.get(Document, i.document_id)), "current_stage_key": i.current_stage_key, "started_at": iso(i.created_at)} for i in submitted],
    }


def _is_prepare(ctx: Ctx, t: WorkflowTask) -> bool:
    inst = ctx.db.get(WorkflowInstance, t.instance_id)
    return wf.spec_of(ctx.db.get(WorkflowVersion, inst.version_id)).stages[0].key == t.stage_key


class DecisionIn(BaseModel):
    decision: str = Field(pattern=r"^(approve|request_changes|reject)$")
    comment: str | None = Field(default=None, max_length=5000)
    checklist: dict[str, bool] | None = None
    # answers to the preparer's checklist: {item_id: {"result": "OK" | "NOT_OK" | "NA", "remark": "..."}}
    item_results: dict[str, dict] | None = None


@router.post("/tasks/{tid}/decide")
def decide(tid: uuid.UUID, body: DecisionIn, ctx: Ctx = Depends(get_ctx)):
    inst = wf.decide(ctx.db, ctx.user, tid, body.decision, body.comment, body.checklist, body.item_results)
    ctx.db.commit()
    return {"instance_status": inst.status, "current_stage_key": inst.current_stage_key}


class SignIn(BaseModel):
    password: str = Field(min_length=1)
    comment: str | None = None


@router.post("/tasks/{tid}/sign")
def sign(tid: uuid.UUID, body: SignIn, ctx: Ctx = Depends(get_ctx)):
    rec = wf.sign(ctx.db, ctx.user, tid, body.password, body.comment)
    ctx.db.commit()
    return {"signature_id": str(rec.id), "serial": rec.certificate_serial}


class ReassignIn(BaseModel):
    user_id: uuid.UUID
    reason: str = Field(min_length=3)


@router.post("/tasks/{tid}/reassign")
def reassign(tid: uuid.UUID, body: ReassignIn, ctx: Ctx = Depends(get_ctx)):
    nt = wf.reassign(ctx.db, ctx.user, tid, body.user_id, body.reason)
    ctx.db.commit()
    return {"task_id": str(nt.id)}


# ------------------------------------------------------------------ designer
def _def_dict(ctx: Ctx, d: WorkflowDefinition, full: bool = False) -> dict:
    vers = ctx.db.execute(select(WorkflowVersion).where(WorkflowVersion.definition_id == d.id).order_by(WorkflowVersion.version_no.desc())).scalars().all()
    binds = ctx.db.execute(select(WorkflowBinding).where(WorkflowBinding.definition_id == d.id)).scalars().all()
    running = ctx.db.execute(select(func.count(WorkflowInstance.id)).join(WorkflowVersion, WorkflowVersion.id == WorkflowInstance.version_id).where(WorkflowVersion.definition_id == d.id, WorkflowInstance.status == "ACTIVE")).scalar()
    latest = vers[0] if vers else None
    out = {
        "id": str(d.id), "code": d.code, "name": d.name, "description": d.description, "category": d.category, "active": d.active,
        "latest_version": latest.version_no if latest else None, "published_at": iso(latest.published_at) if latest else None,
        "has_unpublished_changes": bool(d.draft_spec and (not latest or hashlib.sha256(d.draft_spec.encode()).hexdigest() != latest.spec_sha256)),
        "running_instances": running, "binding_count": len(binds),
        "stage_summary": [s.name for s in WorkflowSpec.model_validate_json(latest.spec).stages] if latest else [],
    }
    if full:
        types = {t.id: t for t in ctx.db.execute(select(DocumentType)).scalars()}
        out.update({
            "draft_spec": json.loads(d.draft_spec) if d.draft_spec else (json.loads(latest.spec) if latest else None),
            "versions": [{"id": str(v.id), "version_no": v.version_no, "status": v.status, "published_at": iso(v.published_at), "published_by": user_brief(ctx.db.get(User, v.published_by_id)) if v.published_by_id else None, "sha256": v.spec_sha256} for v in vers],
            "bindings": [{"id": str(b.id), "document_type": {"id": str(b.document_type_id), "name": types[b.document_type_id].name} if b.document_type_id in types else None,
                          "domain_id": str(b.domain_id) if b.domain_id else None, "project_id": str(b.project_id) if b.project_id else None,
                          "org_unit_id": str(b.org_unit_id) if b.org_unit_id else None, "level_code": b.level_code, "priority": b.priority, "active": b.active} for b in binds],
        })
    return out


@router.get("/workflow-definitions")
def list_definitions(ctx: Ctx = Depends(get_ctx)):
    return [_def_dict(ctx, d) for d in ctx.db.execute(select(WorkflowDefinition).order_by(WorkflowDefinition.name)).scalars()]


@router.get("/workflow-definitions/{wid}")
def get_definition(wid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    return _def_dict(ctx, get_or_404(ctx.db, WorkflowDefinition, wid, "Workflow"), full=True)


class DefIn(BaseModel):
    code: str = Field(pattern=r"^[A-Z0-9_-]{3,60}$")
    name: str = Field(min_length=3)
    description: str | None = None
    category: str = "DOCUMENT"
    copy_from_id: uuid.UUID | None = None


@router.post("/workflow-definitions")
def create_definition(body: DefIn, ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("workflow.configure")
    if ctx.db.execute(select(WorkflowDefinition.id).where(WorkflowDefinition.code == body.code)).first():
        raise AppError("Workflow code already exists.")
    spec = None
    if body.copy_from_id:
        src = get_or_404(ctx.db, WorkflowDefinition, body.copy_from_id, "Workflow")
        latest = ctx.db.execute(select(WorkflowVersion).where(WorkflowVersion.definition_id == src.id).order_by(WorkflowVersion.version_no.desc())).scalars().first()
        spec = src.draft_spec or (latest.spec if latest else None)
    if not spec:
        spec = json.dumps({"stages": [{"key": "prepare", "name": "Prepared By", "type": "prepare", "assignee": {"kind": "initiator"}, "weight": 10},
                                      {"key": "approve", "name": "Approved By", "type": "approval", "assignee": {"kind": "pick"}, "sod_exclude": ["prepare"], "weight": 90}]})
    d = WorkflowDefinition(code=body.code, name=body.name, description=body.description, category=body.category, draft_spec=spec, owner_id=ctx.user.id)
    ctx.db.add(d)
    ctx.audit("workflow.create", "workflow", body.code, f"Workflow {body.name} created")
    ctx.db.commit()
    return _def_dict(ctx, d)


def _parse(spec: dict) -> tuple[WorkflowSpec | None, list[str]]:
    try:
        s = WorkflowSpec.model_validate(spec)
    except ValidationError as e:
        return None, [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()]
    return s, []


@router.put("/workflow-definitions/{wid}/draft")
def save_draft(wid: uuid.UUID, spec: dict, ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("workflow.configure")
    d = get_or_404(ctx.db, WorkflowDefinition, wid, "Workflow")
    parsed, errs = _parse(spec)
    if parsed:
        roles = set(ctx.db.execute(select(Role.code)).scalars())
        errs = validate_spec(parsed, roles)
        d.draft_spec = parsed.model_dump_json()
    ctx.db.commit()
    return {"saved": parsed is not None, "errors": errs}


@router.post("/workflow-definitions/{wid}/publish")
def publish(wid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("workflow.configure")
    d = get_or_404(ctx.db, WorkflowDefinition, wid, "Workflow")
    if not d.draft_spec:
        raise AppError("Nothing to publish.")
    parsed, errs = _parse(json.loads(d.draft_spec))
    if parsed:
        errs = validate_spec(parsed, set(ctx.db.execute(select(Role.code)).scalars()))
    if errs:
        raise AppError("Workflow has validation errors.", code="WORKFLOW_INVALID", details={"errors": errs})
    text = parsed.model_dump_json()
    sha = hashlib.sha256(text.encode()).hexdigest()
    last = ctx.db.execute(select(WorkflowVersion).where(WorkflowVersion.definition_id == d.id).order_by(WorkflowVersion.version_no.desc())).scalars().first()
    if last and last.spec_sha256 == sha:
        raise AppError("No changes since the last published version.")
    v = WorkflowVersion(definition_id=d.id, version_no=(last.version_no + 1) if last else 1, spec=text, spec_sha256=sha, status="PUBLISHED", published_by_id=ctx.user.id, published_at=utcnow())
    if last:
        last.status = "RETIRED"  # existing instances remain pinned to it
    d.draft_spec = text
    ctx.db.add(v)
    ctx.audit("workflow.publish", "workflow", d.id, f"Published {d.name} v{v.version_no}", {"sha256": sha})
    ctx.db.commit()
    return {"version_no": v.version_no}


class BindingIn(BaseModel):
    document_type_id: uuid.UUID | None = None
    domain_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    org_unit_id: uuid.UUID | None = None
    level_code: str | None = None
    priority: int = 0


@router.post("/workflow-definitions/{wid}/bindings")
def add_binding(wid: uuid.UUID, body: BindingIn, ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("workflow.configure")
    d = get_or_404(ctx.db, WorkflowDefinition, wid, "Workflow")
    b = WorkflowBinding(definition_id=d.id, **body.model_dump())
    ctx.db.add(b)
    ctx.audit("workflow.bind", "workflow", d.id, f"Binding added to {d.name}", body.model_dump(mode="json"))
    ctx.db.commit()
    return {"id": str(b.id)}


@router.delete("/workflow-bindings/{bid}")
def remove_binding(bid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("workflow.configure")
    b = get_or_404(ctx.db, WorkflowBinding, bid, "Binding")
    b.active = False
    ctx.audit("workflow.unbind", "workflow", b.definition_id, "Binding deactivated")
    ctx.db.commit()
    return {"ok": True}
