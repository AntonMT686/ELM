"""Task lifecycle (architecture §9.3/§9.4): configurable states and transitions, server-side validation, completion
gates and status-based progress. The default is the ProFlow template; `task.lifecycle` settings override it."""
from __future__ import annotations

import json
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import AppError, Forbidden
from app.models import (
    Document,
    SystemSetting,
    TaskChecklistItem,
    TaskDeliverable,
    TaskDependency,
    TaskParticipant,
    WorkItem,
    WorkItemEvent,
)

CATEGORIES = {"INITIAL", "ACTIVE", "HOLD", "DONE", "CANCELLED"}
ACTORS = {"assignee", "reporter", "reviewer", "manager", "system"}
# "system" moves are made only by ELM itself (for example when GitLab reports that a merge request was merged).
WORK = ["assignee", "manager"]
DECIDE = ["reviewer", "reporter", "manager"]

DEFAULT_LIFECYCLE: dict = {
    "states": [
        {"code": "OPEN", "label": "Open", "category": "INITIAL", "color": "gray"},
        {"code": "IN_PROGRESS", "label": "In progress", "category": "ACTIVE", "color": "blue"},
        {"code": "REVIEW", "label": "In review", "category": "ACTIVE", "color": "violet"},
        {"code": "CHANGES_REQUESTED", "label": "Changes requested", "category": "ACTIVE", "color": "orange"},
        {"code": "ON_HOLD", "label": "On hold", "category": "HOLD", "color": "yellow"},
        {"code": "COMPLETED", "label": "Completed", "category": "DONE", "color": "teal"},
        {"code": "CANCELLED", "label": "Cancelled", "category": "CANCELLED", "color": "gray"},
    ],
    "transitions": [
        {"from": "OPEN", "to": "IN_PROGRESS", "label": "Start", "actors": WORK},
        {"from": "IN_PROGRESS", "to": "REVIEW", "label": "Submit for review", "actors": WORK},
        {"from": "REVIEW", "to": "COMPLETED", "label": "Accept and complete", "actors": DECIDE},
        {"from": "REVIEW", "to": "CHANGES_REQUESTED", "label": "Request changes", "actors": DECIDE, "reason": True},
        {"from": "CHANGES_REQUESTED", "to": "IN_PROGRESS", "label": "Resume work", "actors": WORK},
        {"from": "OPEN", "to": "ON_HOLD", "label": "Put on hold", "actors": WORK, "reason": True},
        {"from": "IN_PROGRESS", "to": "ON_HOLD", "label": "Put on hold", "actors": WORK, "reason": True},
        {"from": "ON_HOLD", "to": "OPEN", "label": "Resume", "actors": WORK},
        {"from": "OPEN", "to": "CANCELLED", "label": "Cancel", "actors": ["reporter", "manager"], "reason": True},
        {"from": "IN_PROGRESS", "to": "CANCELLED", "label": "Cancel", "actors": ["reporter", "manager"], "reason": True},
    ],
}
# Software development lifecycle (architecture §12.1), used for tasks of kind DEVELOPMENT unless configured otherwise.
DEV_LIFECYCLE: dict = {
    "states": [
        {"code": "OPEN", "label": "Open", "category": "INITIAL", "color": "gray"},
        {"code": "IN_PROGRESS", "label": "In progress", "category": "ACTIVE", "color": "blue"},
        {"code": "CODE_REVIEW", "label": "Code review", "category": "ACTIVE", "color": "violet"},
        {"code": "CHANGES_REQUESTED", "label": "Changes requested", "category": "ACTIVE", "color": "orange"},
        {"code": "APPROVED", "label": "Approved", "category": "ACTIVE", "color": "cyan"},
        {"code": "MERGED", "label": "Merged", "category": "ACTIVE", "color": "indigo"},
        {"code": "TESTING", "label": "Testing", "category": "ACTIVE", "color": "grape"},
        {"code": "COMPLETED", "label": "Completed", "category": "DONE", "color": "teal"},
        {"code": "REJECTED", "label": "Rejected", "category": "CANCELLED", "color": "red"},
    ],
    "transitions": [
        {"from": "OPEN", "to": "IN_PROGRESS", "label": "Start development", "actors": WORK},
        {"from": "IN_PROGRESS", "to": "CODE_REVIEW", "label": "Submit for code review", "actors": WORK + ["system"]},
        {"from": "CODE_REVIEW", "to": "CHANGES_REQUESTED", "label": "Request changes", "actors": DECIDE, "reason": True},
        {"from": "CHANGES_REQUESTED", "to": "IN_PROGRESS", "label": "Resume work", "actors": WORK},
        {"from": "CODE_REVIEW", "to": "APPROVED", "label": "Approve code", "actors": DECIDE},
        {"from": "APPROVED", "to": "MERGED", "label": "Mark merged", "actors": ["manager", "system"]},
        {"from": "MERGED", "to": "TESTING", "label": "Start testing", "actors": WORK + ["reviewer"]},
        {"from": "TESTING", "to": "COMPLETED", "label": "Complete", "actors": DECIDE},
        {"from": "TESTING", "to": "IN_PROGRESS", "label": "Testing failed", "actors": DECIDE + ["assignee"], "reason": True},
        {"from": "OPEN", "to": "REJECTED", "label": "Reject", "actors": ["reporter", "manager"], "reason": True},
        {"from": "IN_PROGRESS", "to": "REJECTED", "label": "Reject", "actors": ["reporter", "manager"], "reason": True},
    ],
}
KIND_DEFAULTS: dict[str, dict] = {"DEVELOPMENT": DEV_LIFECYCLE}

