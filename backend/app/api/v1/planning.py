"""Programme / project planning (architecture §9): plans, phases, milestones, work packages, activities, baselines,
overview and WBS, CSV import/export. Scope is enforced on every endpoint; every mutation is audited."""
from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.deps import Ctx, get_ctx, get_or_404
from app.core.errors import AppError, Conflict, Forbidden
from app.models import (
    EngineeringItem,
    Milestone,
    OrgUnit,
    PlanActivity,
    PlanBaseline,
    PlanPhase,
    ProcessDomain,
    Project,
    ProjectPlan,
    User,
    WorkItem,
    WorkItemEvent,
    WorkPackage,
    WorkPackageOrg,
)
from app.services import planning as svc
from app.services import task_lifecycle as lc
from app.services.notify import notify
from app.services.numbering import next_seq
from app.services.serial import iso, user_brief

router = APIRouter(tags=["planning"])

PRIORITIES = r"^(LOW|MEDIUM|HIGH|CRITICAL)$"
ACTIVITY_STATES = {"NOT_STARTED", "IN_PROGRESS", "COMPLETED", "ON_HOLD", "CANCELLED"}
MAX_CSV_BYTES = 2_000_000
CSV_FIELDS = ["key", "title", "kind", "status", "priority", "phase", "activity", "work_package", "assignee", "start_date", "due_date", "estimated_hours", "actual_hours", "progress", "predecessors", "legacy_key"]


def _require_plan_manage(ctx: Ctx, project_id: uuid.UUID, *, org_id: uuid.UUID | None = None, item_id: uuid.UUID | None = None) -> None:
    if not svc.can_manage_plan(ctx.db, ctx.p, project_id, org_id=org_id, item_id=item_id):
        raise Forbidden("You do not have planning permission in this scope.", details={"permission": "plan.manage"})


def _plan(ctx: Ctx, plan_id: uuid.UUID) -> ProjectPlan:
    plan = get_or_404(ctx.db, ProjectPlan, plan_id, "Plan")
    svc.require_view_project(ctx.db, ctx.p, plan.project_id)
    return plan


def _check_version(given: int | None, obj, what: str) -> None:
    if given is not None and given != obj.version:
        raise Conflict(f"This {what} was updated by someone else. Refresh and try again.")


def _dates(start: date | None, end: date | None) -> None:
    if start and end and end < start:
        raise AppError("The end date cannot be before the start date.")


# ------------------------------------------------------------------ plans
class PlanIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    version_label: str = Field(default="1.0", max_length=20)
    description: str | None = None
    owner_id: uuid.UUID | None = None


