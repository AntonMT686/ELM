"""Planning read models: project/task authorization, WBS, explainable roll-up, schedule analysis, baselines."""
from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden
from app.models import (
    Document,
    EngineeringItem,
    Milestone,
    OrgUnit,
    PlanActivity,
    PlanBaseline,
    PlanPhase,
    Project,
    ProjectMember,
    ProjectOrgAssignment,
    ProjectPlan,
    TaskDeliverable,
    TaskDependency,
    TaskParticipant,
    User,
    WorkItem,
    WorkPackage,
    WorkPackageOrg,
)
from app.services.authz import Principal, _expand_org
from app.services.serial import iso, org_brief, user_brief
from app.services.task_lifecycle import get_lifecycle, state_map, weight_of

ACTIVITY_CLOSED = {"COMPLETED", "CANCELLED"}


# ------------------------------------------------------------------ authorization
def visible_project_ids(db: Session, p: Principal) -> set[uuid.UUID] | None:
    """Projects the principal may see plans and tasks for. None means all of them."""
    if p.has_global("project.view") or p.has_global("plan.manage") or p.has_global("task.manage"):
        return None
    out = set(db.execute(select(ProjectMember.project_id).where(ProjectMember.user_id == p.id)).scalars())
    orgs: set[uuid.UUID] = set()
    items: set[uuid.UUID] = set()
    for g in p.grants:
        if g.scope_id is None:
            continue
        if g.scope_type == "PROJECT":
            out.add(g.scope_id)
        elif g.scope_type == "ORG_UNIT" and g.perms & {"project.view", "plan.manage", "task.manage"}:
            orgs.add(g.scope_id)
        elif g.scope_type == "ENG_ITEM":
            items.add(g.scope_id)
    if orgs:
        out |= set(db.execute(select(ProjectOrgAssignment.project_id).where(ProjectOrgAssignment.org_unit_id.in_(_expand_org(db, orgs)))).scalars())
    if items:
        out |= set(db.execute(select(EngineeringItem.project_id).where(EngineeringItem.id.in_(items))).scalars())
    return out


def can_view_project(db: Session, p: Principal, project_id: uuid.UUID) -> bool:
    ids = visible_project_ids(db, p)
    return ids is None or project_id in ids


def require_view_project(db: Session, p: Principal, project_id: uuid.UUID) -> None:
    if not can_view_project(db, p, project_id):
        raise Forbidden("You do not have access to this project.")


def _org_path(db: Session, org_id: uuid.UUID | None) -> str | None:
    if not org_id:
        return None
    o = db.get(OrgUnit, org_id)
    return o.path if o else None


def _item_path(db: Session, item_id: uuid.UUID | None) -> str | None:
    if not item_id:
        return None
    i = db.get(EngineeringItem, item_id)
    return i.path if i else None


def can_manage_plan(db: Session, p: Principal, project_id: uuid.UUID, *, org_id: uuid.UUID | None = None, item_id: uuid.UUID | None = None) -> bool:
    """Project-wide planners, or a directorate/item planner acting inside their own scope only."""
    return p.has("plan.manage", project_id=project_id, org_path=_org_path(db, org_id), item_path=_item_path(db, item_id))


def can_manage_task(db: Session, p: Principal, w: WorkItem) -> bool:
    return p.has("task.manage", project_id=w.project_id, org_path=_org_path(db, w.org_unit_id), item_path=_item_path(db, w.item_id))


def can_view_task(db: Session, p: Principal, w: WorkItem) -> bool:
    if p.id in (w.assignee_id, w.reporter_id) or can_manage_task(db, p, w):
        return True
    if w.project_id and can_view_project(db, p, w.project_id):
        return True
    if w.org_unit_id and w.org_unit_id in task_org_scope(db, p):
        return True
    return db.execute(select(TaskParticipant.id).where(TaskParticipant.work_item_id == w.id, TaskParticipant.user_id == p.id)).first() is not None