DEFAULT_RULES = {"child_tasks_closed": True, "mandatory_checklist": True, "mandatory_deliverables": True, "predecessors": True, "merged_merge_request": True}
ACTIVE_PROGRESS_CAP = 95.0  # only the completion gate can give 100%


def _setting(db: Session, key: str) -> dict | None:
    row = db.get(SystemSetting, key)
    if not row:
        return None
    try:
        return json.loads(row.value)
    except ValueError:
        return None


def get_lifecycle(db: Session, project_id: uuid.UUID | None = None, kind: str | None = None) -> dict:
    """Most specific first: project + kind, kind, then (for kinds without their own lifecycle) project and the shared one."""
    if kind:
        if project_id:
            own = _setting(db, f"task.lifecycle.{project_id}.{kind}")
            if own:
                return own
        shared = _setting(db, f"task.lifecycle.kind.{kind}")
        if shared:
            return shared
        if kind in KIND_DEFAULTS:
            return KIND_DEFAULTS[kind]
    if project_id:
        own = _setting(db, f"task.lifecycle.{project_id}")
        if own:
            return own
    return _setting(db, "task.lifecycle") or DEFAULT_LIFECYCLE


def lifecycle_for(db: Session, w: WorkItem) -> dict:
    return get_lifecycle(db, w.project_id, w.kind)


def merged_state_map(db: Session, project_id: uuid.UUID | None = None) -> dict[str, dict]:
    """States of every lifecycle that can apply in a project, for views that mix task kinds (plans, boards, roll-ups)."""
    out: dict[str, dict] = {}
    for kind in KIND_DEFAULTS:
        out.update(state_map(get_lifecycle(db, project_id, kind)))
    out.update(state_map(get_lifecycle(db, project_id)))
    return out


def get_rules(db: Session) -> dict:
    return {**DEFAULT_RULES, **(_setting(db, "task.completion_rules") or {})}


def state_map(lc: dict) -> dict[str, dict]:
    return {s["code"]: s for s in lc["states"]}


def codes_in(lc: dict, *categories: str) -> set[str]:
    return {s["code"] for s in lc["states"] if s["category"] in categories}


def initial_state(lc: dict) -> str:
    return next(s["code"] for s in lc["states"] if s["category"] == "INITIAL")


def closed_statuses(db: Session) -> set[str]:
    """Every code any configured lifecycle treats as closed, for filters that span projects."""
    out = codes_in(get_lifecycle(db), "DONE", "CANCELLED")
    for kind in KIND_DEFAULTS:
        out |= codes_in(get_lifecycle(db, None, kind), "DONE", "CANCELLED")
    rows = db.execute(select(SystemSetting).where(SystemSetting.key.like("task.lifecycle.%"))).scalars()
    for row in rows:
        try:
            out |= codes_in(json.loads(row.value), "DONE", "CANCELLED")
        except (ValueError, KeyError):
            continue
    return out


