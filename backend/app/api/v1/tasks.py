"""Tasks / work items (architecture §9.3–9.4): scoped access, validated transitions, dependencies, participants,
checklist, deliverables, comments and history. Every mutation is audited in the same transaction."""
from __future__ import annotations

import json
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.core.db import utcnow
from app.core.deps import Ctx, get_ctx, get_or_404
from app.core.errors import AppError, Conflict, Forbidden
from app.models import (
    Document,
    EngineeringItem,
    PlanActivity,
    Project,
    ProjectPlan,
    Requirement,
    RequirementWorkItem,
    SystemSetting,
    TaskChecklistItem,
    TaskComment,
    TaskDeliverable,
    TaskDependency,
    TaskParticipant,
    User,
    WorkItem,
    WorkItemEvent,
    WorkPackage,
)
from app.services import task_lifecycle as lc
from app.services.authz import can_view_document
from app.services.notify import notify
from app.services.numbering import next_seq
from app.services.planning import can_manage_task, can_view_project, can_view_task, require_view_project, task_visibility_clause
from app.services.requirements import can_view as can_view_requirement
from app.services.serial import iso, user_brief

router = APIRouter(tags=["tasks"])

KINDS = r"^(TASK|ACTION|MILESTONE|CHANGE_REQUEST|ISSUE)$"
PRIORITIES = r"^(LOW|MEDIUM|HIGH|CRITICAL)$"


class WorkItemIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    description: str | None = None
    kind: str = Field(default="TASK", pattern=KINDS)
    priority: str = Field(default="MEDIUM", pattern=PRIORITIES)
    project_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    org_unit_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    assignee_id: uuid.UUID | None = None
    plan_id: uuid.UUID | None = None
    work_package_id: uuid.UUID | None = None
    activity_id: uuid.UUID | None = None
    milestone_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    start_date: date | None = None
    due_date: date | None = None
    estimated_hours: float = Field(default=0, ge=0)
    actual_hours: float = Field(default=0, ge=0)
    weight: float | None = Field(default=None, ge=0)
    reported_progress: float = Field(default=0, ge=0, le=100)


class TransitionIn(BaseModel):
    to: str = Field(min_length=1, max_length=30)
    comment: str | None = Field(default=None, max_length=4000)


class DependencyIn(BaseModel):
    predecessor_id: uuid.UUID
    type: str = Field(default="FS", pattern=r"^(FS|SS|FF|SF)$")
    lag_days: int = Field(default=0, ge=-365, le=3650)


class ParticipantsIn(BaseModel):
    contributors: list[uuid.UUID] = Field(default_factory=list)
    reviewers: list[uuid.UUID] = Field(default_factory=list)


class ChecklistIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    mandatory: bool = True


class ChecklistPatch(BaseModel):
    done: bool | None = None
    text: str | None = Field(default=None, min_length=1, max_length=500)
    mandatory: bool | None = None


class DeliverableIn(BaseModel):
    document_id: uuid.UUID
    required_status: str = Field(default="RELEASED", pattern=r"^(APPROVED|RELEASED)$")
    mandatory: bool = True


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=8000)


def _brief(ctx: Ctx, w: WorkItem) -> dict:
    db = ctx.db
    p = db.get(Project, w.project_id) if w.project_id else None
    it = db.get(EngineeringItem, w.item_id) if w.item_id else None
    d = db.get(Document, w.document_id) if w.document_id else None
    a = db.get(PlanActivity, w.activity_id) if w.activity_id else None
    wp = db.get(WorkPackage, w.work_package_id) if w.work_package_id else None
    plan = db.get(ProjectPlan, w.plan_id) if w.plan_id else None
    return {"id": str(w.id), "key": w.key, "title": w.title, "description": w.description, "kind": w.kind, "status": w.status, "priority": w.priority,
            "project": {"id": str(p.id), "code": p.code} if p else None, "item": {"id": str(it.id), "code": it.code, "name": it.name} if it else None,
            "document": {"id": str(d.id), "number": d.number} if d else None, "org_unit_id": str(w.org_unit_id) if w.org_unit_id else None,
            "plan": {"id": str(plan.id), "name": plan.name} if plan else None, "work_package": {"id": str(wp.id), "code": wp.code, "name": wp.name} if wp else None,
            "activity": {"id": str(a.id), "title": a.title} if a else None, "milestone_id": str(w.milestone_id) if w.milestone_id else None, "parent_id": str(w.parent_id) if w.parent_id else None,
            "assignee": user_brief(db.get(User, w.assignee_id)) if w.assignee_id else None, "reporter": user_brief(db.get(User, w.reporter_id)) if w.reporter_id else None,
            "start_date": iso(w.start_date), "due_date": iso(w.due_date), "actual_start": iso(w.actual_start), "actual_end": iso(w.actual_end),
            "progress": w.progress, "reported_progress": w.reported_progress, "estimated_hours": w.estimated_hours, "actual_hours": w.actual_hours, "weight": w.weight,
            "legacy_key": w.legacy_key, "legacy_type": w.legacy_type, "version": w.version, "updated_at": iso(w.updated_at), "completed_at": iso(w.completed_at)}