def task_org_scope(db: Session, p: Principal) -> set[uuid.UUID]:
    """Org units whose tasks the principal sees: their memberships plus task-manage grants with descendants."""
    grants = {g.scope_id for g in p.grants if g.scope_type == "ORG_UNIT" and g.scope_id and "task.manage" in g.perms}
    return set(p.org_ids) | _expand_org(db, grants)


def task_visibility_clause(db: Session, p: Principal):
    """SQL filter for the task list, the same rule as can_view_task. None means no restriction."""
    if p.has_global("task.manage"):
        return None
    conds = [WorkItem.assignee_id == p.id, WorkItem.reporter_id == p.id, WorkItem.id.in_(select(TaskParticipant.work_item_id).where(TaskParticipant.user_id == p.id))]
    ids = visible_project_ids(db, p)
    if ids is None:
        conds.append(WorkItem.project_id.is_not(None))
    elif ids:
        conds.append(WorkItem.project_id.in_(ids))
    orgs = task_org_scope(db, p)
    if orgs:
        conds.append(WorkItem.org_unit_id.in_(orgs))
    return or_(*conds)


# ------------------------------------------------------------------ phases
def phases_for(db: Session, project_id: uuid.UUID) -> list[PlanPhase]:
    own = db.execute(select(PlanPhase).where(PlanPhase.project_id == project_id, PlanPhase.active.is_(True)).order_by(PlanPhase.sort_order, PlanPhase.name)).scalars().all()
    if own:
        return list(own)
    return list(db.execute(select(PlanPhase).where(PlanPhase.project_id.is_(None), PlanPhase.active.is_(True)).order_by(PlanPhase.sort_order, PlanPhase.name)).scalars())


# ------------------------------------------------------------------ roll-up
def activity_progress(a: PlanActivity, tasks: list[WorkItem], states: dict[str, dict]) -> float:
    """Top-level tasks decide. Without tasks the activity's own status decides; a typed percentage is never trusted."""
    if a.status == "COMPLETED":
        return 100.0
    live = [t for t in tasks if states.get(t.status, {}).get("category") != "CANCELLED"]
    if live:
        total = sum(weight_of(t) for t in live)
        return round(sum(weight_of(t) * t.progress for t in live) / total, 1) if total else 0.0
    return 0.0


def _activity_weight(a: PlanActivity) -> float:
    if a.weight is not None:
        return max(float(a.weight), 0.0)
    return float(a.estimated_hours) if a.estimated_hours and a.estimated_hours > 0 else 1.0


def _is_late(end: date | None, closed: bool, today: date) -> bool:
    return bool(end and not closed and end < today)


class PlanData:
    """All rows for one plan, loaded once so the WBS, overview and baseline agree with each other."""

    def __init__(self, db: Session, plan: ProjectPlan):
        self.db = db
        self.plan = plan
        self.project = db.get(Project, plan.project_id)
        self.lifecycle = get_lifecycle(db, plan.project_id)
        self.states = state_map(self.lifecycle)
        self.packages = list(db.execute(select(WorkPackage).where(WorkPackage.plan_id == plan.id).order_by(WorkPackage.sort_order, WorkPackage.code)).scalars())
        self.activities = list(db.execute(select(PlanActivity).where(PlanActivity.plan_id == plan.id).order_by(PlanActivity.sort_order, PlanActivity.start_date, PlanActivity.title)).scalars())
        self.tasks = list(db.execute(select(WorkItem).where(WorkItem.plan_id == plan.id).order_by(WorkItem.sort_order, WorkItem.start_date, WorkItem.key)).scalars())
        self.milestones = list(db.execute(select(Milestone).where(Milestone.project_id == plan.project_id, or_(Milestone.plan_id == plan.id, Milestone.plan_id.is_(None))).order_by(Milestone.due_date, Milestone.name)).scalars())
        self.phases = phases_for(db, plan.project_id)
        ids = [t.id for t in self.tasks]
        self.deps = list(db.execute(select(TaskDependency).where(TaskDependency.successor_id.in_(ids))).scalars()) if ids else []
        self.deliverables = list(db.execute(select(TaskDeliverable, Document).join(Document, Document.id == TaskDeliverable.document_id).where(TaskDeliverable.work_item_id.in_(ids))).all()) if ids else []
        self.tasks_by_activity: dict[uuid.UUID, list[WorkItem]] = defaultdict(list)
        for t in self.tasks:
            if t.activity_id and not t.parent_id:
                self.tasks_by_activity[t.activity_id].append(t)
        self.activity_pct = {a.id: activity_progress(a, self.tasks_by_activity.get(a.id, []), self.states) for a in self.activities}

    def closed(self, t: WorkItem) -> bool:
        return self.states.get(t.status, {}).get("category") in ("DONE", "CANCELLED")

    def users(self, ids) -> dict[uuid.UUID, User]:
        ids = {i for i in ids if i}
        return {u.id: u for u in self.db.execute(select(User).where(User.id.in_(ids))).scalars()} if ids else {}