def validate_lifecycle(lc: dict, actors: set[str] = ACTORS) -> list[str]:
    errors: list[str] = []
    states = lc.get("states") or []
    transitions = lc.get("transitions") or []
    codes = [s.get("code") for s in states]
    if not states:
        return ["At least one state is required."]
    if len(set(codes)) != len(codes):
        errors.append("State codes must be unique.")
    for s in states:
        if not s.get("code") or not s.get("label"):
            errors.append("Every state needs a code and a label.")
        if s.get("category") not in CATEGORIES:
            errors.append(f"State {s.get('code')}: unknown category {s.get('category')}.")
    cats = [s.get("category") for s in states]
    if cats.count("INITIAL") != 1:
        errors.append("Exactly one state must be the initial state.")
    if "DONE" not in cats:
        errors.append("At least one state must mean done.")
    known = set(codes)
    graph: dict[str, set[str]] = {c: set() for c in known}
    for t in transitions:
        if t.get("from") not in known or t.get("to") not in known:
            errors.append(f"Transition {t.get('from')} → {t.get('to')} uses an unknown state.")
            continue
        if t["from"] == t["to"]:
            errors.append(f"Transition {t['from']} → {t['to']} goes nowhere.")
        bad = set(t.get("actors") or []) - actors
        if bad or not t.get("actors"):
            errors.append(f"Transition {t['from']} → {t['to']}: actors must be chosen from {sorted(actors)}.")
        graph[t["from"]].add(t["to"])
    if errors:
        return errors
    start = next(s["code"] for s in states if s["category"] == "INITIAL")
    seen, stack = {start}, [start]
    while stack:
        for n in graph[stack.pop()] - seen:
            seen.add(n)
            stack.append(n)
    for c in sorted(known - seen):
        errors.append(f"State {c} cannot be reached from the initial state.")
    terminal = {s["code"] for s in states if s["category"] in ("DONE", "CANCELLED")}
    for s in states:
        c = s["code"]
        if c in terminal:
            continue
        reach, stack = {c}, [c]
        while stack:
            for n in graph[stack.pop()] - reach:
                reach.add(n)
                stack.append(n)
        if not reach & terminal:
            errors.append(f"State {c} has no path to a done or cancelled state.")
    return errors


def weight_of(w) -> float:
    if w.weight is not None:
        return max(float(w.weight), 0.0)
    return float(w.estimated_hours) if w.estimated_hours and w.estimated_hours > 0 else 1.0


def calculate_progress(category: str, reported: float) -> float:
    """Progress follows status: a client-sent percentage alone can never reach 100 or move an unstarted task."""
    if category == "DONE":
        return 100.0
    if category in ("INITIAL", "CANCELLED"):
        return 0.0
    return max(0.0, min(float(reported or 0), ACTIVE_PROGRESS_CAP))


def refresh_progress(db: Session, w: WorkItem) -> None:
    """Recalculate this task, then its ancestors. A parent is the weighted mean of its children that are not cancelled."""
    states = merged_state_map(db, w.project_id)
    node: WorkItem | None = w
    seen: set[uuid.UUID] = set()
    while node is not None and node.id not in seen:
        seen.add(node.id)
        children = db.execute(select(WorkItem).where(WorkItem.parent_id == node.id)).scalars().all()
        category = state_map(lifecycle_for(db, node)).get(node.status, {}).get("category", "ACTIVE")
        live = [c for c in children if states.get(c.status, {}).get("category") != "CANCELLED"]
        if live and category not in ("DONE", "CANCELLED"):
            total = sum(weight_of(c) for c in live)
            node.progress = round(sum(weight_of(c) * c.progress for c in live) / total, 1) if total else 0.0
            node.progress = min(node.progress, ACTIVE_PROGRESS_CAP)
        else:
            node.progress = calculate_progress(category, node.reported_progress)
        db.flush()
        node = db.get(WorkItem, node.parent_id) if node.parent_id else None


