"""Due-date reminders for tasks and milestones (architecture §18.1). notify() de-duplicates per day, so reruns are safe."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Milestone, Project, WorkItem
from app.services.notify import notify
from app.services.task_lifecycle import closed_statuses

SOON_DAYS = 2
MILESTONE_RISK_DAYS = 14


def sweep(db: Session, today: date | None = None) -> int:
    today = today or date.today()
    sent = 0
    open_tasks = db.execute(select(WorkItem).where(WorkItem.assignee_id.is_not(None), WorkItem.due_date.is_not(None), WorkItem.status.not_in(closed_statuses(db)), WorkItem.due_date <= today + timedelta(days=SOON_DAYS))).scalars()
    for t in open_tasks:
        late = t.due_date < today
        title = f"{t.key} is {(today - t.due_date).days} day(s) overdue" if late else f"{t.key} is due {t.due_date:%d %b}"
        if notify(db, t.assignee_id, "task.overdue" if late else "task.due", title, t.title, link=f"/tasks?open={t.id}", severity="warning" if late else "info", dedupe_key=f"task-due:{t.id}:{t.due_date}:{late}"):
            sent += 1
    risky = db.execute(select(Milestone).where(Milestone.status.not_in(["ACHIEVED", "CANCELLED"]), Milestone.due_date.is_not(None), Milestone.due_date <= today + timedelta(days=MILESTONE_RISK_DAYS))).scalars()
    for m in risky:
        if not m.owner_id:
            continue
        late = m.due_date < today
        project = db.get(Project, m.project_id)
        title = f"Milestone {m.name} is overdue" if late else f"Milestone {m.name} is due {m.due_date:%d %b}"
        if notify(db, m.owner_id, "milestone.risk", title, project.code if project else None, link=f"/planning/{m.project_id}", severity="warning", dedupe_key=f"milestone:{m.id}:{m.due_date}:{late}"):
            sent += 1
    return sent