def task_row(t: WorkItem, users: dict, states: dict, today: date) -> dict:
    st = states.get(t.status, {})
    return {
        "type": "task", "id": str(t.id), "key": t.key, "title": t.title, "status": t.status, "status_label": st.get("label", t.status), "status_color": st.get("color", "gray"),
        "priority": t.priority, "kind": t.kind, "start_date": iso(t.start_date), "end_date": iso(t.due_date), "actual_start": iso(t.actual_start), "actual_end": iso(t.actual_end),
        "estimated_hours": t.estimated_hours, "actual_hours": t.actual_hours, "progress": t.progress, "assignee": user_brief(users.get(t.assignee_id)),
        "activity_id": str(t.activity_id) if t.activity_id else None, "work_package_id": str(t.work_package_id) if t.work_package_id else None, "parent_id": str(t.parent_id) if t.parent_id else None,
        "legacy_key": t.legacy_key, "late": _is_late(t.due_date, st.get("category") in ("DONE", "CANCELLED"), today),
    }


def wbs(db: Session, plan: ProjectPlan) -> dict:
    d = PlanData(db, plan)
    today = date.today()
    users = d.users({t.assignee_id for t in d.tasks} | {a.owner_id for a in d.activities} | {w.owner_id for w in d.packages} | {m.owner_id for m in d.milestones})
    orgs = {o.id: o for o in db.execute(select(OrgUnit)).scalars()}
    contrib: dict[uuid.UUID, list] = defaultdict(list)
    if d.packages:
        for row in db.execute(select(WorkPackageOrg).where(WorkPackageOrg.work_package_id.in_([w.id for w in d.packages]))).scalars():
            if row.org_unit_id in orgs:
                contrib[row.work_package_id].append(org_brief(orgs[row.org_unit_id]))
    phase_names = {f.id: f.name for f in d.phases}
    keys = {t.id: t for t in d.tasks}
    analysis = schedule_analysis(d)
    pkg_rows = []
    for w in d.packages:
        acts = [a for a in d.activities if a.work_package_id == w.id]
        total = sum(_activity_weight(a) for a in acts if a.status != "CANCELLED")
        pct = round(sum(_activity_weight(a) * d.activity_pct[a.id] for a in acts if a.status != "CANCELLED") / total, 1) if total else 0.0
        pkg_rows.append({"id": str(w.id), "code": w.code, "name": w.name, "description": w.description, "status": w.status, "start_date": iso(w.start_date), "end_date": iso(w.end_date), "owner": user_brief(users.get(w.owner_id)),
                         "lead_org": org_brief(orgs.get(w.lead_org_unit_id)), "contributors": contrib[w.id], "item_id": str(w.item_id) if w.item_id else None, "domain_id": str(w.domain_id) if w.domain_id else None, "progress": pct, "version": w.version})
    return {
        "plan": plan_dict(db, plan),
        "lifecycle": d.lifecycle,
        "work_packages": pkg_rows,
        "activities": [{"id": str(a.id), "title": a.title, "description": a.description, "status": a.status, "priority": a.priority, "start_date": iso(a.start_date), "end_date": iso(a.end_date),
                        "estimated_hours": a.estimated_hours, "weight": a.weight, "progress": d.activity_pct[a.id], "work_package_id": str(a.work_package_id) if a.work_package_id else None,
                        "phase_id": str(a.phase_id) if a.phase_id else None, "phase": phase_names.get(a.phase_id), "owner": user_brief(users.get(a.owner_id)), "version": a.version,
                        "late": _is_late(a.end_date, a.status in ACTIVITY_CLOSED, today)} for a in d.activities],
        "tasks": [{**task_row(t, users, d.states, today), "critical": str(t.id) in analysis["critical"]} for t in d.tasks],
        "dependencies": [{"id": str(x.id), "successor_id": str(x.successor_id), "predecessor_id": str(x.predecessor_id), "type": x.dep_type, "lag_days": x.lag_days, "predecessor_key": keys[x.predecessor_id].key if x.predecessor_id in keys else None} for x in d.deps],
        "milestones": [milestone_dict(db, m, users, today) for m in d.milestones],
        "phases": [{"id": str(f.id), "code": f.code, "name": f.name, "weight": f.weight} for f in d.phases],
        "schedule_conflicts": analysis["conflicts"],
    }