def _detail(ctx: Ctx, w: WorkItem) -> dict:
    db = ctx.db
    manager = can_manage_task(db, ctx.p, w)
    parts = db.execute(select(TaskParticipant, User).join(User, User.id == TaskParticipant.user_id).where(TaskParticipant.work_item_id == w.id)).all()
    preds = db.execute(select(TaskDependency, WorkItem).join(WorkItem, WorkItem.id == TaskDependency.predecessor_id).where(TaskDependency.successor_id == w.id)).all()
    succs = db.execute(select(TaskDependency, WorkItem).join(WorkItem, WorkItem.id == TaskDependency.successor_id).where(TaskDependency.predecessor_id == w.id)).all()
    checklist = db.execute(select(TaskChecklistItem).where(TaskChecklistItem.work_item_id == w.id).order_by(TaskChecklistItem.sort_order, TaskChecklistItem.created_at)).scalars().all()
    deliverables = db.execute(select(TaskDeliverable, Document).join(Document, Document.id == TaskDeliverable.document_id).where(TaskDeliverable.work_item_id == w.id)).all()
    children = db.execute(select(WorkItem).where(WorkItem.parent_id == w.id).order_by(WorkItem.key)).scalars().all()
    comments = db.execute(select(TaskComment).where(TaskComment.work_item_id == w.id).order_by(TaskComment.created_at)).scalars().all()
    events = db.execute(select(WorkItemEvent).where(WorkItemEvent.work_item_id == w.id).order_by(WorkItemEvent.at)).scalars().all()
    users = {u.id: u for u in db.execute(select(User).where(User.id.in_({c.author_id for c in comments} | {e.actor_id for e in events} | {uuid.uuid4()}))).scalars()}

    def dep_row(x: TaskDependency, other: WorkItem) -> dict:
        return {"id": str(x.id), "task": {"id": str(other.id), "key": other.key, "title": other.title, "status": other.status, "org_unit_id": str(other.org_unit_id) if other.org_unit_id else None,
                                          "assignee": user_brief(db.get(User, other.assignee_id)) if other.assignee_id else None}, "type": x.dep_type, "lag_days": x.lag_days,
                "cross_directorate": bool(w.org_unit_id and other.org_unit_id and w.org_unit_id != other.org_unit_id)}

    return {
        **_brief(ctx, w),
        "can_edit": manager or ctx.user.id in (w.assignee_id, w.reporter_id),
        "can_manage": manager,
        "transitions": lc.available_transitions(db, w, ctx.user.id, manager),
        "completion_blockers": lc.completion_blockers(db, w, lc.get_lifecycle(db, w.project_id)),
        "contributors": [user_brief(u) for p, u in parts if p.role == "CONTRIBUTOR"],
        "reviewers": [user_brief(u) for p, u in parts if p.role == "REVIEWER"],
        "predecessors": [dep_row(x, o) for x, o in preds],
        "successors": [dep_row(x, o) for x, o in succs],
        "checklist": [{"id": str(i.id), "text": i.text, "mandatory": i.mandatory, "done": i.done, "done_at": iso(i.done_at), "done_by": user_brief(db.get(User, i.done_by_id)) if i.done_by_id else None} for i in checklist],
        "deliverables": [{"id": str(x.id), "document": {"id": str(d.id), "number": d.number, "title": d.title, "status": d.status}, "required_status": x.required_status, "mandatory": x.mandatory} for x, d in deliverables],
        "children": [{"id": str(c.id), "key": c.key, "title": c.title, "status": c.status, "progress": c.progress, "assignee": user_brief(db.get(User, c.assignee_id)) if c.assignee_id else None} for c in children],
        "comments": [{"id": str(c.id), "body": c.body, "created_at": iso(c.created_at), "author": user_brief(users.get(c.author_id))} for c in comments],
        "requirements": [{"id": str(r.id), "key": r.key, "title": r.title, "status": r.status, "project_id": str(r.project_id), "link_type": x.link_type} for x, r in db.execute(select(RequirementWorkItem, Requirement).join(Requirement, Requirement.id == RequirementWorkItem.requirement_id).where(RequirementWorkItem.work_item_id == w.id)).all() if can_view_requirement(db, ctx.p, r)],
        "history": [{"id": str(e.id), "kind": e.kind, "from": e.from_value, "to": e.to_value, "comment": e.comment, "at": iso(e.at), "actor": user_brief(users.get(e.actor_id))} for e in events],
    }


