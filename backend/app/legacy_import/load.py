"""Step 2 of the PMS → ADA-ELM migration: load a bundle made by scripts/import_legacy/extract_pms.py.

    python -m app.legacy_import.load pms_bundle.json                 # dry run (default): full load, report, then ROLLBACK
    python -m app.legacy_import.load pms_bundle.json --commit        # keep the data
    python -m app.legacy_import.load --rollback <run-id>             # undo a committed run

Re-running is safe: rows already in legacy_import_map are left alone, so a later bundle adds only what is new.
ELM edits are never overwritten. Existing ELM users with the same username are linked, not changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.db import SessionLocal, utcnow
from app.legacy_import import mapping as mp
from app.models import (
    EngineeringItem,
    HierarchyLevel,
    LegacyAuditRecord,
    LegacyImportMap,
    LegacyImportRun,
    Milestone,
    OrgUnit,
    PlanActivity,
    PlanPhase,
    Project,
    Requirement,
    RequirementBaseline,
    RequirementBaselineItem,
    RequirementEvent,
    RequirementReview,
    RequirementRevision,
    RequirementSource,
    RequirementWorkItem,
    ProjectMember,
    ProjectPlan,
    Role,
    RoleAssignment,
    TaskComment,
    TaskDependency,
    User,
    UserOrgAssignment,
    WorkItem,
    WorkItemEvent,
)
from app.services import audit as auditsvc
from app.services import requirements as rq
from app.services import task_lifecycle as lc
from app.services.numbering import next_seq

SOURCE = "PMS"
# Tables this loader consumes, for the "what was not migrated" inventory. Everything else with rows is reported as deferred.
CONSUMED = {
    "department", "user", "auth_item", "project", "project_user_role", "user_project_mapping", "projectteam", "system", "subsystem", "project_mapping",
    "project_milestone", "milestone", "project_plans", "plan_activities", "masterdata_main", "act_masterdata", "act_task_main", "act_schedule", "task_dependency",
    "task_completion_rule", "states", "record_types", "workflow", "act_dailystatus", "requirements", "baselined_requirements", "baseline", "requirement_review", "log_requirements", "tag_type", "audit_log", "log_activity",
}
# Children before parents, so rollback can delete in this order.
ROLLBACK_ORDER = [
    "legacy_audit_records", "requirement_baseline_items", "requirement_baselines", "requirement_reviews", "requirement_events", "requirement_revisions", "requirement_work_items", "requirements", "requirement_sources",
    "task_comments", "work_item_events", "task_dependencies", "work_items", "plan_activities", "milestones", "project_plans", "plan_phases", "engineering_items", "hierarchy_levels",
    "role_assignments", "project_members", "projects", "user_org_assignments", "users", "org_units",
]


def parse_date(v) -> date | None:
    """None for empty values and MySQL zero dates. Year-out-of-range values such as 2626 in legacy rows stay visible to the date checks."""
    if not v or str(v).startswith("0000"):
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def parse_dt(v, tz=mp.LEGACY_TZ) -> datetime | None:
    if not v or str(v).startswith("0000"):
        return None
    try:
        d = datetime.fromisoformat(str(v))
    except ValueError:
        return None
    return (d.replace(tzinfo=tz) if d.tzinfo is None else d).astimezone(timezone.utc)


def to_float(v) -> float:
    try:
        return max(float(v), 0.0)
    except (TypeError, ValueError):
        return 0.0


def to_int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def clean(v, limit: int | None = None) -> str | None:
    s = str(v).strip() if v is not None else ""
    if not s:
        return None
    return s[:limit] if limit else s


def fingerprint(rows: dict) -> str:
    """Order-independent digest of {target_id: comparable values}."""
    text = json.dumps(sorted(json.dumps([k, v], default=str, sort_keys=True) for k, v in rows.items()))
    return hashlib.sha256(text.encode()).hexdigest()


class Loader:
    def __init__(self, db: Session, bundle: dict, bundle_sha: str, role_map: dict | None = None):
        self.db = db
        self.bundle = bundle
        self.d = bundle["data"]
        self.role_map = role_map or mp.ROLE_MAP
        self.exceptions: list[dict] = []
        self.stats: dict[str, dict] = defaultdict(lambda: {"source": 0, "created": 0, "linked": 0, "already_imported": 0, "skipped": 0})
        self.expected: dict[str, dict] = defaultdict(dict)  # entity → {target id: values derived from the source}
        self.run = LegacyImportRun(source_system=SOURCE, source_database=bundle["source"].get("database"), bundle_sha256=bundle_sha)
        db.add(self.run)
        db.flush()
        self.maps = {(m.source_table, m.source_id): m for m in db.execute(select(LegacyImportMap).where(LegacyImportMap.source_system == SOURCE)).scalars()}
        self.lifecycle = lc.get_lifecycle(db)
        self.states = lc.state_map(self.lifecycle)

    # ------------------------------------------------------------- helpers
    def note(self, severity: str, entity: str, source_id, message: str) -> None:
        self.exceptions.append({"severity": severity, "entity": entity, "source_id": str(source_id), "message": message})

    def target(self, table: str, source_id) -> uuid.UUID | None:
        m = self.maps.get((table, str(source_id)))
        return m.target_id if m else None

    def remember(self, source_table: str, source_id, target_table: str, target_id: uuid.UUID, created: bool = True) -> None:
        m = LegacyImportMap(run_id=self.run.id, source_system=SOURCE, source_table=source_table, source_id=str(source_id), target_table=target_table, target_id=target_id, created=created)
        self.db.add(m)
        self.maps[(source_table, str(source_id))] = m

    def seen(self, entity: str, table: str, source_id) -> bool:
        self.stats[entity]["source"] += 1
        if (table, str(source_id)) in self.maps:
            self.stats[entity]["already_imported"] += 1
            return True
        return False

    def user_id(self, legacy_id) -> uuid.UUID | None:
        return self.target("user", legacy_id) if legacy_id not in (None, "", 0) else None

    # ------------------------------------------------------------- run
    def load(self) -> dict:
        self.departments()
        self.users()
        self.projects()
        self.structure()
        self.memberships()
        self.phases()
        self.plans()
        self.milestones()
        self.activities()
        self.tasks()
        self.dependencies()
        self.requirements()
        self.history()
        self.daily_status()
        self.audit_history()
        self.db.flush()
        self.review_notes()
        report = self.report()
        auditsvc.record(self.db, actor_id=None, action="legacy.import", entity_type="legacy_import_run", entity_id=self.run.id, summary=f"PMS import: {report['totals']['created']} record(s) created from {self.run.source_database}", data={"bundle_sha256": self.run.bundle_sha256, "totals": report["totals"]})
        self.run.report = json.dumps(report, default=str)
        self.run.finished_at = utcnow()
        return report

    def departments(self) -> None:
        root = self.db.execute(select(OrgUnit).where(OrgUnit.parent_id.is_(None)).order_by(OrgUnit.created_at)).scalars().first()
        if root is None:
            raise SystemExit("ELM has no root organization. Run `python -m app.seed` before importing.")
        for r in self.d["department"]:
            if self.seen("org_units", "department", r["id"]):
                continue
            code = f"PMS-DEPT-{r['id']}"
            existing = self.db.execute(select(OrgUnit).where(OrgUnit.code == code)).scalar_one_or_none()
            if existing:
                self.remember("department", r["id"], "org_units", existing.id, created=False)
                self.stats["org_units"]["linked"] += 1
                continue
            o = OrgUnit(id=uuid.uuid4(), code=code, name=clean(r["name"], 200) or code, unit_type="DEPARTMENT", parent_id=root.id, active=bool(r.get("enabled", 1)), description="Imported from PMS; place it under the right directorate.")
            o.path = f"{root.path}{o.id}/"
            self.db.add(o)
            self.db.flush()
            self.remember("department", r["id"], "org_units", o.id)
            self.stats["org_units"]["created"] += 1

    def users(self) -> None:
        existing = {u.username.lower(): u for u in self.db.execute(select(User)).scalars()}
        for r in self.d["user"]:
            if self.seen("users", "user", r["id"]):
                continue
            username = clean(r["username"], 80)
            if not username:
                self.note("ERROR", "users", r["id"], "No username; the user was not imported.")
                self.stats["users"]["skipped"] += 1
                continue
            match = existing.get(username.lower())
            if match:
                self.remember("user", r["id"], "users", match.id, created=False)
                self.stats["users"]["linked"] += 1
                self.note("INFO", "users", r["id"], f"Username {username} already exists in ELM. Linked to it; the ELM account was not changed.")
                continue
            active = r.get("status") == 1 and r.get("employment_status") not in mp.EMPLOYMENT_ENDED
            org = self.target("department", r.get("department_id"))
            name = " ".join(x for x in [clean(r.get("first_name")), clean(r.get("last_name"))] if x) or username
            # Legacy passwords are never carried over. The account cannot sign in until an administrator sets a password or LDAP is enabled.
            u = User(username=username, full_name=name[:200], email=clean(r.get("email"), 200), designation=clean(r.get("designation"), 120), password_hash=None, auth_source="local", is_active=active, is_system_admin=False,
                     primary_org_unit_id=org, last_login_at=parse_dt(r.get("lastLogin")), created_at=parse_dt(r.get("dateCreated")) or utcnow())
            self.db.add(u)
            self.db.flush()
            self.remember("user", r["id"], "users", u.id)
            self.stats["users"]["created"] += 1
            existing[username.lower()] = u
            self.expected["users"][str(u.id)] = [username, active]
            if org:
                a = UserOrgAssignment(user_id=u.id, org_unit_id=org)
                self.db.add(a)
                self.db.flush()
                self.remember("user_department", r["id"], "user_org_assignments", a.id)
            elif r.get("department_id"):
                self.note("WARN", "users", r["id"], f"{username}: department {r['department_id']} does not exist in PMS.")

    def projects(self) -> None:
        for r in self.d["project"]:
            if self.seen("projects", "project", r["id"]):
                continue
            code = clean(r.get("short_code"), 40) or f"PMS-{r['id']}"
            code = "".join(c if c.isalnum() or c in "-_" else "-" for c in code)
            if self.db.execute(select(Project.id).where(Project.code == code)).first():
                self.note("WARN", "projects", r["id"], f"Code {code} is already used in ELM, so this project was imported as PMS-{code}.")
                code = f"PMS-{code}"[:40]
            status = "CLOSED" if not r.get("enabled") else mp.PROJECT_STATUS.get(r.get("status_id"), "ACTIVE")
            p = Project(code=code, name=clean(r["name"], 200) or code, description=clean(r.get("description")), status=status, start_date=parse_date(r.get("start_date")), end_date=parse_date(r.get("end_date")), created_at=parse_dt(r.get("dateCreated")) or utcnow())
            self.db.add(p)
            self.db.flush()
            self.remember("project", r["id"], "projects", p.id)
            self.stats["projects"]["created"] += 1
            self.expected["projects"][str(p.id)] = [code, p.name, str(p.start_date), str(p.end_date)]
            self.note("REVIEW", "projects", r["id"], f"{code}: PMS has no directorate on a project. Set the lead and contributing directorates in ELM.")
            for no, (lv_code, lv_name) in enumerate([("SYSTEM", "System"), ("SUBSYSTEM", "Subsystem")], 1):
                lv = HierarchyLevel(project_id=p.id, level_no=no, code=lv_code, name=lv_name)
                self.db.add(lv)
                self.db.flush()
                self.remember("project_level", f"{r['id']}:{lv_code}", "hierarchy_levels", lv.id)

    def structure(self) -> None:
        """project_mapping (project → system → subsystem) becomes the engineering breakdown."""
        systems = {r["id"]: r for r in self.d["system"]}
        subs = {r["id"]: r for r in self.d["subsystem"]}
        self.subsystem_projects: dict[int, set[int]] = defaultdict(set)
        seen_pairs = set()
        counted: set[str] = set()

        def item(key: str, project_uuid, level_key: str, parent, src) -> uuid.UUID:
            found = self.target("project_item", key)
            if found:
                if key not in counted:
                    counted.add(key)
                    self.stats["engineering_items"]["source"] += 1
                    self.stats["engineering_items"]["already_imported"] += 1
                return found
            counted.add(key)
            self.stats["engineering_items"]["source"] += 1
            lv = self.target("project_level", level_key)
            code = (clean(src.get("short_code"), 60) or f"PMS-{src['id']}")
            if self.db.execute(select(EngineeringItem.id).where(EngineeringItem.project_id == project_uuid, EngineeringItem.code == code)).first():
                code = f"{code}-{src['id']}"[:60]
            it = EngineeringItem(id=uuid.uuid4(), project_id=project_uuid, parent_id=parent.id if parent else None, level_id=lv, code=code, name=clean(src["name"], 200) or code)
            it.path = (parent.path if parent else "/") + f"{it.id}/"
            self.db.add(it)
            self.db.flush()
            self.remember("project_item", key, "engineering_items", it.id)
            self.stats["engineering_items"]["created"] += 1
            return it.id

        for r in self.d["project_mapping"]:
            if r.get("record_status") != 1:
                continue
            pair = (r["project_id"], r["system_id"], r["subsys_id"])
            if pair in seen_pairs:  # one row per version in PMS; the breakdown needs one
                continue
            seen_pairs.add(pair)
            project_uuid = self.target("project", r["project_id"])
            if not project_uuid:
                self.note("WARN", "engineering_items", r["id"], f"project_mapping points at project {r['project_id']}, which does not exist.")
                self.stats["engineering_items"]["source"] += 1
                self.stats["engineering_items"]["skipped"] += 1
                continue
            self.subsystem_projects[r["subsys_id"]].add(r["project_id"])
            parent = None
            if r["system_id"] in systems:
                sid = item(f"{r['project_id']}:S{r['system_id']}", project_uuid, f"{r['project_id']}:SYSTEM", None, systems[r["system_id"]])
                parent = self.db.get(EngineeringItem, sid)
            if r["subsys_id"] in subs:
                if parent is None:
                    self.note("WARN", "engineering_items", r["id"], f"Subsystem {r['subsys_id']} has no valid system, so it sits at the top of the breakdown.")
                item(f"{r['project_id']}:U{r['subsys_id']}", project_uuid, f"{r['project_id']}:SUBSYSTEM", parent, subs[r["subsys_id"]])

    def memberships(self) -> None:
        roles = {r["id"]: r["name"] for r in self.d["auth_item"]}
        elm_roles = {r.code: r for r in self.db.execute(select(Role)).scalars()}
        members: set[tuple] = set()
        rows = [("project_user_role", r["id"], r["project_id"], r["user_id"], r.get("status") == 1) for r in self.d["project_user_role"]]
        rows += [("user_project_mapping", r["id"], r["project_id"], r["user_id"], r.get("record_status") == 1) for r in self.d["user_project_mapping"]]
        rows += [("projectteam", r["id"], r["project_id"], r["user_id"], True) for r in self.d["projectteam"]]
        for table, rid, project, user, active in rows:
            if not active:
                continue
            p, u = self.target("project", project), self.user_id(user)
            if not p or not u:
                self.note("WARN", "project_members", f"{table}:{rid}", f"Refers to project {project} / user {user}, which do not both exist.")
                continue
            key = f"{project}:{user}"
            if (p, u) in members or self.target("project_member", key):
                continue
            members.add((p, u))
            self.stats["project_members"]["source"] += 1
            existing = self.db.execute(select(ProjectMember).where(ProjectMember.project_id == p, ProjectMember.user_id == u)).scalar_one_or_none()
            if existing:
                self.remember("project_member", key, "project_members", existing.id, created=False)
                self.stats["project_members"]["linked"] += 1
                continue
            m = ProjectMember(project_id=p, user_id=u)
            self.db.add(m)
            self.db.flush()
            self.remember("project_member", key, "project_members", m.id)
            self.stats["project_members"]["created"] += 1
        for r in self.d["project_user_role"]:
            if r.get("status") != 1:
                continue
            legacy_role = roles.get(r["role_id"])
            p, u = self.target("project", r["project_id"]), self.user_id(r["user_id"])
            if not p or not u:
                continue
            code = self.role_map.get(legacy_role or "", None)
            self.stats["role_assignments"]["source"] += 1
            if self.target("project_user_role", r["id"]):
                self.stats["role_assignments"]["already_imported"] += 1
                continue
            if not code or code not in elm_roles:
                self.note("REVIEW", "role_assignments", r["id"], f"PMS role '{legacy_role}' for user {r['user_id']} on project {r['project_id']} has no automatic ELM role. Assign one if needed; project membership was imported.")
                self.stats["role_assignments"]["skipped"] += 1
                continue
            role = elm_roles[code]
            dup = self.db.execute(select(RoleAssignment).where(RoleAssignment.user_id == u, RoleAssignment.role_id == role.id, RoleAssignment.scope_type == "PROJECT", RoleAssignment.scope_id == p)).scalar_one_or_none()
            if dup:
                self.remember("project_user_role", r["id"], "role_assignments", dup.id, created=False)
                self.stats["role_assignments"]["linked"] += 1
                continue
            a = RoleAssignment(user_id=u, role_id=role.id, scope_type="PROJECT", scope_id=p)
            self.db.add(a)
            self.db.flush()
            self.remember("project_user_role", r["id"], "role_assignments", a.id)
            self.stats["role_assignments"]["created"] += 1

    def phases(self) -> None:
        shared = {p.code: p for p in self.db.execute(select(PlanPhase).where(PlanPhase.project_id.is_(None))).scalars()}
        for i, r in enumerate(self.d["masterdata_main"]):
            if self.seen("plan_phases", "plan_phase", r["id"]):
                continue
            name = clean(r["name"], 120) or f"Phase {r['id']}"
            code = mp.PHASE_ALIASES.get(name.lower()) or "".join(c if c.isalnum() else "_" for c in name.upper())[:40]
            if code in shared:
                self.remember("plan_phase", r["id"], "plan_phases", shared[code].id, created=False)
                self.stats["plan_phases"]["linked"] += 1
                continue
            f = PlanPhase(code=code, name=name, sort_order=100 + i, weight=1.0, active=r.get("record_status") == 1)
            self.db.add(f)
            self.db.flush()
            shared[code] = f
            self.remember("plan_phase", r["id"], "plan_phases", f.id)
            self.stats["plan_phases"]["created"] += 1

    def plans(self) -> None:
        for r in self.d["project_plans"]:
            if self.seen("project_plans", "project_plans", r["id"]):
                continue
            p = self.target("project", r["project_id"])
            if not p:
                self.note("ERROR", "project_plans", r["id"], f"Plan '{r['name']}' refers to project {r['project_id']}, which does not exist. Not imported.")
                self.stats["project_plans"]["skipped"] += 1
                continue
            status = mp.PLAN_STATUS.get(str(r.get("status")), "DRAFT")
            if status == "ACTIVE" and self.db.execute(select(ProjectPlan.id).where(ProjectPlan.project_id == p, ProjectPlan.status == "ACTIVE")).first():
                self.note("WARN", "project_plans", r["id"], f"Plan '{r['name']}' was active, but its project already has an active plan. Imported as a draft.")
                status = "DRAFT"
            plan = ProjectPlan(project_id=p, name=clean(r["name"], 200) or f"Plan {r['id']}", version_label=clean(r.get("version"), 20) or "1.0", description=clean(r.get("description")), status=status, owner_id=self.user_id(r.get("created_by")), created_by_id=self.user_id(r.get("created_by")), created_at=parse_dt(r.get("created_at")) or utcnow())
            self.db.add(plan)
            self.db.flush()
            self.remember("project_plans", r["id"], "project_plans", plan.id)
            self.stats["project_plans"]["created"] += 1
            self.expected["project_plans"][str(plan.id)] = [plan.name, plan.version_label, status]

    def milestones(self) -> None:
        rows = [("project_milestone", r["id"], r["project_id"], r["milestone_name"], None, r.get("description"), r.get("start_date"), r.get("end_date"), None, r.get("status"), r.get("created_by"), True) for r in self.d["project_milestone"]]
        rows += [("milestone", r["id"], r["project"], r["milestone"], r.get("code"), r.get("description"), r.get("start_date"), r.get("end_date"), r.get("completed_date"), r.get("status"), r.get("created_by"), r.get("record_status") == 1) for r in self.d["milestone"]]
        for table, rid, project, name, code, desc, start, end, achieved, status, created_by, active in rows:
            if self.seen("milestones", table, rid):
                continue
            p = self.target("project", project)
            if not p or not active:
                self.note("WARN", "milestones", f"{table}:{rid}", f"Milestone '{name}' refers to project {project}, which does not exist. Not imported." if not p else f"Milestone '{name}' is inactive in PMS. Not imported.")
                self.stats["milestones"]["skipped"] += 1
                continue
            st = mp.MILESTONE_STATUS.get(status, "PLANNED")
            m = Milestone(project_id=p, code=clean(code, 40), name=clean(name, 200) or f"Milestone {rid}", description=clean(desc), start_date=parse_date(start), due_date=parse_date(end), achieved_date=parse_date(achieved), status=st, owner_id=self.user_id(created_by))
            self.db.add(m)
            self.db.flush()
            self.remember(table, rid, "milestones", m.id)
            self.stats["milestones"]["created"] += 1
            self.expected["milestones"][str(m.id)] = [m.name, str(m.due_date), st]
            if st == "ACHIEVED" and not m.achieved_date:
                self.note("WARN", "milestones", f"{table}:{rid}", f"Milestone '{m.name}' is completed in PMS without a completion date.")

    def activities(self) -> None:
        for r in self.d["plan_activities"]:
            if self.seen("plan_activities", "plan_activities", r["id"]):
                continue
            plan, project = self.target("project_plans", r["plan_id"]), self.target("project", r["project_id"])
            if not plan or not project:
                self.note("ERROR", "plan_activities", r["id"], f"Activity '{r['title']}' refers to a plan or project that was not imported. Not imported.")
                self.stats["plan_activities"]["skipped"] += 1
                continue
            status = mp.ACTIVITY_STATUS.get(str(r.get("status")), "NOT_STARTED")
            start, end = parse_date(r.get("start_date")), parse_date(r.get("end_date"))
            a = PlanActivity(plan_id=plan, project_id=project, phase_id=self.target("plan_phase", r.get("phase_id")), title=clean(r["title"], 300) or f"Activity {r['id']}", description=clean(r.get("description")), owner_id=self.user_id(r.get("assigned_to")),
                             start_date=start, end_date=end, estimated_hours=to_float(r.get("estimated_hours")), priority=mp.PRIORITY.get(str(r.get("priority")), "MEDIUM"), status=status, sort_order=r.get("sort_order") or 0, created_at=parse_dt(r.get("created_at")) or utcnow())
            self.db.add(a)
            self.db.flush()
            self.remember("plan_activities", r["id"], "plan_activities", a.id)
            self.stats["plan_activities"]["created"] += 1
            self.expected["plan_activities"][str(a.id)] = [a.title, str(start), str(end), a.estimated_hours, status]
            if to_float(r.get("progress")) > 0 and status != "COMPLETED":
                self.note("INFO", "plan_activities", r["id"], f"'{a.title}': PMS held a typed progress of {r['progress']}% with status {r.get('status')}. ELM calculates activity progress from its tasks, so that figure was not kept.")
            if to_float(r.get("actual_hours")) > 0:
                self.note("INFO", "plan_activities", r["id"], f"'{a.title}': {r['actual_hours']} actual hours were recorded on the activity. ELM records actual hours on tasks.")

    # ------------------------------------------------------------- tasks
    def _task_project(self, r: dict, tasks: dict, requirement_projects: dict, activity_projects: dict, names: dict, depth: int = 0) -> tuple[int | None, str]:
        """PMS tasks have no project column; PMS reads it from the signed-in user's current project. Reconstruct it from real
        links only, strongest first. When nothing identifies it, the task stays unassigned to a project and is reported."""
        if r.get("plan_activity_id") and r["plan_activity_id"] in activity_projects:
            return activity_projects[r["plan_activity_id"]], "activity"
        rid = to_int(r.get("req_id"))
        if rid and requirement_projects.get(rid) in names:
            return names[requirement_projects[rid]], "requirement"
        parent = tasks.get(r.get("paret_task_id"))
        if parent and depth < 20:
            pid, how = self._task_project(parent, tasks, requirement_projects, activity_projects, names, depth + 1)
            if pid:
                return pid, f"parent/{how}"
        sub = self._subsystem_id(r.get("sub_system"))
        if sub and len(self.subsystem_projects.get(sub, ())) == 1:
            return next(iter(self.subsystem_projects[sub])), "subsystem"
        return None, "unresolved"

    def _subsystem_id(self, raw) -> int | None:
        """sub_system holds an id in some rows and a name in others."""
        v = clean(raw)
        if not v:
            return None
        as_int = to_int(v)
        ids = {r["id"] for r in self.d["subsystem"]}
        if as_int in ids:
            return as_int
        return next((r["id"] for r in self.d["subsystem"] if (r.get("name") or "").strip().lower() == v.lower()), None)

    def tasks(self) -> None:
        tasks = {r["id"]: r for r in self.d["act_task_main"]}
        schedule = {}
        for s in self.d["act_schedule"]:
            if s.get("record_status") in ("Y", "1", 1, None) or s["task_id"] not in schedule:
                schedule[s["task_id"]] = s
        states = {str(s["state_id"]): s for s in self.d["states"]}
        record_types = {r["record_type_id"]: r["record_type"] for r in self.d["record_types"]}
        priorities = {r["id"]: str(r["name"]).upper() for r in self.d["act_masterdata"]}
        requirement_projects = {r["id"]: r["project"] for r in self.d["requirements"]}
        activity_projects = {r["id"]: r["project_id"] for r in self.d["plan_activities"]}
        names = {str(p["name"]): p["id"] for p in self.d["project"]}
        created: dict[int, WorkItem] = {}
        for r in sorted(tasks.values(), key=lambda x: x["id"]):
            if self.seen("work_items", "act_task_main", r["id"]):
                continue
            if r.get("record_status") not in ("Y", "1"):
                self.note("INFO", "work_items", r["id"], f"Task is marked deleted in PMS (record_status {r.get('record_status')}). Not imported.")
                self.stats["work_items"]["skipped"] += 1
                continue
            legacy_project, how = self._task_project(r, tasks, requirement_projects, activity_projects, names)
            project = self.target("project", legacy_project) if legacy_project else None
            if not project:
                self.note("REVIEW", "work_items", r["id"], f"Could not determine the project of task {r.get('task_id')} ('{clean(r.get('name'), 60)}'). It was imported with no project; only its assignee and reporter can see it.")
            state = states.get(str(r.get("state")))
            state_name = state["name"] if state else None
            status = mp.map_state(state_name, state.get("state_status") if state else None)
            if status is None or status not in self.states:
                self.note("REVIEW", "work_items", r["id"], f"PMS state '{state_name or r.get('state')}' has no mapping. The task was imported as {lc.initial_state(self.lifecycle)}.")
                status = lc.initial_state(self.lifecycle)
            s = schedule.get(r["id"], {})
            if not s:
                self.note("INFO", "work_items", r["id"], "Task has no schedule row in PMS, so it has no assignee or dates.")
            start = parse_date(s.get("plan_start_date"))
            raw_due = s.get("plan_end_date")
            due = parse_date(raw_due) or parse_date(s.get("exp_dev_complete"))
            if raw_due and not parse_date(raw_due):
                self.note("WARN", "work_items", r["id"], f"Invalid planned end date '{raw_due}'" + (f"; used the expected completion date {due}." if due else "; no due date was set."))
            if start and due and due < start:
                self.note("WARN", "work_items", r["id"], f"Due date {due} is before start date {start} in PMS. Kept as is; correct it in the plan.")
            priority_id = to_int(s.get("priority"))
            priority = priorities.get(priority_id)
            if priority not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
                if s.get("priority") is not None:
                    self.note("INFO", "work_items", r["id"], f"PMS priority value {s.get('priority')} is unknown; used MEDIUM.")
                priority = "MEDIUM"
            title = clean(r.get("name")) or f"Task {r['id']}"
            description = clean(r.get("description"))
            if len(title) > 300:  # PMS titles are long text; keep the whole text in the description
                description = f"{title}\n\n{description or ''}".strip()
                title = title[:297] + "..."
            record_type = record_types.get(r.get("task_type_id"))
            prefix = self.db.get(Project, project).code if project else "TSK"
            activity = self.target("plan_activities", r.get("plan_activity_id"))
            plan = self.db.get(PlanActivity, activity).plan_id if activity else None
            created_at = parse_dt(r.get("created_on"), timezone.utc) or utcnow()
            category = self.states[status]["category"]
            modified = parse_dt(r.get("modified_on"))
            w = WorkItem(key=f"{prefix}-{next_seq(self.db, 'wi:' + prefix)}", title=title, description=description, kind="ACTION" if record_type in mp.ACTION_RECORD_TYPES else "TASK", status=status, priority=priority, project_id=project,
                         item_id=self._task_item(r, legacy_project), assignee_id=self.user_id(s.get("assigned_to")), reporter_id=self.user_id(r.get("created_by")), start_date=start, due_date=due, plan_id=plan, activity_id=activity,
                         milestone_id=self.target("project_milestone", r.get("mile_stone")), estimated_hours=to_float(s.get("estimation_hr")), legacy_key=clean(r.get("task_id"), 80), legacy_type=clean(record_type, 60),
                         progress=lc.calculate_progress(category, 0), created_at=created_at, completed_at=(modified or created_at) if category == "DONE" else None)
            self.db.add(w)
            self.db.flush()
            self.remember("act_task_main", r["id"], "work_items", w.id)
            self.stats["work_items"]["created"] += 1
            created[r["id"]] = w
            self.expected["work_items"][str(w.id)] = [title, status, priority, str(start), str(due), w.estimated_hours, str(w.assignee_id), str(w.reporter_id), str(project), w.legacy_key]
            reason = clean(r.get("holding_reason")) if status == "ON_HOLD" else clean(r.get("shortclose_reason")) if status == "CANCELLED" else None
            self.db.add(WorkItemEvent(work_item_id=w.id, actor_id=w.reporter_id, kind="CREATED", to_value=status, comment=f"Imported from PMS (state {state_name}; project found through: {how})." + (f" Reason: {reason}" if reason else ""), at=created_at))
        for lid, w in created.items():
            parent = tasks[lid].get("paret_task_id")
            if not parent:
                continue
            target = self.target("act_task_main", parent)
            if not target:
                self.note("WARN", "work_items", lid, f"Parent task {parent} does not exist in PMS. Imported without a parent.")
                continue
            w.parent_id = target
        self.db.flush()
        for w in created.values():
            if w.project_id and w.parent_id:
                pr = self.db.get(WorkItem, w.parent_id)
                if pr.project_id != w.project_id:
                    self.note("WARN", "work_items", w.legacy_key, f"Parent and child resolved to different projects ({w.key} under {pr.key}).")
            lc.refresh_progress(self.db, w)

    def _task_item(self, r: dict, legacy_project: int | None) -> uuid.UUID | None:
        if not legacy_project:
            return None
        sub = self._subsystem_id(r.get("sub_system"))
        if sub:
            found = self.target("project_item", f"{legacy_project}:U{sub}")
            if found:
                return found
        system = to_int(r.get("act_system"))
        return self.target("project_item", f"{legacy_project}:S{system}") if system else None

    def dependencies(self) -> None:
        for r in self.d["task_dependency"]:
            if self.seen("task_dependencies", "task_dependency", r["id"]):
                continue
            succ, pred = self.target("act_task_main", r["task_id"]), self.target("act_task_main", r["predecessor_id"])
            if not succ or not pred:
                self.note("WARN", "task_dependencies", r["id"], f"Dependency {r['predecessor_id']} → {r['task_id']} refers to a task that was not imported.")
                self.stats["task_dependencies"]["skipped"] += 1
                continue
            if succ == pred or lc.would_cycle(self.db, succ, pred):
                self.note("ERROR", "task_dependencies", r["id"], f"Dependency {r['predecessor_id']} → {r['task_id']} would create a loop. Not imported.")
                self.stats["task_dependencies"]["skipped"] += 1
                continue
            if self.db.execute(select(TaskDependency.id).where(TaskDependency.successor_id == succ, TaskDependency.predecessor_id == pred)).first():
                self.note("INFO", "task_dependencies", r["id"], "A second dependency between the same two tasks with a different type; ELM keeps one link per pair.")
                self.stats["task_dependencies"]["skipped"] += 1
                continue
            d = TaskDependency(successor_id=succ, predecessor_id=pred, dep_type=r.get("type") or "FS", lag_days=r.get("lag_days") or 0, created_by_id=self.user_id(r.get("created_by")))
            self.db.add(d)
            self.db.flush()
            self.remember("task_dependency", r["id"], "task_dependencies", d.id)
            self.stats["task_dependencies"]["created"] += 1
            self.expected["task_dependencies"][str(d.id)] = [str(succ), str(pred), d.dep_type, d.lag_days]

    def history(self) -> None:
        """workflow rows are the only PMS record of state changes. object_id is only unique within a record type."""
        tasks = {r["id"]: r for r in self.d["act_task_main"]}
        states = {str(s["state_id"]): s["name"] for s in self.d["states"]}
        for r in self.d["workflow"]:
            task = tasks.get(r["object_id"])
            if not task or task.get("task_type_id") != r.get("record_type_id"):
                continue  # belongs to another record type (requirement, test case...), a later phase
            if self.seen("work_item_events", "workflow", r["workflow_id"]):
                continue
            w = self.target("act_task_main", r["object_id"])
            if not w:
                self.stats["work_item_events"]["skipped"] += 1
                continue
            e = WorkItemEvent(work_item_id=w, actor_id=self.user_id(r.get("from_user")), kind="LEGACY_STATE", to_value=clean(states.get(str(r.get("current_state")), r.get("current_state")), 100), at=parse_dt(r.get("created_date")) or utcnow())
            self.db.add(e)
            self.db.flush()
            self.remember("workflow", r["workflow_id"], "work_item_events", e.id)
            self.stats["work_item_events"]["created"] += 1

    def daily_status(self) -> None:
        hours: dict[uuid.UUID, float] = defaultdict(float)
        for r in self.d["act_dailystatus"]:
            if self.seen("task_comments", "act_dailystatus", r["id"]):
                continue
            w = self.target("act_task_main", r["activity_id"])
            if not w:
                self.note("WARN", "task_comments", r["id"], f"Daily status refers to task {r['activity_id']}, which was not imported.")
                self.stats["task_comments"]["skipped"] += 1
                continue
            worked = to_float(r.get("availed_work_hr"))
            hours[w] += worked
            parts = [clean(r.get("remarks")) or "(no remarks)"]
            if clean(r.get("review_remarks")):
                parts.append(f"Review: {clean(r['review_remarks'])}")
            c = TaskComment(work_item_id=w, author_id=self.user_id(r.get("created_by")), body=f"[Daily status, {worked:g} h] " + " | ".join(parts), created_at=parse_dt(r.get("created_on")) or utcnow())
            self.db.add(c)
            self.db.flush()
            self.remember("act_dailystatus", r["id"], "task_comments", c.id)
            self.stats["task_comments"]["created"] += 1
        for wid, h in hours.items():
            self.db.get(WorkItem, wid).actual_hours += h

    def audit_history(self) -> None:
        for table in ("audit_log", "log_activity"):
            for r in self.d[table]:
                if self.seen("legacy_audit_records", table, r["id"]):
                    continue
                if table == "audit_log":
                    details = {k: r.get(k) for k in ("old_value", "new_value", "remarks", "module", "project_id") if r.get(k) not in (None, "")}
                    rec = LegacyAuditRecord(source_system=SOURCE, source_table=table, source_id=str(r["id"]), at=parse_dt(r.get("created_at")), username=clean(r.get("username"), 250), action=clean(r.get("action"), 100), entity_type=clean(r.get("entity_type"), 100), entity_id=clean(r.get("entity_id"), 100), details=json.dumps(details, default=str))
                else:
                    rec = LegacyAuditRecord(source_system=SOURCE, source_table=table, source_id=str(r["id"]), at=parse_dt(r.get("created_at")), username=str(r.get("user_id")), action=clean(r.get("activity"), 100), entity_id=clean(r.get("activity_id"), 100), details=clean(r.get("description")))
                self.db.add(rec)
                self.db.flush()
                self.remember(table, r["id"], "legacy_audit_records", rec.id)
                self.stats["legacy_audit_records"]["created"] += 1

    def review_notes(self) -> None:
        roles = {r["id"]: r["name"] for r in self.d["auth_item"]}
        admins = [clean(u.get("username")) for u in self.d["user"] if roles.get(u.get("user_level")) == "admin"]
        if admins:
            self.note("REVIEW", "users", "-", f"PMS administrators, not made ELM system administrators automatically: {', '.join(a for a in admins if a)}.")
        created_users = self.stats["users"]["created"]
        if created_users:
            self.note("REVIEW", "users", "-", f"{created_users} imported account(s) cannot sign in yet. PMS passwords are not migrated; set passwords in Users & access, or enable LDAP.")
        for r in self.d["task_completion_rule"]:
            if r.get("rule_key") == "no_open_defects" and r.get("enabled"):
                self.note("REVIEW", "settings", r["id"], "PMS enforces 'no open defects' before closure. ELM cannot check this until the defect module (architecture §13) exists.")
            if r.get("rule_key") == "child_tasks_completed" and not r.get("enabled"):
                self.note("REVIEW", "settings", r["id"], "PMS has the 'child tasks closed' rule switched off, but ELM enforces it by default. Change the ELM rule if PMS behaviour should stay.")

    # ------------------------------------------------------------- requirements
    def _project_by_label(self, label) -> int | None:
        """requirements.project holds a project name in most rows, a short code in others, in mixed case."""
        v = (clean(label) or "").lower()
        for p in self.d["project"]:
            if (clean(p.get("name")) or "").lower() == v or (clean(p.get("short_code")) or "").lower() == v:
                return p["id"]
        return None

    def requirements(self) -> None:
        rows = self.d.get("requirements", [])
        if rows and "requirement_tag" not in rows[0]:
            self.note("WARN", "requirements", "-", "This bundle was made by an older extractor and has no requirement data. Extract again to migrate requirements.")
            return
        evidence = {(self._project_by_label(b.get("project")), clean(b.get("requirement_tag"))) for b in self.d.get("baselined_requirements", [])}
        tag_counts: dict = defaultdict(int)
        for r in rows:
            tag_counts[(self._project_by_label(r.get("project")), clean(r.get("requirement_tag")))] += 1
        created: dict[int, Requirement] = {}
        by_tag: dict = defaultdict(list)
        for r in sorted(rows, key=lambda x: x["id"]):
            if self.seen("requirements", "requirements", r["id"]):
                continue
            legacy_project = self._project_by_label(r.get("project"))
            project = self.target("project", legacy_project) if legacy_project else None
            tag = clean(r.get("requirement_tag"), 100)
            if not project or not tag:
                self.note("ERROR", "requirements", r["id"], f"Requirement {tag or '(no tag)'} refers to project '{r.get('project')}', which does not exist, or has no tag. Not imported.")
                self.stats["requirements"]["skipped"] += 1
                continue
            if clean(r.get("delete_ver")):
                self.note("INFO", "requirements", r["id"], f"{tag} is marked deleted in version {r['delete_ver']} in PMS. Not imported.")
                self.stats["requirements"]["skipped"] += 1
                continue
            key = tag
            if tag_counts[(legacy_project, tag)] > 1:
                key = f"{tag}~{r['id']}"
                self.note("REVIEW", "requirements", r["id"], f"Tag {tag} is used by {tag_counts[(legacy_project, tag)]} PMS requirements in this project. Imported as {key}; merge them if they are the same requirement.")
            state = clean(r.get("states")) or ""
            status = mp.REQUIREMENT_STATE.get(state.lower())
            if status is None:
                self.note("REVIEW", "requirements", r["id"], f"{tag}: PMS state '{state}' has no mapping. Imported as DRAFT.")
                status = "DRAFT"
            if status == "BASELINED" and (legacy_project, tag) not in evidence:
                self.note("REVIEW", "requirements", r["id"], f"{tag} is Baselined in PMS, but no baseline contains it. Imported as APPROVED.")
                status = "APPROVED"
            if status in ("APPROVED", "BASELINED", "UNDER_REVIEW"):
                self.note("INFO", "requirements", r["id"], f"{tag}: state {state} was carried over from PMS. It was not approved through ELM's review, so no ELM review decision exists for it.")
            source = self._requirement_source(project, legacy_project, r)
            suffix = next((s for s in mp.REQUIREMENT_TYPE_SUFFIX if (clean(r.get("tag")) or "").upper().endswith(s)), "REQ")
            title = clean(r.get("name")) or tag
            description = clean(r.get("description"))
            if len(title) > 500:
                description = f"{title}\n\n{description or ''}".strip()
                title = title[:497] + "..."
            raw_priority = (clean(r.get("priority")) or "").lower()
            priority = mp.REQUIREMENT_PRIORITY.get(raw_priority, "MEDIUM")
            if raw_priority and raw_priority not in mp.REQUIREMENT_PRIORITY:
                self.note("INFO", "requirements", r["id"], f"{tag}: priority '{r.get('priority')}' is unknown; used MEDIUM.")
            req_type = mp.REQUIREMENT_TYPE_SUFFIX[suffix]
            # PMS records no requirement owner and guessing one would be wrong, so an owner is chosen in ELM before review.
            x = Requirement(project_id=project, source_id=source, key=key, title=title, description=description, req_type=req_type, priority=priority, status=status, owner_id=None, content_sha256=rq.content_hash(title, description, None, req_type, priority), external_id=tag, external_version=clean(r.get("csci_version"), 80), created_at=parse_dt(r.get("dateCreated")) or utcnow())
            self.db.add(x)
            self.db.flush()
            self.remember("requirements", r["id"], "requirements", x.id)
            self.stats["requirements"]["created"] += 1
            created[r["id"]] = x
            by_tag[(project, tag)].append((r, x))
            self.expected["requirements"][str(x.id)] = [key, title, status, priority, req_type, str(project), x.content_sha256]
            rev = RequirementRevision(requirement_id=x.id, revision=1, title=title, description=description, req_type=req_type, priority=priority, content_sha256=x.content_sha256, change_reason="Imported from PMS", created_at=x.created_at)
            self.db.add(rev)
            self.db.flush()
            self.remember("requirements_revision", r["id"], "requirement_revisions", rev.id)
            e = RequirementEvent(requirement_id=x.id, kind="IMPORTED", to_value=status, comment=f"Imported from PMS. Tag {tag}, version {r.get('csci_version')}, state {state}.", at=x.created_at)
            self.db.add(e)
            self.db.flush()
            self.remember("requirements_event", r["id"], "requirement_events", e.id)
        # Hierarchy lives in the tag: AWSSSSREQ6.1.2 sits under AWSSSSREQ6.1. Prefer a parent from the same version.
        for r, x in [v for vals in by_tag.values() for v in vals]:
            tag = clean(r["requirement_tag"])
            if "." not in tag:
                continue
            parents = by_tag.get((x.project_id, tag.rsplit(".", 1)[0]), [])
            if not parents:
                self.note("INFO", "requirements", r["id"], f"{tag}: its parent tag is not among the imported requirements, so it has no parent.")
                continue
            same = [p for p in parents if p[0].get("csci_version") == r.get("csci_version")]
            x.parent_id = (same or parents)[0][1].id
        self.db.flush()
        if created:
            self.note("REVIEW", "requirements", "-", f"{len(created)} requirement(s) have no owner because PMS does not record one. Choose an owner before submitting them for review.")
        self._requirement_task_links()
        self._requirement_baselines()
        self._requirement_reviews()
        self._requirement_history()

    def _requirement_source(self, project: uuid.UUID, legacy_project: int, r: dict) -> uuid.UUID:
        doc = clean(r.get("document"), 300) or "PMS requirements"
        key = f"{legacy_project}:{doc}"
        found = self.target("requirement_source", key)
        if found:
            return found
        src = RequirementSource(project_id=project, name=doc, source_system="PMS", external_ref=doc, key_prefix=(clean(r.get("tag"), 40) or "PMS"))
        self.db.add(src)
        self.db.flush()
        self.remember("requirement_source", key, "requirement_sources", src.id)
        self.stats["requirement_sources"]["source"] += 1
        self.stats["requirement_sources"]["created"] += 1
        return src.id

    def _requirement_task_links(self) -> None:
        for t in self.d["act_task_main"]:
            rid = to_int(t.get("req_id"))
            if not rid or t.get("record_status") not in ("Y", "1"):
                continue
            key = f"{t['id']}:{rid}"
            if self.seen("requirement_task_links", "act_task_req", key):
                continue
            req, task = self.target("requirements", rid), self.target("act_task_main", t["id"])
            if not req or not task:
                self.note("WARN", "requirement_task_links", key, f"Task {t.get('task_id')} refers to requirement {rid}, which was not imported.")
                self.stats["requirement_task_links"]["skipped"] += 1
                continue
            link = RequirementWorkItem(requirement_id=req, work_item_id=task, link_type="implements")
            self.db.add(link)
            self.db.flush()
            self.remember("act_task_req", key, "requirement_work_items", link.id)
            self.stats["requirement_task_links"]["created"] += 1

    def _requirement_baselines(self) -> None:
        """baselined_requirements are snapshots: they migrate as written, whatever the requirement's state is today."""
        groups: dict = defaultdict(list)
        for b in self.d.get("baselined_requirements", []):
            groups[(self._project_by_label(b.get("project")), clean(b.get("baseline_name")) or "(unnamed)")].append(b)
        ordered = sorted(groups.items(), key=lambda kv: min(str(x.get("dateCreated") or "") for x in kv[1]))
        for (legacy_project, name), rows in ordered:
            key = f"{legacy_project}:{name}"
            if self.seen("requirement_baselines", "baseline", key):
                continue
            project = self.target("project", legacy_project) if legacy_project else None
            if not project:
                self.note("ERROR", "requirement_baselines", key, f"Baseline '{name}' refers to a project that does not exist. Not imported.")
                self.stats["requirement_baselines"]["skipped"] += 1
                continue
            seq = (self.db.execute(select(func.max(RequirementBaseline.seq)).where(RequirementBaseline.project_id == project)).scalar() or 0) + 1
            at = parse_dt(min(str(x.get("dateCreated") or "") for x in rows)) or utcnow()
            base = RequirementBaseline(project_id=project, seq=seq, label=name[:300], reason="Imported from PMS.", sha256="", created_at=at)
            self.db.add(base)
            self.db.flush()
            self.remember("baseline", key, "requirement_baselines", base.id)
            self.stats["requirement_baselines"]["created"] += 1
            items = []
            for b in rows:
                tag = clean(b.get("requirement_tag"), 100) or f"PMS-{b['id']}"
                live = self.db.execute(select(Requirement).where(Requirement.project_id == project, Requirement.external_id == tag).order_by(Requirement.key)).scalars().all()
                same = [x for x in live if x.external_version == clean(b.get("csci_version"), 80)]
                match = (same or live or [None])[0]
                title = (clean(b.get("name")) or tag)[:500]
                description = clean(b.get("description"))
                priority = mp.REQUIREMENT_PRIORITY.get((clean(b.get("priority")) or "").lower(), "MEDIUM")
                revision = to_int(b.get("req_baseline_version")) or 1
                if not match:
                    self.note("WARN", "requirement_baselines", b["id"], f"Baseline '{name}' holds {tag}, which is not among the imported requirements. The snapshot was kept.")
                req_type = match.req_type if match else "FUNCTIONAL"
                item = RequirementBaselineItem(baseline_id=base.id, requirement_id=match.id if match else None, key=match.key if match else tag, revision=revision, title=title, description=description, req_type=req_type, priority=priority, content_sha256=rq.content_hash(title, description, None, req_type, priority))
                self.db.add(item)
                self.db.flush()
                self.remember("baselined_requirements", b["id"], "requirement_baseline_items", item.id)
                self.stats["requirement_baseline_items"]["source"] += 1
                self.stats["requirement_baseline_items"]["created"] += 1
                items.append(item)
                self.expected["requirement_baseline_items"][str(item.id)] = [item.key, revision, title, item.content_sha256]
            base.sha256 = rq.seal_items(items)

    def _requirement_reviews(self) -> None:
        """requirement_review.status is undocumented, so past decisions are not inferred from it. A requirement that is under
        review today gets its assigned people as pending decisions on the imported revision; all others keep them as history."""
        for v in self.d.get("requirement_review", []):
            if self.seen("requirement_reviews", "requirement_review", v["id"]):
                continue
            req_id, user = self.target("requirements", v.get("requirement_id")), self.user_id(v.get("user_id"))
            if not req_id or not user:
                self.stats["requirement_reviews"]["skipped"] += 1
                self.note("INFO", "requirement_reviews", v["id"], f"Review assignment refers to requirement {v.get('requirement_id')} or user {v.get('user_id')}, which were not imported.")
                continue
            x = self.db.get(Requirement, req_id)
            role = "APPROVER" if v.get("approver") == 2 else "REVIEWER"
            at = parse_dt(v.get("created_at")) or utcnow()
            if x.status == "UNDER_REVIEW":
                dup = self.db.execute(select(RequirementReview.id).where(RequirementReview.requirement_id == req_id, RequirementReview.reviewer_id == user, RequirementReview.role == role)).first()
                if dup:
                    self.stats["requirement_reviews"]["skipped"] += 1
                    continue
                row = RequirementReview(requirement_id=req_id, revision=1, content_sha256=x.content_sha256, cycle=1, reviewer_id=user, role=role, created_at=at)
                table = "requirement_reviews"
            else:
                row = RequirementEvent(requirement_id=req_id, actor_id=user, kind="LEGACY_REVIEW", to_value=role, comment=f"Assigned as {role.lower()} in PMS (PMS status code {v.get('status')}).", at=at)
                table = "requirement_events"
            self.db.add(row)
            self.db.flush()
            self.remember("requirement_review", v["id"], table, row.id)
            self.stats["requirement_reviews"]["created"] += 1

    def _requirement_history(self) -> None:
        """log_requirements holds a row per update; only actual state changes become history."""
        last: dict = {}
        for v in sorted(self.d.get("log_requirements", []), key=lambda x: (str(x.get("trigger_date") or ""), x["id"])):
            rid, state = v.get("requirement_id"), clean(v.get("states"), 100)
            if state == last.get(rid) or v.get("action") != "UPDATE":
                continue
            previous = last.get(rid)
            last[rid] = state
            req_id = self.target("requirements", rid)
            if not req_id or previous is None:
                continue
            if self.seen("requirement_history", "log_requirements", v["id"]):
                continue
            e = RequirementEvent(requirement_id=req_id, kind="LEGACY_STATE", from_value=previous, to_value=state, at=parse_dt(v.get("trigger_date")) or utcnow())
            self.db.add(e)
            self.db.flush()
            self.remember("log_requirements", v["id"], "requirement_events", e.id)
            self.stats["requirement_history"]["created"] += 1

    # ------------------------------------------------------------- report
    def _actual(self, entity: str) -> dict:
        rows: dict = {}
        target = {"users": User, "projects": Project, "project_plans": ProjectPlan, "milestones": Milestone, "plan_activities": PlanActivity, "work_items": WorkItem, "task_dependencies": TaskDependency, "requirements": Requirement, "requirement_baseline_items": RequirementBaselineItem}[entity]
        for tid in self.expected[entity]:
            o = self.db.get(target, uuid.UUID(tid))
            if o is None:
                continue
            if entity == "users":
                rows[tid] = [o.username, o.is_active]
            elif entity == "projects":
                rows[tid] = [o.code, o.name, str(o.start_date), str(o.end_date)]
            elif entity == "requirements":
                rows[tid] = [o.key, o.title, o.status, o.priority, o.req_type, str(o.project_id), o.content_sha256]
            elif entity == "requirement_baseline_items":
                rows[tid] = [o.key, o.revision, o.title, o.content_sha256]
            elif entity == "project_plans":
                rows[tid] = [o.name, o.version_label, o.status]
            elif entity == "milestones":
                rows[tid] = [o.name, str(o.due_date), o.status]
            elif entity == "plan_activities":
                rows[tid] = [o.title, str(o.start_date), str(o.end_date), o.estimated_hours, o.status]
            elif entity == "work_items":
                rows[tid] = [o.title, o.status, o.priority, str(o.start_date), str(o.due_date), o.estimated_hours, str(o.assignee_id), str(o.reporter_id), str(o.project_id), o.legacy_key]
            else:
                rows[tid] = [str(o.successor_id), str(o.predecessor_id), o.dep_type, o.lag_days]
        return rows

    def report(self) -> dict:
        self.db.flush()
        self.db.expire_all()
        recon = {}
        for entity in sorted(self.expected):
            exp, act = self.expected[entity], self._actual(entity)
            bad = [k for k in exp if json.dumps(exp[k], default=str) != json.dumps(act.get(k), default=str)]
            recon[entity] = {"rows": len(exp), "source_sha256": fingerprint(exp), "target_sha256": fingerprint(act), "match": not bad and fingerprint(exp) == fingerprint(act), "mismatches": bad[:20]}
        deferred = {t: n for t, n in sorted(self.bundle["inventory"].items()) if n and t not in CONSUMED}
        unbalanced = {}
        for k, v in self.stats.items():
            if k in ("legacy_audit_records",):
                continue
            if v["source"] != v["created"] + v["linked"] + v["already_imported"] + v["skipped"]:
                unbalanced[k] = v
        counts = defaultdict(int)
        for e in self.exceptions:
            counts[e["severity"]] += 1
        return {
            "run_id": str(self.run.id), "source": self.bundle["source"], "bundle_sha256": self.run.bundle_sha256, "generated_at": utcnow().isoformat(),
            "totals": {"created": sum(v["created"] for v in self.stats.values()), "linked": sum(v["linked"] for v in self.stats.values()), "already_imported": sum(v["already_imported"] for v in self.stats.values()), "skipped": sum(v["skipped"] for v in self.stats.values()), "exceptions": dict(counts)},
            "entities": {k: dict(v) for k, v in sorted(self.stats.items())}, "reconciliation": recon, "unbalanced_counts": unbalanced, "missing_source_tables": self.bundle.get("missing_tables", []),
            "exceptions": self.exceptions, "deferred_tables": deferred,
            "ok": not unbalanced and all(r["match"] for r in recon.values()) and not counts.get("ERROR"),
        }