def plan_dict(db: Session, p: ProjectPlan) -> dict:
    proj = db.get(Project, p.project_id)
    return {"id": str(p.id), "project": {"id": str(proj.id), "code": proj.code, "name": proj.name} if proj else None, "name": p.name, "version_label": p.version_label, "description": p.description, "status": p.status,
            "owner": user_brief(db.get(User, p.owner_id)) if p.owner_id else None, "version": p.version, "created_at": iso(p.created_at), "updated_at": iso(p.updated_at)}


def milestone_dict(db: Session, m: Milestone, users: dict | None, today: date) -> dict:
    owner = users.get(m.owner_id) if users is not None else (db.get(User, m.owner_id) if m.owner_id else None)
    return {"id": str(m.id), "code": m.code, "name": m.name, "description": m.description, "status": m.status, "start_date": iso(m.start_date), "due_date": iso(m.due_date), "achieved_date": iso(m.achieved_date),
            "owner": user_brief(owner), "plan_id": str(m.plan_id) if m.plan_id else None, "org_unit_id": str(m.org_unit_id) if m.org_unit_id else None, "item_id": str(m.item_id) if m.item_id else None, "version": m.version,
            "late": _is_late(m.due_date, m.status in ("ACHIEVED", "CANCELLED"), today), "at_risk": bool(m.due_date and m.status not in ("ACHIEVED", "CANCELLED") and today <= m.due_date <= today + timedelta(days=14))}