# ------------------------------------------------------------------ lifecycle configuration
@router.get("/task-lifecycle")
def get_task_lifecycle(project_id: uuid.UUID | None = None, ctx: Ctx = Depends(get_ctx)):
    if project_id:
        require_view_project(ctx.db, ctx.p, project_id)
    return {**lc.get_lifecycle(ctx.db, project_id), "completion_rules": lc.get_rules(ctx.db), "default": lc.DEFAULT_LIFECYCLE}


class LifecycleIn(BaseModel):
    states: list[dict]
    transitions: list[dict]
    completion_rules: dict[str, bool] | None = None


@router.put("/task-lifecycle")
def set_task_lifecycle(body: LifecycleIn, project_id: uuid.UUID | None = None, ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("workflow.configure")
    new = {"states": body.states, "transitions": body.transitions}
    errors = lc.validate_lifecycle(new)
    codes = {s.get("code") for s in body.states}
    q = select(WorkItem.status).distinct()
    if project_id:
        q = q.where(WorkItem.project_id == project_id)
    else:
        # the shared lifecycle governs every project that has no override of its own
        overridden = [uuid.UUID(k.rsplit(".", 1)[1]) for k in ctx.db.execute(select(SystemSetting.key).where(SystemSetting.key.like("task.lifecycle.%"))).scalars()]
        if overridden:
            q = q.where(or_(WorkItem.project_id.is_(None), WorkItem.project_id.not_in(overridden)))
    used = set(ctx.db.execute(q).scalars())
    for code in sorted(used - codes):
        errors.append(f"State {code} cannot be removed because tasks are using it.")
    if errors:
        raise AppError("The task lifecycle is not valid.", code="LIFECYCLE_INVALID", details={"errors": errors})
    key = f"task.lifecycle.{project_id}" if project_id else "task.lifecycle"
    row = ctx.db.get(SystemSetting, key)
    if row:
        row.value = json.dumps(new)
    else:
        ctx.db.add(SystemSetting(key=key, value=json.dumps(new), description="Task lifecycle (states and transitions)"))
    if body.completion_rules is not None:
        unknown = set(body.completion_rules) - set(lc.DEFAULT_RULES)
        if unknown:
            raise AppError(f"Unknown completion rule: {', '.join(sorted(unknown))}.")
        rules = ctx.db.get(SystemSetting, "task.completion_rules")
        if rules:
            rules.value = json.dumps(body.completion_rules)
        else:
            ctx.db.add(SystemSetting(key="task.completion_rules", value=json.dumps(body.completion_rules), description="Gates checked before a task can be completed"))
    ctx.audit("task.lifecycle.update", "system_setting", None, f"Task lifecycle updated ({key})", {"states": sorted(codes), "transitions": len(body.transitions), "rules": body.completion_rules})
    ctx.db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ list / read
@router.get("/work-items")
def list_work_items(mine: bool = False, project_id: uuid.UUID | None = None, item_id: uuid.UUID | None = None, plan_id: uuid.UUID | None = None, activity_id: uuid.UUID | None = None,
                    status: str | None = None, overdue: bool = False, limit: int = Query(500, le=1000), ctx: Ctx = Depends(get_ctx)):
    q = select(WorkItem)
    if mine:
        q = q.where(or_(WorkItem.assignee_id == ctx.user.id, WorkItem.reporter_id == ctx.user.id, WorkItem.id.in_(select(TaskParticipant.work_item_id).where(TaskParticipant.user_id == ctx.user.id))))
    else:
        vis = task_visibility_clause(ctx.db, ctx.p)
        if vis is not None:
            q = q.where(vis)
    if project_id:
        q = q.where(WorkItem.project_id == project_id)
    if item_id:
        q = q.where(WorkItem.item_id == item_id)
    if plan_id:
        q = q.where(WorkItem.plan_id == plan_id)
    if activity_id:
        q = q.where(WorkItem.activity_id == activity_id)
    if status:
        q = q.where(WorkItem.status.in_(status.split(",")))
    if overdue:
        q = q.where(WorkItem.due_date < date.today(), WorkItem.status.not_in(lc.closed_statuses(ctx.db)))
    rows = ctx.db.execute(q.order_by(WorkItem.due_date.is_(None), WorkItem.due_date, WorkItem.created_at.desc()).limit(limit)).scalars().all()
    return [_brief(ctx, w) for w in rows]


@router.get("/work-items/{wid}")
def get_work_item(wid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    w = get_or_404(ctx.db, WorkItem, wid, "Task")
    if not can_view_task(ctx.db, ctx.p, w):
        raise Forbidden("You do not have access to this task.")
    return _detail(ctx, w)


def _validate_links(ctx: Ctx, body: WorkItemIn, wid: uuid.UUID | None = None) -> None:
    """A task's links must agree with each other: a client cannot attach a task to another project's plan."""
    db = ctx.db
    if body.project_id:
        get_or_404(db, Project, body.project_id, "Project")
    if body.item_id:
        it = get_or_404(db, EngineeringItem, body.item_id, "Item")
        if it.project_id != body.project_id:
            raise AppError("The engineering item belongs to a different project.")
    if body.document_id:
        doc = get_or_404(db, Document, body.document_id, "Document")
        if not can_view_document(db, ctx.p, doc):
            raise Forbidden("You do not have access to that document.")
    if body.activity_id:
        a = get_or_404(db, PlanActivity, body.activity_id, "Activity")
        if a.project_id != body.project_id:
            raise AppError("The activity belongs to a different project.")
        if body.plan_id and body.plan_id != a.plan_id:
            raise AppError("The activity belongs to a different plan.")
        body.plan_id = a.plan_id
        body.work_package_id = body.work_package_id or a.work_package_id
    if body.work_package_id:
        wp = get_or_404(db, WorkPackage, body.work_package_id, "Work package")
        if wp.project_id != body.project_id:
            raise AppError("The work package belongs to a different project.")
        if body.plan_id and body.plan_id != wp.plan_id:
            raise AppError("The work package belongs to a different plan.")
        body.plan_id = wp.plan_id
    if body.plan_id:
        plan = get_or_404(db, ProjectPlan, body.plan_id, "Plan")
        if plan.project_id != body.project_id:
            raise AppError("The plan belongs to a different project.")
    if body.parent_id:
        parent = get_or_404(db, WorkItem, body.parent_id, "Parent task")
        if parent.project_id != body.project_id:
            raise AppError("A sub-task must be in the same project as its parent.")
        if wid and lc.would_parent_cycle(db, wid, body.parent_id):
            raise AppError("A task cannot be placed under itself or one of its own sub-tasks.", code="CYCLE")
    if body.start_date and body.due_date and body.due_date < body.start_date:
        raise AppError("The due date cannot be before the start date.")
    if body.assignee_id:
        u = get_or_404(db, User, body.assignee_id, "Assignee")
        if not u.is_active:
            raise AppError("The assignee's account is not active.")


# ------------------------------------------------------------------ create / update
@router.post("/work-items")
def create_work_item(body: WorkItemIn, ctx: Ctx = Depends(get_ctx)):
    _validate_links(ctx, body)
    probe = WorkItem(project_id=body.project_id, org_unit_id=body.org_unit_id, item_id=body.item_id)
    manager = can_manage_task(ctx.db, ctx.p, probe)
    if body.assignee_id and body.assignee_id != ctx.user.id and not manager:
        raise Forbidden("You can create tasks for yourself; assigning others needs task management permission in this scope.")
    if body.project_id and not manager and not can_view_project(ctx.db, ctx.p, body.project_id):
        raise Forbidden("You do not have access to this project.")
    project = ctx.db.get(Project, body.project_id) if body.project_id else None
    life = lc.get_lifecycle(ctx.db, body.project_id)
    prefix = project.code if project else "TSK"
    w = WorkItem(key=f"{prefix}-{next_seq(ctx.db, 'wi:' + prefix)}", reporter_id=ctx.user.id, status=lc.initial_state(life), **body.model_dump())
    ctx.db.add(w)
    ctx.db.flush()
    ctx.db.add(WorkItemEvent(work_item_id=w.id, actor_id=ctx.user.id, kind="CREATED", to_value=w.status))
    lc.refresh_progress(ctx.db, w)
    if w.assignee_id and w.assignee_id != ctx.user.id:
        notify(ctx.db, w.assignee_id, "task.assigned", f"New task {w.key}: {w.title}", f"Assigned by {ctx.user.full_name}", link=f"/tasks?open={w.id}")
    ctx.audit("task.create", "work_item", w.id, f"{w.key} created: {w.title}")
    ctx.db.commit()
    return _brief(ctx, w)


@router.put("/work-items/{wid}")
def update_work_item(wid: uuid.UUID, body: WorkItemIn, version: int | None = None, ctx: Ctx = Depends(get_ctx)):
    w = get_or_404(ctx.db, WorkItem, wid, "Task")
    manager = can_manage_task(ctx.db, ctx.p, w)
    if ctx.user.id not in (w.assignee_id, w.reporter_id) and not manager:
        raise Forbidden("Only the assignee, reporter or a task manager in this scope can update this task.")
    if version is not None and version != w.version:
        raise Conflict("Task was updated by someone else. Refresh and try again.")
    if body.assignee_id != w.assignee_id and not manager and body.assignee_id != ctx.user.id:
        raise Forbidden("Reassigning this task needs task management permission in this scope.")
    _validate_links(ctx, body, wid)
    old_assignee = w.assignee_id
    for k, v in body.model_dump().items():
        setattr(w, k, v)
    w.version += 1
    if w.assignee_id != old_assignee:
        ctx.db.add(WorkItemEvent(work_item_id=w.id, actor_id=ctx.user.id, kind="ASSIGNED", from_value=str(old_assignee) if old_assignee else None, to_value=str(w.assignee_id) if w.assignee_id else None))
        if w.assignee_id and w.assignee_id != ctx.user.id:
            notify(ctx.db, w.assignee_id, "task.assigned", f"Task {w.key} assigned to you", w.title, link=f"/tasks?open={w.id}")
    lc.refresh_progress(ctx.db, w)
    ctx.audit("task.update", "work_item", w.id, f"{w.key} updated")
    ctx.db.commit()
    return _brief(ctx, w)


@router.post("/work-items/{wid}/transition")
def transition_work_item(wid: uuid.UUID, body: TransitionIn, version: int | None = None, ctx: Ctx = Depends(get_ctx)):
    w = get_or_404(ctx.db, WorkItem, wid, "Task")
    if not can_view_task(ctx.db, ctx.p, w):
        raise Forbidden("You do not have access to this task.")
    if version is not None and version != w.version:
        raise Conflict("Task was updated by someone else. Refresh and try again.")
    old = lc.transition(ctx.db, w, body.to, user_id=ctx.user.id, is_manager=can_manage_task(ctx.db, ctx.p, w), comment=body.comment)
    for uid in {w.assignee_id, w.reporter_id} - {ctx.user.id, None}:
        notify(ctx.db, uid, "task.status", f"{w.key}: {old} → {w.status}", (body.comment or w.title)[:300], link=f"/tasks?open={w.id}")
    ctx.audit("task.transition", "work_item", w.id, f"{w.key} {old} → {w.status}", {"from": old, "to": w.status, "reason": body.comment})
    ctx.db.commit()
    return _detail(ctx, w)


# ------------------------------------------------------------------ dependencies
def _require_edit(ctx: Ctx, w: WorkItem) -> None:
    if ctx.user.id not in (w.assignee_id, w.reporter_id) and not can_manage_task(ctx.db, ctx.p, w):
        raise Forbidden("Only the assignee, reporter or a task manager in this scope can change this task.")


@router.post("/work-items/{wid}/dependencies")
def add_dependency(wid: uuid.UUID, body: DependencyIn, ctx: Ctx = Depends(get_ctx)):
    db = ctx.db
    w = get_or_404(db, WorkItem, wid, "Task")
    _require_edit(ctx, w)
    pred = get_or_404(db, WorkItem, body.predecessor_id, "Predecessor")
    if not can_view_task(db, ctx.p, pred):
        raise Forbidden("You do not have access to the predecessor task.")
    if pred.id == w.id:
        raise AppError("A task cannot depend on itself.", code="CYCLE")
    if db.execute(select(TaskDependency.id).where(TaskDependency.successor_id == w.id, TaskDependency.predecessor_id == pred.id)).first():
        raise Conflict("This dependency already exists.")
    if lc.would_cycle(db, w.id, pred.id):
        raise AppError(f"{pred.key} already depends on {w.key}, so this would create a loop.", code="CYCLE")
    db.add(TaskDependency(successor_id=w.id, predecessor_id=pred.id, dep_type=body.type, lag_days=body.lag_days, created_by_id=ctx.user.id))
    if pred.assignee_id and pred.org_unit_id != w.org_unit_id and pred.assignee_id != ctx.user.id:
        notify(db, pred.assignee_id, "task.dependency", f"{w.key} now depends on your task {pred.key}", w.title, link=f"/tasks?open={pred.id}")
    ctx.audit("task.dependency.add", "work_item", w.id, f"{w.key} depends on {pred.key} ({body.type}{body.lag_days:+d}d)")
    db.commit()
    return _detail(ctx, w)


@router.delete("/work-items/{wid}/dependencies/{dep_id}")
def remove_dependency(wid: uuid.UUID, dep_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    w = get_or_404(ctx.db, WorkItem, wid, "Task")
    _require_edit(ctx, w)
    dep = get_or_404(ctx.db, TaskDependency, dep_id, "Dependency")
    if w.id not in (dep.successor_id, dep.predecessor_id):
        raise AppError("This dependency does not belong to this task.")
    ctx.db.delete(dep)
    ctx.audit("task.dependency.remove", "work_item", w.id, f"Dependency removed from {w.key}")
    ctx.db.commit()
    return _detail(ctx, w)


# ------------------------------------------------------------------ participants
@router.put("/work-items/{wid}/participants")
def set_participants(wid: uuid.UUID, body: ParticipantsIn, ctx: Ctx = Depends(get_ctx)):
    db = ctx.db
    w = get_or_404(db, WorkItem, wid, "Task")
    if not can_manage_task(db, ctx.p, w) and ctx.user.id != w.reporter_id:
        raise Forbidden("Only the reporter or a task manager in this scope can change participants.")
    existing = db.execute(select(TaskParticipant).where(TaskParticipant.work_item_id == w.id)).scalars().all()
    have = {(p.user_id, p.role) for p in existing}
    want = {(u, "CONTRIBUTOR") for u in body.contributors} | {(u, "REVIEWER") for u in body.reviewers}
    for u, _ in want:
        get_or_404(db, User, u, "User")
    for p in existing:
        if (p.user_id, p.role) not in want:
            db.delete(p)
    for u, role in want - have:
        db.add(TaskParticipant(work_item_id=w.id, user_id=u, role=role))
        if u != ctx.user.id:
            notify(db, u, "task.assigned", f"You were added to {w.key} as {role.lower()}", w.title, link=f"/tasks?open={w.id}")
    ctx.audit("task.participants", "work_item", w.id, f"{w.key} participants updated", {"contributors": [str(x) for x in body.contributors], "reviewers": [str(x) for x in body.reviewers]})
    db.commit()
    return _detail(ctx, w)


# ------------------------------------------------------------------ checklist
@router.post("/work-items/{wid}/checklist")
def add_checklist_item(wid: uuid.UUID, body: ChecklistIn, ctx: Ctx = Depends(get_ctx)):
    w = get_or_404(ctx.db, WorkItem, wid, "Task")
    _require_edit(ctx, w)
    count = len(ctx.db.execute(select(TaskChecklistItem.id).where(TaskChecklistItem.work_item_id == w.id)).all())
    ctx.db.add(TaskChecklistItem(work_item_id=w.id, text=body.text, mandatory=body.mandatory, sort_order=count))
    ctx.audit("task.checklist.add", "work_item", w.id, f"Checklist item added to {w.key}")
    ctx.db.commit()
    return _detail(ctx, w)


@router.patch("/work-items/{wid}/checklist/{item_id}")
def update_checklist_item(wid: uuid.UUID, item_id: uuid.UUID, body: ChecklistPatch, ctx: Ctx = Depends(get_ctx)):
    w = get_or_404(ctx.db, WorkItem, wid, "Task")
    _require_edit(ctx, w)
    i = get_or_404(ctx.db, TaskChecklistItem, item_id, "Checklist item")
    if i.work_item_id != w.id:
        raise AppError("This checklist item does not belong to this task.")
    if body.done is not None and body.done != i.done:
        i.done = body.done
        i.done_by_id = ctx.user.id if body.done else None
        i.done_at = utcnow() if body.done else None
    if body.text is not None:
        i.text = body.text
    if body.mandatory is not None:
        i.mandatory = body.mandatory
    ctx.audit("task.checklist.update", "work_item", w.id, f"{w.key} checklist: {i.text[:80]} ({'done' if i.done else 'open'})")
    ctx.db.commit()
    return _detail(ctx, w)


@router.delete("/work-items/{wid}/checklist/{item_id}")
def delete_checklist_item(wid: uuid.UUID, item_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    w = get_or_404(ctx.db, WorkItem, wid, "Task")
    if not can_manage_task(ctx.db, ctx.p, w) and ctx.user.id != w.reporter_id:
        raise Forbidden("Only the reporter or a task manager can remove a checklist item.")  # the owner must not delete their own gate
    i = get_or_404(ctx.db, TaskChecklistItem, item_id, "Checklist item")
    if i.work_item_id != w.id:
        raise AppError("This checklist item does not belong to this task.")
    ctx.audit("task.checklist.remove", "work_item", w.id, f"{w.key} checklist item removed: {i.text[:80]}")
    ctx.db.delete(i)
    ctx.db.commit()
    return _detail(ctx, w)


# ------------------------------------------------------------------ deliverables
@router.post("/work-items/{wid}/deliverables")
def add_deliverable(wid: uuid.UUID, body: DeliverableIn, ctx: Ctx = Depends(get_ctx)):
    w = get_or_404(ctx.db, WorkItem, wid, "Task")
    _require_edit(ctx, w)
    doc = get_or_404(ctx.db, Document, body.document_id, "Document")
    if not can_view_document(ctx.db, ctx.p, doc):
        raise Forbidden("You do not have access to that document.")
    if ctx.db.execute(select(TaskDeliverable.id).where(TaskDeliverable.work_item_id == w.id, TaskDeliverable.document_id == doc.id)).first():
        raise Conflict("This document is already a deliverable of this task.")
    ctx.db.add(TaskDeliverable(work_item_id=w.id, document_id=doc.id, required_status=body.required_status, mandatory=body.mandatory, created_by_id=ctx.user.id))
    ctx.audit("task.deliverable.add", "work_item", w.id, f"{doc.number} added as a deliverable of {w.key} (must be {body.required_status})")
    ctx.db.commit()
    return _detail(ctx, w)


@router.delete("/work-items/{wid}/deliverables/{did}")
def remove_deliverable(wid: uuid.UUID, did: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    w = get_or_404(ctx.db, WorkItem, wid, "Task")
    if not can_manage_task(ctx.db, ctx.p, w) and ctx.user.id != w.reporter_id:
        raise Forbidden("Only the reporter or a task manager can remove a deliverable.")
    x = get_or_404(ctx.db, TaskDeliverable, did, "Deliverable")
    if x.work_item_id != w.id:
        raise AppError("This deliverable does not belong to this task.")
    ctx.db.delete(x)
    ctx.audit("task.deliverable.remove", "work_item", w.id, f"Deliverable removed from {w.key}")
    ctx.db.commit()
    return _detail(ctx, w)


# ------------------------------------------------------------------ comments
@router.post("/work-items/{wid}/comments")
def add_comment(wid: uuid.UUID, body: CommentIn, ctx: Ctx = Depends(get_ctx)):
    w = get_or_404(ctx.db, WorkItem, wid, "Task")
    if not can_view_task(ctx.db, ctx.p, w):
        raise Forbidden("You do not have access to this task.")
    ctx.db.add(TaskComment(work_item_id=w.id, author_id=ctx.user.id, body=body.body))
    for uid in {w.assignee_id, w.reporter_id} - {ctx.user.id, None}:
        notify(ctx.db, uid, "task.comment", f"{ctx.user.full_name} commented on {w.key}", body.body[:300], link=f"/tasks?open={w.id}")
    ctx.audit("task.comment", "work_item", w.id, f"Comment added to {w.key}")
    ctx.db.commit()
    return _detail(ctx, w)