@router.get("/projects/{pid}/plans")
def list_plans(pid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    get_or_404(ctx.db, Project, pid, "Project")
    svc.require_view_project(ctx.db, ctx.p, pid)
    rows = ctx.db.execute(select(ProjectPlan).where(ProjectPlan.project_id == pid).order_by(ProjectPlan.created_at.desc())).scalars().all()
    return {"can_manage": svc.can_manage_plan(ctx.db, ctx.p, pid), "items": [svc.plan_dict(ctx.db, p) for p in rows]}


@router.post("/projects/{pid}/plans")
def create_plan(pid: uuid.UUID, body: PlanIn, ctx: Ctx = Depends(get_ctx)):
    project = get_or_404(ctx.db, Project, pid, "Project")
    _require_plan_manage(ctx, pid)
    plan = ProjectPlan(project_id=pid, created_by_id=ctx.user.id, owner_id=body.owner_id or ctx.user.id, name=body.name, version_label=body.version_label, description=body.description)
    ctx.db.add(plan)
    ctx.db.flush()
    ctx.audit("plan.create", "project_plan", plan.id, f"Plan {plan.name} created in {project.code}")
    ctx.db.commit()
    return svc.plan_dict(ctx.db, plan)


@router.get("/plans/{plan_id}")
def get_plan(plan_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    plan = _plan(ctx, plan_id)
    return {**svc.wbs(ctx.db, plan), "can_manage": svc.can_manage_plan(ctx.db, ctx.p, plan.project_id)}


@router.get("/plans/{plan_id}/overview")
def plan_overview(plan_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    return svc.overview(ctx.db, _plan(ctx, plan_id))


@router.put("/plans/{plan_id}")
def update_plan(plan_id: uuid.UUID, body: PlanIn, version: int | None = None, ctx: Ctx = Depends(get_ctx)):
    plan = _plan(ctx, plan_id)
    _require_plan_manage(ctx, plan.project_id)
    _check_version(version, plan, "plan")
    if plan.status == "ARCHIVED":
        raise AppError("An archived plan cannot be changed.")
    plan.name, plan.version_label, plan.description, plan.owner_id = body.name, body.version_label, body.description, body.owner_id
    plan.version += 1
    ctx.audit("plan.update", "project_plan", plan.id, f"Plan {plan.name} updated")
    ctx.db.commit()
    return svc.plan_dict(ctx.db, plan)


@router.post("/plans/{plan_id}/activate")
def activate_plan(plan_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    """Only one plan is active per project, so "project progress" has a single meaning. The previous one is archived, not removed."""
    plan = _plan(ctx, plan_id)
    _require_plan_manage(ctx, plan.project_id)
    if plan.status == "ACTIVE":
        return svc.plan_dict(ctx.db, plan)
    if plan.status == "ARCHIVED":
        raise AppError("An archived plan cannot be reactivated. Create a new plan version instead.")
    for other in ctx.db.execute(select(ProjectPlan).where(ProjectPlan.project_id == plan.project_id, ProjectPlan.status == "ACTIVE")).scalars():
        other.status = "ARCHIVED"
        other.version += 1
        ctx.audit("plan.archive", "project_plan", other.id, f"Plan {other.name} archived (replaced by {plan.name})")
    plan.status = "ACTIVE"
    plan.version += 1
    ctx.audit("plan.activate", "project_plan", plan.id, f"Plan {plan.name} activated")
    ctx.db.commit()
    return svc.plan_dict(ctx.db, plan)


# ------------------------------------------------------------------ phases
class PhaseIn(BaseModel):
    code: str = Field(pattern=r"^[A-Z0-9_]{2,40}$")
    name: str = Field(min_length=2, max_length=120)
    sort_order: int = 0
    weight: float = Field(default=1.0, ge=0)
    active: bool = True


@router.get("/projects/{pid}/phases")
def list_phases(pid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    svc.require_view_project(ctx.db, ctx.p, pid)
    return [{"id": str(f.id), "code": f.code, "name": f.name, "sort_order": f.sort_order, "weight": f.weight, "shared": f.project_id is None} for f in svc.phases_for(ctx.db, pid)]


@router.post("/projects/{pid}/phases")
def create_phase(pid: uuid.UUID, body: PhaseIn, ctx: Ctx = Depends(get_ctx)):
    """A project's first own phase replaces the shared template for that project (see PlanPhase)."""
    project = get_or_404(ctx.db, Project, pid, "Project")
    _require_plan_manage(ctx, pid)
    if ctx.db.execute(select(PlanPhase.id).where(PlanPhase.project_id == pid, PlanPhase.code == body.code)).first():
        raise Conflict("This phase code already exists in the project.")
    f = PlanPhase(project_id=pid, **body.model_dump())
    ctx.db.add(f)
    ctx.db.flush()
    ctx.audit("plan.phase.create", "plan_phase", f.id, f"Phase {f.code} added to {project.code}")
    ctx.db.commit()
    return {"id": str(f.id)}


@router.put("/phases/{phase_id}")
def update_phase(phase_id: uuid.UUID, body: PhaseIn, ctx: Ctx = Depends(get_ctx)):
    f = get_or_404(ctx.db, PlanPhase, phase_id, "Phase")
    if f.project_id:
        _require_plan_manage(ctx, f.project_id)
    else:
        ctx.p.require("workflow.configure")
    for k, v in body.model_dump().items():
        setattr(f, k, v)
    ctx.audit("plan.phase.update", "plan_phase", f.id, f"Phase {f.code} updated")
    ctx.db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ milestones
class MilestoneIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    code: str | None = Field(default=None, max_length=40)
    description: str | None = None
    plan_id: uuid.UUID | None = None
    start_date: date | None = None
    due_date: date | None = None
    achieved_date: date | None = None
    status: str = Field(default="PLANNED", pattern=r"^(PLANNED|IN_PROGRESS|ACHIEVED|CANCELLED)$")
    owner_id: uuid.UUID | None = None
    org_unit_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=2000)


@router.get("/projects/{pid}/milestones")
def list_milestones(pid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    svc.require_view_project(ctx.db, ctx.p, pid)
    rows = ctx.db.execute(select(Milestone).where(Milestone.project_id == pid).order_by(Milestone.due_date, Milestone.name)).scalars().all()
    return [svc.milestone_dict(ctx.db, m, None, date.today()) for m in rows]


def _milestone_gate(ctx: Ctx, m: Milestone) -> None:
    """A milestone is not achieved while tasks tied to it are open (architecture §9.4 and §17.2)."""
    states = lc.state_map(lc.get_lifecycle(ctx.db, m.project_id))
    blockers = [f"Task {t.key} is {states.get(t.status, {}).get('label', t.status)}." for t in ctx.db.execute(select(WorkItem).where(WorkItem.milestone_id == m.id)).scalars() if states.get(t.status, {}).get("category") not in ("DONE", "CANCELLED")]
    if blockers:
        raise AppError("This milestone cannot be marked achieved yet.", code="GATE_BLOCKED", details={"errors": blockers})


@router.post("/projects/{pid}/milestones")
def create_milestone(pid: uuid.UUID, body: MilestoneIn, ctx: Ctx = Depends(get_ctx)):
    project = get_or_404(ctx.db, Project, pid, "Project")
    _require_plan_manage(ctx, pid, org_id=body.org_unit_id, item_id=body.item_id)
    _dates(body.start_date, body.due_date)
    if body.plan_id and get_or_404(ctx.db, ProjectPlan, body.plan_id, "Plan").project_id != pid:
        raise AppError("The plan belongs to a different project.")
    m = Milestone(project_id=pid, **body.model_dump(exclude={"reason"}))
    ctx.db.add(m)
    ctx.db.flush()
    ctx.audit("milestone.create", "milestone", m.id, f"Milestone {m.name} added to {project.code}")
    ctx.db.commit()
    return svc.milestone_dict(ctx.db, m, None, date.today())


@router.put("/milestones/{mid}")
def update_milestone(mid: uuid.UUID, body: MilestoneIn, version: int | None = None, ctx: Ctx = Depends(get_ctx)):
    m = get_or_404(ctx.db, Milestone, mid, "Milestone")
    _require_plan_manage(ctx, m.project_id, org_id=m.org_unit_id, item_id=m.item_id)
    _check_version(version, m, "milestone")
    _dates(body.start_date, body.due_date)
    if body.status == "ACHIEVED" and m.status != "ACHIEVED":
        _milestone_gate(ctx, m)
        body.achieved_date = body.achieved_date or date.today()
    date_moved = m.due_date != body.due_date
    if date_moved and m.due_date and not (body.reason or "").strip():
        raise AppError("A reason is required to move a milestone's due date.", code="REASON_REQUIRED")
    before = {"due_date": iso(m.due_date), "status": m.status}
    for k, v in body.model_dump(exclude={"reason"}).items():
        setattr(m, k, v)
    m.version += 1
    ctx.audit("milestone.update", "milestone", m.id, f"Milestone {m.name} updated", {"before": before, "after": {"due_date": iso(m.due_date), "status": m.status}, "reason": body.reason})
    ctx.db.commit()
    return svc.milestone_dict(ctx.db, m, None, date.today())


# ------------------------------------------------------------------ work packages
class WorkPackageIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None
    domain_id: uuid.UUID | None = None
    lead_org_unit_id: uuid.UUID | None = None
    contributor_org_ids: list[uuid.UUID] = Field(default_factory=list)
    item_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str = Field(default="ACTIVE", pattern=r"^(ACTIVE|ON_HOLD|CLOSED)$")
    sort_order: int = 0


def _validate_package(ctx: Ctx, plan: ProjectPlan, body: WorkPackageIn) -> None:
    _dates(body.start_date, body.end_date)
    if body.item_id and get_or_404(ctx.db, EngineeringItem, body.item_id, "Item").project_id != plan.project_id:
        raise AppError("The engineering item belongs to a different project.")
    if body.domain_id:
        get_or_404(ctx.db, ProcessDomain, body.domain_id, "Process domain")
    for oid in [body.lead_org_unit_id, *body.contributor_org_ids]:
        if oid:
            get_or_404(ctx.db, OrgUnit, oid, "Organization unit")


def _set_contributors(ctx: Ctx, wp: WorkPackage, ids: list[uuid.UUID]) -> None:
    for row in ctx.db.execute(select(WorkPackageOrg).where(WorkPackageOrg.work_package_id == wp.id)).scalars():
        ctx.db.delete(row)
    ctx.db.flush()
    for oid in set(ids) - {wp.lead_org_unit_id}:
        ctx.db.add(WorkPackageOrg(work_package_id=wp.id, org_unit_id=oid))


@router.post("/plans/{plan_id}/work-packages")
def create_work_package(plan_id: uuid.UUID, body: WorkPackageIn, ctx: Ctx = Depends(get_ctx)):
    plan = _plan(ctx, plan_id)
    _require_plan_manage(ctx, plan.project_id, org_id=body.lead_org_unit_id, item_id=body.item_id)
    _validate_package(ctx, plan, body)
    if ctx.db.execute(select(WorkPackage.id).where(WorkPackage.plan_id == plan.id, WorkPackage.code == body.code)).first():
        raise Conflict(f"Work package code {body.code} already exists in this plan.")
    wp = WorkPackage(plan_id=plan.id, project_id=plan.project_id, **body.model_dump(exclude={"contributor_org_ids"}))
    ctx.db.add(wp)
    ctx.db.flush()
    _set_contributors(ctx, wp, body.contributor_org_ids)
    ctx.audit("plan.wp.create", "work_package", wp.id, f"Work package {wp.code} added to plan {plan.name}")
    ctx.db.commit()
    return {"id": str(wp.id)}


@router.put("/work-packages/{wid}")
def update_work_package(wid: uuid.UUID, body: WorkPackageIn, version: int | None = None, ctx: Ctx = Depends(get_ctx)):
    wp = get_or_404(ctx.db, WorkPackage, wid, "Work package")
    plan = _plan(ctx, wp.plan_id)
    _require_plan_manage(ctx, plan.project_id, org_id=wp.lead_org_unit_id, item_id=wp.item_id)
    _check_version(version, wp, "work package")
    _validate_package(ctx, plan, body)
    for k, v in body.model_dump(exclude={"contributor_org_ids"}).items():
        setattr(wp, k, v)
    wp.version += 1
    _set_contributors(ctx, wp, body.contributor_org_ids)
    ctx.audit("plan.wp.update", "work_package", wp.id, f"Work package {wp.code} updated")
    ctx.db.commit()
    return {"ok": True}


@router.delete("/work-packages/{wid}")
def delete_work_package(wid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    wp = get_or_404(ctx.db, WorkPackage, wid, "Work package")
    _require_plan_manage(ctx, wp.project_id, org_id=wp.lead_org_unit_id, item_id=wp.item_id)
    if ctx.db.execute(select(PlanActivity.id).where(PlanActivity.work_package_id == wp.id)).first() or ctx.db.execute(select(WorkItem.id).where(WorkItem.work_package_id == wp.id)).first():
        raise Conflict("This work package still has activities or tasks. Move them first.")
    for row in ctx.db.execute(select(WorkPackageOrg).where(WorkPackageOrg.work_package_id == wp.id)).scalars():
        ctx.db.delete(row)
    ctx.audit("plan.wp.delete", "work_package", wp.id, f"Work package {wp.code} removed")
    ctx.db.delete(wp)
    ctx.db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ activities
class ActivityIn(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    description: str | None = None
    work_package_id: uuid.UUID | None = None
    phase_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    estimated_hours: float = Field(default=0, ge=0)
    priority: str = Field(default="MEDIUM", pattern=PRIORITIES)
    weight: float | None = Field(default=None, ge=0)
    status: str = "NOT_STARTED"
    sort_order: int = 0


def _validate_activity(ctx: Ctx, plan: ProjectPlan, body: ActivityIn) -> WorkPackage | None:
    _dates(body.start_date, body.end_date)
    if body.status not in ACTIVITY_STATES:
        raise AppError(f"Unknown activity status {body.status}.")
    if body.phase_id:
        phase = get_or_404(ctx.db, PlanPhase, body.phase_id, "Phase")
        if phase.project_id not in (None, plan.project_id):
            raise AppError("The phase belongs to a different project.")
    if body.work_package_id:
        wp = get_or_404(ctx.db, WorkPackage, body.work_package_id, "Work package")
        if wp.plan_id != plan.id:
            raise AppError("The work package belongs to a different plan.")
        return wp
    return None


@router.post("/plans/{plan_id}/activities")
def create_activity(plan_id: uuid.UUID, body: ActivityIn, ctx: Ctx = Depends(get_ctx)):
    plan = _plan(ctx, plan_id)
    wp = _validate_activity(ctx, plan, body)
    _require_plan_manage(ctx, plan.project_id, org_id=wp.lead_org_unit_id if wp else None, item_id=wp.item_id if wp else None)
    a = PlanActivity(plan_id=plan.id, project_id=plan.project_id, **body.model_dump())
    ctx.db.add(a)
    ctx.db.flush()
    if a.owner_id and a.owner_id != ctx.user.id:
        notify(ctx.db, a.owner_id, "plan.activity", f"You own a new activity: {a.title}", f"Plan {plan.name}", link=f"/planning/{plan.project_id}?plan={plan.id}")
    ctx.audit("plan.activity.create", "plan_activity", a.id, f"Activity {a.title} added to plan {plan.name}")
    ctx.db.commit()
    return {"id": str(a.id)}


@router.put("/activities/{aid}")
def update_activity(aid: uuid.UUID, body: ActivityIn, version: int | None = None, ctx: Ctx = Depends(get_ctx)):
    a = get_or_404(ctx.db, PlanActivity, aid, "Activity")
    plan = _plan(ctx, a.plan_id)
    current_wp = ctx.db.get(WorkPackage, a.work_package_id) if a.work_package_id else None
    _require_plan_manage(ctx, plan.project_id, org_id=current_wp.lead_org_unit_id if current_wp else None, item_id=current_wp.item_id if current_wp else None)
    _check_version(version, a, "activity")
    _validate_activity(ctx, plan, body)
    if body.status == "COMPLETED" and a.status != "COMPLETED":
        states = lc.state_map(lc.get_lifecycle(ctx.db, plan.project_id))
        blockers = [f"Task {t.key} is {states.get(t.status, {}).get('label', t.status)}." for t in ctx.db.execute(select(WorkItem).where(WorkItem.activity_id == a.id)).scalars() if states.get(t.status, {}).get("category") not in ("DONE", "CANCELLED")]
        if blockers:
            raise AppError("This activity cannot be completed yet.", code="GATE_BLOCKED", details={"errors": blockers})
    old = a.status
    for k, v in body.model_dump().items():
        setattr(a, k, v)
    a.version += 1
    ctx.audit("plan.activity.update", "plan_activity", a.id, f"Activity {a.title} updated", {"status": [old, a.status]})
    ctx.db.commit()
    return {"ok": True}


@router.delete("/activities/{aid}")
def delete_activity(aid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    a = get_or_404(ctx.db, PlanActivity, aid, "Activity")
    _require_plan_manage(ctx, a.project_id)
    if ctx.db.execute(select(WorkItem.id).where(WorkItem.activity_id == a.id)).first():
        raise Conflict("This activity still has tasks. Move or cancel them first.")
    ctx.audit("plan.activity.delete", "plan_activity", a.id, f"Activity {a.title} removed")
    ctx.db.delete(a)
    ctx.db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ baselines
class BaselineIn(BaseModel):
    label: str = Field(min_length=2, max_length=120)
    reason: str = Field(min_length=3, max_length=4000)


@router.get("/plans/{plan_id}/baselines")
def list_baselines(plan_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    plan = _plan(ctx, plan_id)
    rows = ctx.db.execute(select(PlanBaseline).where(PlanBaseline.plan_id == plan.id).order_by(PlanBaseline.seq.desc())).scalars().all()
    return [{"id": str(b.id), "seq": b.seq, "label": b.label, "reason": b.reason, "sha256": b.sha256, "created_at": iso(b.created_at), "created_by": user_brief(ctx.db.get(User, b.created_by_id)) if b.created_by_id else None} for b in rows]


@router.post("/plans/{plan_id}/baselines")
def create_baseline(plan_id: uuid.UUID, body: BaselineIn, ctx: Ctx = Depends(get_ctx)):
    plan = _plan(ctx, plan_id)
    _require_plan_manage(ctx, plan.project_id)
    seq = (ctx.db.execute(select(func.max(PlanBaseline.seq)).where(PlanBaseline.plan_id == plan.id)).scalar() or 0) + 1
    text, digest = svc.seal(svc.snapshot(ctx.db, plan))
    b = PlanBaseline(plan_id=plan.id, seq=seq, label=body.label, reason=body.reason, snapshot=text, sha256=digest, created_by_id=ctx.user.id)
    ctx.db.add(b)
    ctx.db.flush()
    ctx.audit("plan.baseline", "plan_baseline", b.id, f"Baseline {seq} ({body.label}) captured for plan {plan.name}", {"sha256": digest, "reason": body.reason})
    ctx.db.commit()
    return {"id": str(b.id), "seq": seq, "sha256": digest}


@router.get("/baselines/{bid}/compare")
def compare_baseline(bid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    b = get_or_404(ctx.db, PlanBaseline, bid, "Baseline")
    return svc.compare_baseline(ctx.db, _plan(ctx, b.plan_id), b)


# ------------------------------------------------------------------ CSV export / import
def _safe_cell(v):
    """Spreadsheets run cells that start with these characters as formulas, so neutralise them on export."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


@router.get("/plans/{plan_id}/export.csv")
def export_plan(plan_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    plan = _plan(ctx, plan_id)
    d = svc.PlanData(ctx.db, plan)
    users = d.users({t.assignee_id for t in d.tasks})
    acts = {a.id: a for a in d.activities}
    wps = {w.id: w for w in d.packages}
    phases = {f.id: f.name for f in d.phases}
    keys = {t.id: t.key for t in d.tasks}
    preds: dict[uuid.UUID, list[str]] = {}
    for x in d.deps:
        if x.predecessor_id in keys:
            preds.setdefault(x.successor_id, []).append(f"{keys[x.predecessor_id]}:{x.dep_type}{x.lag_days:+d}")
    buf = io.StringIO()
    out = csv.writer(buf)
    out.writerow(CSV_FIELDS)
    for t in d.tasks:
        a = acts.get(t.activity_id)
        wp = wps.get(t.work_package_id)
        u = users.get(t.assignee_id)
        out.writerow([_safe_cell(x) for x in [t.key, t.title, t.kind, t.status, t.priority, phases.get(a.phase_id) if a else "", a.title if a else "", wp.code if wp else "", u.username if u else "",
                                              iso(t.start_date), iso(t.due_date), t.estimated_hours, t.actual_hours, t.progress, " ".join(preds.get(t.id, [])), t.legacy_key]])
    ctx.audit("plan.export", "project_plan", plan.id, f"Plan {plan.name} exported to CSV", {"rows": len(d.tasks)})
    ctx.db.commit()
    filename = f"plan-{d.project.code}-{plan.version_label}.csv".replace(" ", "_")
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _parse_date(raw: str, field: str, errors: list[str]) -> date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        errors.append(f"{field} must be YYYY-MM-DD.")
        return None


@router.post("/plans/{plan_id}/import")
def import_plan_csv(plan_id: uuid.UUID, file: UploadFile = File(...), dry_run: bool = Query(True), ctx: Ctx = Depends(get_ctx)):
    """Validate a CSV of new tasks. dry_run=true (the default) only reports. Nothing is written if any row fails."""
    plan = _plan(ctx, plan_id)
    _require_plan_manage(ctx, plan.project_id)
    raw = file.file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise AppError("The CSV file is too large (limit 2 MB).")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise AppError("The file must be UTF-8 encoded CSV.") from None
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "title" not in [f.strip() for f in reader.fieldnames]:
        raise AppError("The CSV must have a header row with at least a 'title' column.", details={"errors": [f"Expected columns: {', '.join(CSV_FIELDS)}"]})
    d = svc.PlanData(ctx.db, plan)
    acts = {a.title.lower(): a for a in d.activities}
    wps = {w.code.lower(): w for w in d.packages}
    life = lc.get_lifecycle(ctx.db, plan.project_id)
    rows, problems = [], []
    for n, rec in enumerate(reader, 2):
        rec = {(k or "").strip(): (v or "").strip() for k, v in rec.items() if isinstance(v, str)}
        errs: list[str] = []
        if (rec.get("key") or "") and rec.get("key") in {t.key for t in d.tasks}:
            problems.append({"row": n, "errors": [f"Task {rec['key']} already exists; import adds new tasks only."]})
            continue
        title = rec.get("title", "")
        if not 3 <= len(title) <= 300:
            errs.append("title must be 3 to 300 characters.")
        priority = (rec.get("priority") or "MEDIUM").upper()
        if priority not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            errs.append(f"priority {priority} is not valid.")
        kind = (rec.get("kind") or "TASK").upper()
        if kind not in ("TASK", "ACTION", "MILESTONE", "CHANGE_REQUEST", "ISSUE"):
            errs.append(f"kind {kind} is not valid.")
        activity = acts.get(rec.get("activity", "").lower()) if rec.get("activity") else None
        if rec.get("activity") and not activity:
            errs.append(f"activity '{rec['activity']}' is not in this plan.")
        wp = wps.get(rec.get("work_package", "").lower()) if rec.get("work_package") else None
        if rec.get("work_package") and not wp:
            errs.append(f"work package '{rec['work_package']}' is not in this plan.")
        assignee = None
        if rec.get("assignee"):
            assignee = ctx.db.execute(select(User).where(func.lower(User.username) == rec["assignee"].lower())).scalar_one_or_none()
            if not assignee or not assignee.is_active:
                errs.append(f"assignee '{rec['assignee']}' is not an active user.")
        start = _parse_date(rec.get("start_date", ""), "start_date", errs)
        due = _parse_date(rec.get("due_date", ""), "due_date", errs)
        if start and due and due < start:
            errs.append("due_date is before start_date.")
        try:
            hours = float(rec.get("estimated_hours") or 0)
            if hours < 0:
                raise ValueError
        except ValueError:
            errs.append("estimated_hours must be a positive number.")
            hours = 0.0
        if errs:
            problems.append({"row": n, "errors": errs})
        else:
            rows.append({"title": title, "priority": priority, "kind": kind, "activity": activity, "wp": wp or (ctx.db.get(WorkPackage, activity.work_package_id) if activity and activity.work_package_id else None), "assignee": assignee, "start": start, "due": due, "hours": hours})
    if dry_run or problems:
        return {"dry_run": True, "would_create": len(rows) if not problems else 0, "valid_rows": len(rows), "errors": problems, "committed": False}
    for r in rows:
        key = f"{d.project.code}-{next_seq(ctx.db, 'wi:' + d.project.code)}"
        w = WorkItem(key=key, title=r["title"], kind=r["kind"], priority=r["priority"], status=lc.initial_state(life), project_id=plan.project_id, plan_id=plan.id, activity_id=r["activity"].id if r["activity"] else None,
                     work_package_id=r["wp"].id if r["wp"] else None, assignee_id=r["assignee"].id if r["assignee"] else None, reporter_id=ctx.user.id, start_date=r["start"], due_date=r["due"], estimated_hours=r["hours"])
        ctx.db.add(w)
        ctx.db.flush()
        ctx.db.add(WorkItemEvent(work_item_id=w.id, actor_id=ctx.user.id, kind="CREATED", to_value=w.status, comment="Imported from CSV"))
    ctx.audit("plan.import", "project_plan", plan.id, f"{len(rows)} task(s) imported from CSV into plan {plan.name}", {"filename": file.filename})
    ctx.db.commit()
    return {"dry_run": False, "would_create": len(rows), "valid_rows": len(rows), "errors": [], "committed": True, "created": len(rows)}


# ------------------------------------------------------------------ portfolio
@router.get("/planning/portfolio")
def portfolio(ctx: Ctx = Depends(get_ctx)):
    """One row per visible project with its active plan's roll-up. Scope-filtered, so no count leaks between directorates."""
    q = select(Project).order_by(Project.code)
    ids = svc.visible_project_ids(ctx.db, ctx.p)
    if ids is not None:
        if not ids:
            return []
        q = q.where(Project.id.in_(ids))
    out = []
    for p in ctx.db.execute(q).scalars():
        plans = ctx.db.execute(select(ProjectPlan).where(ProjectPlan.project_id == p.id).order_by(ProjectPlan.created_at.desc())).scalars().all()
        active = next((x for x in plans if x.status == "ACTIVE"), None) or next((x for x in plans if x.status == "DRAFT"), None)
        row = {"project": {"id": str(p.id), "code": p.code, "name": p.name, "status": p.status, "color": p.color, "start_date": iso(p.start_date), "end_date": iso(p.end_date)}, "plan_count": len(plans), "can_manage": svc.can_manage_plan(ctx.db, ctx.p, p.id), "plan": None}
        if active:
            ov = svc.overview(ctx.db, active)
            row["plan"] = {"id": str(active.id), "name": active.name, "status": active.status, "version_label": active.version_label, "progress": ov["progress"], "fully_complete": ov["fully_complete"], "tasks": ov["tasks"]["total"], "overdue": ov["tasks"]["overdue"], "open_gates": len(ov["open_gates"]),
                           "next_milestone": next(({"name": m["name"], "due_date": m["due_date"], "late": m["late"]} for m in ov["milestones"] if m["status"] not in ("ACHIEVED", "CANCELLED")), None)}
        out.append(row)
    return out


@router.get("/settings/planning-config")
def planning_config(ctx: Ctx = Depends(get_ctx)):
    """Shared phases, for the admin screen."""
    rows = ctx.db.execute(select(PlanPhase).where(PlanPhase.project_id.is_(None)).order_by(PlanPhase.sort_order)).scalars().all()
    return {"phases": [{"id": str(f.id), "code": f.code, "name": f.name, "sort_order": f.sort_order, "weight": f.weight, "active": f.active} for f in rows], "statuses": lc.get_lifecycle(ctx.db)["states"]}