def overview(db: Session, plan: ProjectPlan) -> dict:
    """Explainable roll-up (architecture §17.3): counts, weights and open gates beside each percentage."""
    d = PlanData(db, plan)
    today = date.today()
    users = d.users({t.assignee_id for t in d.tasks})
    # phases
    phase_rows = []
    weighted = total_weight = 0.0
    phase_ids = {f.id for f in d.phases}
    groups = [(f.id, f.name, f.weight, [a for a in d.activities if a.phase_id == f.id]) for f in d.phases]
    other = [a for a in d.activities if a.phase_id not in phase_ids]
    if other:
        groups.append((None, "No phase", 0.0, other))
    open_by_activity: dict[uuid.UUID, int] = defaultdict(int)
    for t in d.tasks:
        if t.activity_id and not d.closed(t):
            open_by_activity[t.activity_id] += 1
    for fid, name, weight, acts in groups:
        live = [a for a in acts if a.status != "CANCELLED"]
        tw = sum(_activity_weight(a) for a in live)
        score = sum(_activity_weight(a) * d.activity_pct[a.id] for a in live)
        pct = round(score / tw, 1) if tw else 0.0
        if live and weight:
            weighted += pct * weight
            total_weight += weight
        phase_rows.append({"id": str(fid) if fid else None, "name": name, "weight": weight, "progress": pct, "activities_total": len(live), "activities_completed": sum(1 for a in live if a.status == "COMPLETED"),
                           "open_tasks": sum(open_by_activity[a.id] for a in live), "late_activities": sum(1 for a in live if _is_late(a.end_date, a.status in ACTIVITY_CLOSED, today))})
    if total_weight:
        progress = round(weighted / total_weight, 1)
    else:
        live = [a for a in d.activities if a.status != "CANCELLED"]
        tw = sum(_activity_weight(a) for a in live)
        progress = round(sum(_activity_weight(a) * d.activity_pct[a.id] for a in live) / tw, 1) if tw else 0.0
    # tasks
    task_ids = {t.id for t in d.tasks}
    counts: dict[str, int] = defaultdict(int)
    overdue = []
    workload: dict[str, dict] = {}
    for t in d.tasks:
        counts[t.status] += 1
        late = _is_late(t.due_date, d.closed(t), today)
        if late:
            overdue.append({**task_row(t, users, d.states, today), "days_late": (today - t.due_date).days})
        if t.assignee_id and not d.closed(t):
            u = users.get(t.assignee_id)
            row = workload.setdefault(str(t.assignee_id), {"user": user_brief(u), "open": 0, "late": 0, "estimated_hours": 0.0})
            row["open"] += 1
            row["late"] += 1 if late else 0
            row["estimated_hours"] += t.estimated_hours or 0
    # gates: progress can read 100 while these stay open (architecture §23 scenario G)
    gates = []
    by_id = {t.id: t for t in d.tasks}
    for x, doc in d.deliverables:
        if not x.mandatory:
            continue
        met = doc.status in (("APPROVED", "RELEASED", "SUPERSEDED") if x.required_status == "APPROVED" else ("RELEASED", "SUPERSEDED"))
        if not met:
            t = by_id.get(x.work_item_id)
            gates.append({"type": "DELIVERABLE", "task": t.key if t else None, "document": doc.number, "status": doc.status, "required": x.required_status, "document_id": str(doc.id)})
    for m in d.milestones:
        if m.status not in ("ACHIEVED", "CANCELLED"):
            gates.append({"type": "MILESTONE", "name": m.name, "status": m.status, "due_date": iso(m.due_date), "late": _is_late(m.due_date, False, today)})
    analysis = schedule_analysis(d)
    # cross-directorate dependencies, with who answers for each side (architecture §9.4)
    cross = []
    for dep in d.deps:
        s, pr = by_id.get(dep.successor_id), by_id.get(dep.predecessor_id)
        if s and pr and s.org_unit_id and pr.org_unit_id and s.org_unit_id != pr.org_unit_id:
            more = d.users({s.assignee_id, pr.assignee_id})
            cross.append({"successor": s.key, "predecessor": pr.key, "type": dep.dep_type, "lag_days": dep.lag_days, "successor_org": org_brief(db.get(OrgUnit, s.org_unit_id)), "predecessor_org": org_brief(db.get(OrgUnit, pr.org_unit_id)),
                          "successor_owner": user_brief(more.get(s.assignee_id)), "predecessor_owner": user_brief(more.get(pr.assignee_id)), "predecessor_status": pr.status})
    n_tasks = len(task_ids)
    completed = sum(v for k, v in counts.items() if d.states.get(k, {}).get("category") == "DONE")
    cancelled = sum(v for k, v in counts.items() if d.states.get(k, {}).get("category") == "CANCELLED")
    return {
        "plan": plan_dict(db, plan),
        "progress": progress,
        "fully_complete": progress >= 100 and not gates,
        "calculation": {"rule": "Phase progress is the weighted mean of its activities; project progress is the weighted mean of its phases that have activities. Task progress follows status: Completed = 100, Open = 0, others use the assignee's estimate capped at 95.", "phase_weight_total": total_weight},
        "phases": phase_rows,
        "tasks": {"total": n_tasks, "completed": completed, "cancelled": cancelled, "open": n_tasks - completed - cancelled, "overdue": len(overdue), "by_status": [{"status": s["code"], "label": s["label"], "color": s.get("color"), "count": counts.get(s["code"], 0)} for s in d.lifecycle["states"]]},
        "overdue": sorted(overdue, key=lambda x: -x["days_late"])[:50],
        "workload": sorted(workload.values(), key=lambda x: -x["open"]),
        "milestones": [milestone_dict(db, m, d.users({x.owner_id for x in d.milestones}), today) for m in d.milestones],
        "open_gates": gates,
        "schedule_conflicts": analysis["conflicts"],
        "critical_tasks": len(analysis["critical"]),
        "cross_directorate_dependencies": cross,
    }