def start_blockers(db: Session, w: WorkItem, lc: dict) -> list[str]:
    """Start-side dependency gates: FS needs the predecessor finished, SS needs it started."""
    if not get_rules(db)["predecessors"]:
        return []
    states = {**merged_state_map(db, w.project_id), **state_map(lc)}
    out: list[str] = []
    for dep, pred in _preds(db, w):
        cat = states.get(pred.status, {}).get("category", "ACTIVE")
        if cat == "CANCELLED":
            continue
        if dep.dep_type == "FS" and cat != "DONE":
            out.append(f"Waiting for {pred.key} to finish (finish-to-start).")
        elif dep.dep_type == "SS" and cat in ("INITIAL", "HOLD"):
            out.append(f"Waiting for {pred.key} to start (start-to-start).")
    return out


def completion_blockers(db: Session, w: WorkItem, lc: dict) -> list[str]:
    """Why this task cannot be marked complete (architecture §9.4). Empty means it can."""
    rules = get_rules(db)
    states = {**merged_state_map(db, w.project_id), **state_map(lc)}
    out: list[str] = []
    if rules["child_tasks_closed"]:
        for c in db.execute(select(WorkItem).where(WorkItem.parent_id == w.id)).scalars():
            if states.get(c.status, {}).get("category") not in ("DONE", "CANCELLED"):
                out.append(f"Sub-task {c.key} is still open.")
    if rules["mandatory_checklist"]:
        for i in db.execute(select(TaskChecklistItem).where(TaskChecklistItem.work_item_id == w.id, TaskChecklistItem.mandatory.is_(True), TaskChecklistItem.done.is_(False))).scalars():
            out.append(f"Checklist item not done: {i.text}")
    if rules["mandatory_deliverables"]:
        rows = db.execute(select(TaskDeliverable, Document).join(Document, Document.id == TaskDeliverable.document_id).where(TaskDeliverable.work_item_id == w.id, TaskDeliverable.mandatory.is_(True))).all()
        for d, doc in rows:
            if not _deliverable_met(doc.status, d.required_status):
                out.append(f"Deliverable {doc.number} is {doc.status} and must be {d.required_status}.")
    if rules["predecessors"]:
        for dep, pred in _preds(db, w):
            cat = states.get(pred.status, {}).get("category", "ACTIVE")
            if cat == "CANCELLED":
                continue
            if dep.dep_type in ("FS", "FF") and cat != "DONE":
                out.append(f"Predecessor {pred.key} has not finished.")
            elif dep.dep_type == "SF" and cat == "INITIAL":
                out.append(f"Predecessor {pred.key} has not started (start-to-finish).")
    if rules.get("merged_merge_request") and w.kind == "DEVELOPMENT":
        from app.services import scm

        out.extend(scm.completion_blockers(db, w))
    return out


def _deliverable_met(status: str, required: str) -> bool:
    if required == "APPROVED":
        return status in ("APPROVED", "RELEASED", "SUPERSEDED")
    return status in ("RELEASED", "SUPERSEDED")


def _preds(db: Session, w: WorkItem):
    return db.execute(select(TaskDependency, WorkItem).join(WorkItem, WorkItem.id == TaskDependency.predecessor_id).where(TaskDependency.successor_id == w.id)).all()


def actors_for(db: Session, w: WorkItem, user_id: uuid.UUID, is_manager: bool) -> set[str]:
    out: set[str] = set()
    if user_id == w.assignee_id:
        out.add("assignee")
    if user_id == w.reporter_id:
        out.add("reporter")
    if is_manager:
        out.add("manager")
    if db.execute(select(TaskParticipant.id).where(TaskParticipant.work_item_id == w.id, TaskParticipant.user_id == user_id, TaskParticipant.role == "REVIEWER")).first():
        out.add("reviewer")
    return out


def has_other_reviewers(db: Session, w: WorkItem) -> bool:
    rows = db.execute(select(TaskParticipant.user_id).where(TaskParticipant.work_item_id == w.id, TaskParticipant.role == "REVIEWER")).scalars()
    return any(uid != w.assignee_id for uid in rows)