# ------------------------------------------------------------------ rollback
def rollback(db: Session, run_id: uuid.UUID, force: bool) -> dict:
    run = db.get(LegacyImportRun, run_id)
    if run is None:
        raise SystemExit(f"No import run {run_id}.")
    if run.status != "COMMITTED":
        raise SystemExit(f"Run {run_id} is already {run.status}.")
    later = db.execute(select(LegacyImportRun).join(LegacyImportMap, LegacyImportMap.run_id == LegacyImportRun.id).where(LegacyImportRun.started_at > run.started_at, LegacyImportRun.status == "COMMITTED").distinct()).scalars().first()
    if later:
        raise SystemExit(f"Run {later.id} imported records after this one and may depend on it. Roll that run back first.")
    rows = db.execute(select(LegacyImportMap).where(LegacyImportMap.run_id == run.id)).scalars().all()
    by_table: dict[str, list[LegacyImportMap]] = defaultdict(list)
    for r in rows:
        by_table[r.target_table].append(r)
    created = {t: [m.target_id for m in ms if m.created] for t, ms in by_table.items()}
    # Refuse when anyone has worked on the imported records since: silently deleting that work would be worse than stopping.
    problems: list[str] = []
    task_ids = created.get("work_items", [])
    for w in db.execute(select(WorkItem).where(WorkItem.id.in_(task_ids))).scalars() if task_ids else []:
        if w.version > 1:
            problems.append(f"Task {w.key} was changed after the import.")
    if task_ids:
        known = set(created.get("task_comments", [])) | set(created.get("work_item_events", []))
        for c in db.execute(select(TaskComment.id).where(TaskComment.work_item_id.in_(task_ids))).scalars():
            if c not in known:
                problems.append(f"A comment {c} was added to an imported task.")
        for e in db.execute(select(WorkItemEvent).where(WorkItemEvent.work_item_id.in_(task_ids), WorkItemEvent.kind != "CREATED")).scalars():
            if e.id not in known:
                problems.append(f"Task history {e.id} was added to an imported task.")
    req_ids = created.get("requirements", [])
    for x in db.execute(select(Requirement).where(Requirement.id.in_(req_ids))).scalars() if req_ids else []:
        if x.version > 1:
            problems.append(f"Requirement {x.key} was changed after the import.")
    since = run.finished_at or run.started_at
    user_ids = created.get("users", [])
    for u in db.execute(select(User).where(User.id.in_(user_ids))).scalars() if user_ids else []:
        if u.password_hash:
            problems.append(f"User {u.username} has been given a password since the import.")
        if u.updated_at and since and u.updated_at.replace(tzinfo=None) > since.replace(tzinfo=None):
            problems.append(f"User {u.username} was changed after the import.")
    if problems and not force:
        raise SystemExit("Rollback refused; these records have been used since the import (use --force to delete them anyway):\n  " + "\n  ".join(problems[:40]))
    tables = {m.__tablename__: m for m in [RequirementBaselineItem, RequirementBaseline, RequirementReview, RequirementEvent, RequirementRevision, RequirementWorkItem, Requirement, RequirementSource, LegacyAuditRecord, TaskComment, WorkItemEvent, TaskDependency, WorkItem, PlanActivity, Milestone, ProjectPlan, PlanPhase, EngineeringItem, HierarchyLevel, RoleAssignment, ProjectMember, Project, UserOrgAssignment, User, OrgUnit]}
    if task_ids:
        for model, col in ((WorkItemEvent, WorkItemEvent.work_item_id), (TaskComment, TaskComment.work_item_id)):
            for o in db.execute(select(model).where(col.in_(task_ids))).scalars():
                db.delete(o)
        for w in db.execute(select(WorkItem).where(WorkItem.id.in_(task_ids))).scalars():
            w.parent_id = None
        db.flush()
    req_ids = created.get("requirements", [])
    for x in db.execute(select(Requirement).where(Requirement.id.in_(req_ids))).scalars() if req_ids else []:
        x.parent_id = None  # self-referencing, so unlink before deleting
    db.flush()
    item_ids = created.get("engineering_items", [])
    for i in db.execute(select(EngineeringItem).where(EngineeringItem.id.in_(item_ids))).scalars() if item_ids else []:
        i.parent_id = None  # self-referencing, so unlink before deleting
    db.flush()
    removed: dict[str, int] = {}
    for table in ROLLBACK_ORDER:
        ids = created.get(table, [])
        if table in ("work_item_events", "task_comments") and task_ids:
            removed[table] = len(ids)
            continue
        n = 0
        for o in db.execute(select(tables[table]).where(tables[table].id.in_(ids))).scalars() if ids else []:
            db.delete(o)
            n += 1
        db.flush()
        if n:
            removed[table] = n
    for r in rows:
        db.delete(r)
    run.status = "ROLLED_BACK"
    auditsvc.record(db, actor_id=None, action="legacy.import.rollback", entity_type="legacy_import_run", entity_id=run.id, summary=f"PMS import run {run.id} rolled back", data={"removed": removed, "forced": bool(problems and force)})
    return removed