# ------------------------------------------------------------------ schedule analysis
def _duration(t: WorkItem) -> int:
    return max((t.due_date - t.start_date).days, 0) + 1 if t.start_date and t.due_date else 1


def schedule_analysis(d: PlanData) -> dict:
    """Date conflicts against dependencies, and the critical path (zero-float chain) in calendar days."""
    tasks = {t.id: t for t in d.tasks if t.start_date or t.due_date}
    conflicts = []
    for x in d.deps:
        s, pr = tasks.get(x.successor_id), tasks.get(x.predecessor_id)
        if not s or not pr or d.closed(s):
            continue
        lag = timedelta(days=x.lag_days)
        need, actual, what = None, None, ""
        if x.dep_type == "FS" and pr.due_date and s.start_date:
            need, actual, what = pr.due_date + lag + timedelta(days=1), s.start_date, "must start after its predecessor finishes"
        elif x.dep_type == "SS" and pr.start_date and s.start_date:
            need, actual, what = pr.start_date + lag, s.start_date, "must start with or after its predecessor"
        elif x.dep_type == "FF" and pr.due_date and s.due_date:
            need, actual, what = pr.due_date + lag, s.due_date, "must finish with or after its predecessor"
        elif x.dep_type == "SF" and pr.start_date and s.due_date:
            need, actual, what = pr.start_date + lag, s.due_date, "must finish after its predecessor starts"
        if need and actual and actual < need:
            conflicts.append({"task": s.key, "task_id": str(s.id), "predecessor": pr.key, "type": x.dep_type, "lag_days": x.lag_days, "planned": iso(actual), "earliest_allowed": iso(need), "message": f"{s.key} {what} {pr.key} ({x.dep_type}{x.lag_days:+d}d): planned {actual}, earliest {need}."})
    return {"conflicts": conflicts, "critical": _critical(d, tasks)}


def _critical(d: PlanData, tasks: dict[uuid.UUID, WorkItem]) -> set[str]:
    preds: dict[uuid.UUID, list[TaskDependency]] = defaultdict(list)
    succs: dict[uuid.UUID, list[TaskDependency]] = defaultdict(list)
    for x in d.deps:
        if x.successor_id in tasks and x.predecessor_id in tasks:
            preds[x.successor_id].append(x)
            succs[x.predecessor_id].append(x)
    if not preds:
        return set()
    indeg = {i: len(preds[i]) for i in tasks}
    order, queue = [], [i for i, n in indeg.items() if n == 0]
    while queue:
        cur = queue.pop()
        order.append(cur)
        for x in succs[cur]:
            indeg[x.successor_id] -= 1
            if indeg[x.successor_id] == 0:
                queue.append(x.successor_id)
    if len(order) != len(tasks):  # a loop in migrated data must not break the page
        return set()
    es: dict[uuid.UUID, int] = {}
    ef: dict[uuid.UUID, int] = {}
    for i in order:
        dur = _duration(tasks[i])
        start = 0
        for x in preds[i]:
            if x.dep_type == "FS":
                start = max(start, ef[x.predecessor_id] + x.lag_days)
            elif x.dep_type == "SS":
                start = max(start, es[x.predecessor_id] + x.lag_days)
            elif x.dep_type == "FF":
                start = max(start, ef[x.predecessor_id] + x.lag_days - dur)
            else:
                start = max(start, es[x.predecessor_id] + x.lag_days - dur)
        es[i], ef[i] = start, start + dur
    end = max(ef.values())
    ls: dict[uuid.UUID, int] = {}
    lf: dict[uuid.UUID, int] = {}
    for i in reversed(order):
        dur = _duration(tasks[i])
        finish = end
        for x in succs[i]:
            s = x.successor_id
            if x.dep_type == "FS":
                finish = min(finish, ls[s] - x.lag_days)
            elif x.dep_type == "SS":
                finish = min(finish, ls[s] - x.lag_days + dur)
            elif x.dep_type == "FF":
                finish = min(finish, lf[s] - x.lag_days)
            else:
                finish = min(finish, lf[s] - x.lag_days + dur)
        lf[i], ls[i] = finish, finish - dur
    return {str(i) for i in order if ls[i] - es[i] <= 0 and (preds[i] or succs[i])}