def available_transitions(db: Session, w: WorkItem, user_id: uuid.UUID, is_manager: bool) -> list[dict]:
    """What this user may do now, including blockers, so the UI can explain instead of failing later."""
    lc = lifecycle_for(db, w)
    mine = actors_for(db, w, user_id, is_manager)
    states = state_map(lc)
    out = []
    for t in lc["transitions"]:
        if t["from"] != w.status or not mine & set(t["actors"]):
            continue
        cat = states[t["to"]]["category"]
        if user_id == w.assignee_id and cat == "DONE" and has_other_reviewers(db, w):
            continue  # maker-checker: a task with a named reviewer is not self-accepted
        blockers: list[str] = []
        if cat == "DONE":
            blockers = completion_blockers(db, w, lc)
        elif cat == "ACTIVE" and states[t["from"]]["category"] == "INITIAL":
            blockers = start_blockers(db, w, lc)
        out.append({"to": t["to"], "label": t.get("label") or states[t["to"]]["label"], "reason_required": bool(t.get("reason")), "blockers": blockers})
    return out


def transition(db: Session, w: WorkItem, to: str, *, user_id: uuid.UUID | None, is_manager: bool, comment: str | None = None, system: bool = False) -> str:
    """Validate and apply one transition. Returns the previous status. The caller audits and commits.
    system=True is used only by ELM itself (GitLab events); it acts as the "system" actor and never as a person."""
    lc = lifecycle_for(db, w)
    states = state_map(lc)
    if to not in states:
        raise AppError(f"{to} is not a state in this lifecycle.", code="INVALID_STATE")
    rule = next((t for t in lc["transitions"] if t["from"] == w.status and t["to"] == to), None)
    if rule is None:
        allowed = sorted(t["to"] for t in lc["transitions"] if t["from"] == w.status)
        raise AppError(f"A task cannot move from {states.get(w.status, {}).get('label', w.status)} to {states[to]['label']}.", code="INVALID_TRANSITION", details={"allowed": allowed})
    mine = {"system"} if system else actors_for(db, w, user_id, is_manager)
    if not mine & set(rule["actors"]):
        raise Forbidden(f"You are not allowed to perform “{rule.get('label') or states[to]['label']}” on this task.", details={"actors": rule["actors"]})
    cat = states[to]["category"]
    if not system and user_id == w.assignee_id and cat == "DONE" and has_other_reviewers(db, w):
        raise Forbidden("This task has a named reviewer, so its owner cannot accept it.", code="SOD_VIOLATION")
    if rule.get("reason") and not (comment or "").strip():
        raise AppError("A reason is required for this action.", code="REASON_REQUIRED")
    blockers: list[str] = []
    if cat == "DONE":
        blockers = completion_blockers(db, w, lc)
    elif cat == "ACTIVE" and states[w.status]["category"] == "INITIAL":
        blockers = start_blockers(db, w, lc)
    if blockers:
        raise AppError("This task cannot move yet.", code="GATE_BLOCKED", details={"errors": blockers})
    old = w.status
    w.status = to
    w.version += 1
    today = date.today()
    if cat == "ACTIVE" and not w.actual_start:
        w.actual_start = today
    if cat == "DONE":
        w.completed_at = utcnow()
        w.actual_end = today
    else:
        w.completed_at = None
        w.actual_end = None
    db.add(WorkItemEvent(work_item_id=w.id, actor_id=user_id, kind="STATUS", from_value=old, to_value=to, comment=(comment or "").strip() or None))
    refresh_progress(db, w)
    return old


def would_cycle(db: Session, successor_id: uuid.UUID, predecessor_id: uuid.UUID) -> bool:
    """True if adding predecessor → successor closes a loop, i.e. the predecessor already depends on the successor."""
    stack, seen = [predecessor_id], set()
    while stack:
        cur = stack.pop()
        if cur == successor_id:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(db.execute(select(TaskDependency.predecessor_id).where(TaskDependency.successor_id == cur)).scalars())
    return False


def would_parent_cycle(db: Session, task_id: uuid.UUID, parent_id: uuid.UUID) -> bool:
    cur: uuid.UUID | None = parent_id
    seen: set[uuid.UUID] = set()
    while cur and cur not in seen:
        if cur == task_id:
            return True
        seen.add(cur)
        cur = db.execute(select(WorkItem.parent_id).where(WorkItem.id == cur)).scalar()
    return False