# ------------------------------------------------------------------ output
def write_reports(report: dict, directory: str, dry_run: bool) -> tuple[str, str]:
    os.makedirs(directory, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = os.path.join(directory, f"pms-import-{'dry-run' if dry_run else 'commit'}-{stamp}")
    with open(stem + ".json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    lines = [f"# PMS import report ({'DRY RUN, nothing kept' if dry_run else 'COMMITTED'})", "", f"- Result: **{'PASS' if report['ok'] else 'NEEDS ATTENTION'}**", f"- Run id: `{report['run_id']}`", f"- Source: {report['source'].get('database')} extracted {report['source'].get('extracted_at')}", f"- Bundle SHA-256: `{report['bundle_sha256']}`", "",
             "## Counts", "", "| Entity | Source | Created | Linked | Already imported | Skipped |", "|---|---:|---:|---:|---:|---:|"]
    lines += [f"| {k} | {v['source']} | {v['created']} | {v['linked']} | {v['already_imported']} | {v['skipped']} |" for k, v in report["entities"].items()]
    lines += ["", "## Reconciliation (source values against what was read back from ELM)", "", "| Entity | Rows | Match |", "|---|---:|---|"]
    lines += [f"| {k} | {v['rows']} | {'yes' if v['match'] else 'NO'} |" for k, v in report["reconciliation"].items()]
    order = {"ERROR": 0, "REVIEW": 1, "WARN": 2, "INFO": 3}
    lines += ["", f"## Exceptions ({len(report['exceptions'])})", "", "| Severity | Entity | Source id | Message |", "|---|---|---|---|"]
    lines += [f"| {e['severity']} | {e['entity']} | {e['source_id']} | {str(e['message']).replace('|', '/')} |" for e in sorted(report["exceptions"], key=lambda x: order.get(x["severity"], 9))]
    lines += ["", "## PMS tables with data not migrated by this version", "", "These belong to later phases (requirements, design, development, testing, deployment, maintenance, documents). They are not lost: PMS stays read-only as the source.", "", "| Table | Rows |", "|---|---:|"]
    lines += [f"| {t} | {n} |" for t, n in report["deferred_tables"].items()]
    with open(stem + ".md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return stem + ".json", stem + ".md"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bundle", nargs="?", help="Bundle from extract_pms.py")
    ap.add_argument("--commit", action="store_true", help="Keep the data. Without this the load is rolled back.")
    ap.add_argument("--accept-errors", action="store_true", help="With --commit: keep the data even though rows were rejected (ERROR). Reconciliation must still match.")
    ap.add_argument("--report-dir", default="import_reports")
    ap.add_argument("--rollback", metavar="RUN_ID", help="Undo a committed run")
    ap.add_argument("--force", action="store_true", help="With --rollback: also delete records used since the import")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        if args.rollback:
            removed = rollback(db, uuid.UUID(args.rollback), args.force)
            db.commit()
            print("Rolled back. Removed:", json.dumps(removed, indent=2))
            return 0
        if not args.bundle:
            ap.error("a bundle file is required")
        raw = open(args.bundle, "rb").read()
        digest = hashlib.sha256(raw).hexdigest()
        side = args.bundle + ".sha256"
        if os.path.exists(side) and open(side, encoding="ascii").read().split()[0] != digest:
            raise SystemExit("The bundle does not match its .sha256 file, so it may be damaged or altered. Stopping.")
        bundle = json.loads(raw)
        if bundle.get("format") != 1 or bundle.get("source", {}).get("system") != "PMS":
            raise SystemExit("This is not a PMS bundle made by extract_pms.py.")
        report = Loader(db, bundle, digest).load()
        data_ok = not report["unbalanced_counts"] and all(r["match"] for r in report["reconciliation"].values())
        allowed = report["ok"] or (args.accept_errors and data_ok)
        report["errors_accepted"] = bool(args.accept_errors and not report["ok"] and data_ok)
        if args.commit and not allowed:
            db.rollback()
            paths = write_reports(report, args.report_dir, True)
            print(f"NOT committed: the checks did not pass. See {paths[1]}")
            return 2
        if args.commit:
            db.commit()
        else:
            db.rollback()
        paths = write_reports(report, args.report_dir, not args.commit)
        print(f"{'COMMITTED' if args.commit else 'DRY RUN (nothing kept)'}: {'PASS' if report['ok'] else 'NEEDS ATTENTION'}")
        print(json.dumps(report["totals"], indent=2))
        for k, v in report["entities"].items():
            print(f"  {k:<24} source {v['source']:>6}  created {v['created']:>6}  linked {v['linked']:>4}  already {v['already_imported']:>6}  skipped {v['skipped']:>4}")
        print("Reconciliation:", ", ".join(f"{k} {'ok' if v['match'] else 'MISMATCH'}" for k, v in report["reconciliation"].items()))
        print(f"Report: {paths[1]}")
        if args.commit:
            print(f"To undo: python -m app.legacy_import.load --rollback {report['run_id']}")
        return 0 if allowed else 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