# ------------------------------------------------------------------ baselines
def snapshot(db: Session, plan: ProjectPlan) -> dict:
    d = PlanData(db, plan)
    return {
        "plan": {"id": str(plan.id), "name": plan.name, "version_label": plan.version_label},
        "activities": [{"id": str(a.id), "title": a.title, "start_date": iso(a.start_date), "end_date": iso(a.end_date), "estimated_hours": a.estimated_hours, "status": a.status} for a in d.activities],
        "tasks": [{"id": str(t.id), "key": t.key, "title": t.title, "start_date": iso(t.start_date), "due_date": iso(t.due_date), "estimated_hours": t.estimated_hours, "status": t.status, "assignee_id": str(t.assignee_id) if t.assignee_id else None} for t in d.tasks],
        "milestones": [{"id": str(m.id), "name": m.name, "due_date": iso(m.due_date), "status": m.status} for m in d.milestones],
        "dependencies": [{"successor_id": str(x.successor_id), "predecessor_id": str(x.predecessor_id), "type": x.dep_type, "lag_days": x.lag_days} for x in d.deps],
    }


def seal(data: dict) -> tuple[str, str]:
    text = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return text, hashlib.sha256(text.encode()).hexdigest()


def compare_baseline(db: Session, plan: ProjectPlan, base: PlanBaseline) -> dict:
    """Variance between a sealed baseline and the live plan: added, removed and rescheduled records, with slip in days."""
    old = json.loads(base.snapshot)
    new = snapshot(db, plan)
    out: dict = {"baseline": {"id": str(base.id), "seq": base.seq, "label": base.label, "reason": base.reason, "created_at": iso(base.created_at), "sha256": base.sha256, "created_by": user_brief(db.get(User, base.created_by_id)) if base.created_by_id else None},
                 "integrity_ok": hashlib.sha256(base.snapshot.encode()).hexdigest() == base.sha256}
    for section, end_key in (("tasks", "due_date"), ("activities", "end_date"), ("milestones", "due_date")):
        a = {r["id"]: r for r in old.get(section, [])}
        b = {r["id"]: r for r in new[section]}
        moved = []
        for i in a.keys() & b.keys():
            o, n = a[i].get(end_key), b[i].get(end_key)
            if o != n:
                slip = (date.fromisoformat(n) - date.fromisoformat(o)).days if o and n else None
                moved.append({"id": i, "name": b[i].get("key") or b[i].get("title") or b[i].get("name"), "title": b[i].get("title"), "baseline": o, "current": n, "slip_days": slip})
        out[section] = {"added": [b[i] for i in b.keys() - a.keys()], "removed": [a[i] for i in a.keys() - b.keys()], "moved": sorted(moved, key=lambda x: -(x["slip_days"] or 0))}
    return out
