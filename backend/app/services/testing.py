"""Testing, verification and defect rules (architecture §13).

* Failure taxonomy is configurable (`test.failure_causes`). Only causes marked `creates_defect` (by default only
  application_defect) create or link a defect; the others are recorded as analysis outcomes (§13.3).
* Executions are append-only. A fixed defect puts its run cases back to RETEST; a passing retest moves the defect to
  VERIFIED, a failing one re-opens it (back to IN_PROGRESS) with the new execution linked.
* A run closes only when the plan's exit criteria hold and an authorised person (test.approve, not the executor) closes it.
"""
from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import AppError, Forbidden
from app.models import SystemSetting
from app.models.testing import Defect, TestCase, TestCaseRevision, TestExecution, TestPlan, TestRun, TestRunCase
from app.services import artifacts as art
from app.services.notify import notify
from app.services.numbering import next_seq

DEFAULT_FAILURE_CAUSES = [
    {"code": "application_defect", "label": "Application defect", "creates_defect": True},
    {"code": "environment", "label": "Test environment", "creates_defect": False},
    {"code": "test_data", "label": "Test data", "creates_defect": False},
    {"code": "automation_script", "label": "Automation script", "creates_defect": False},
    {"code": "configuration", "label": "Configuration", "creates_defect": False},
    {"code": "infrastructure", "label": "Infrastructure", "creates_defect": False},
    {"code": "expected_behaviour_changed", "label": "Expected behaviour changed", "creates_defect": False},
    {"code": "equipment_fixture", "label": "Equipment / fixture issue", "creates_defect": False},
]
CASE_FIELDS = ("title", "objective", "preconditions", "test_type", "steps", "expected_result")
PLAN_FIELDS = ("title", "scope", "build_version", "environments", "entry_criteria", "exit_criteria")
DEFAULT_EXIT = {"all_executed": True, "min_pass_rate": 100.0, "no_open_defects": ["CRITICAL", "HIGH"], "manual": []}
RESULTS = ("PASSED", "FAILED", "BLOCKED", "SKIPPED")
OPEN_DEFECT = ("OPEN", "IN_PROGRESS", "FIXED", "DEFERRED")

# Defect lifecycle (§13.4). Actors: assignee, reporter, manager (defect.manage in scope), tester (test.edit), system.
DEFECT_STATES = [
    {"code": "OPEN", "label": "Open", "color": "red"}, {"code": "IN_PROGRESS", "label": "In progress", "color": "blue"}, {"code": "FIXED", "label": "Fixed", "color": "cyan"},
    {"code": "VERIFIED", "label": "Verified", "color": "teal"}, {"code": "CLOSED", "label": "Closed", "color": "gray"}, {"code": "REJECTED", "label": "Rejected", "color": "gray"},
    {"code": "DEFERRED", "label": "Deferred", "color": "yellow"},
]
DEFECT_TRANSITIONS = [
    {"from": "OPEN", "to": "IN_PROGRESS", "label": "Start fixing", "actors": ["assignee", "manager"]},
    {"from": "OPEN", "to": "REJECTED", "label": "Reject", "actors": ["manager"], "reason": True},
    {"from": "OPEN", "to": "DEFERRED", "label": "Defer", "actors": ["manager"], "reason": True},
    {"from": "DEFERRED", "to": "OPEN", "label": "Reopen", "actors": ["manager"]},
    {"from": "IN_PROGRESS", "to": "FIXED", "label": "Mark fixed", "actors": ["assignee", "manager"]},
    {"from": "FIXED", "to": "VERIFIED", "label": "Verify", "actors": ["tester", "system"]},
    {"from": "FIXED", "to": "IN_PROGRESS", "label": "Retest failed / reopen", "actors": ["reporter", "manager", "tester", "system"], "reason": True},
    {"from": "VERIFIED", "to": "CLOSED", "label": "Close", "actors": ["reporter", "manager"]},
    {"from": "VERIFIED", "to": "IN_PROGRESS", "label": "Reopen", "actors": ["reporter", "manager"], "reason": True},
]


def _setting(db: Session, key: str, default):
    row = db.get(SystemSetting, key)
    if not row:
        return default
    try:
        return json.loads(row.value)
    except ValueError:
        return default


def failure_causes(db: Session) -> list[dict]:
    return _setting(db, "test.failure_causes", DEFAULT_FAILURE_CAUSES)


def canon(obj: dict, fields: tuple[str, ...]) -> tuple[str, str]:
    text = json.dumps({k: obj.get(k) for k in fields}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return text, hashlib.sha256(text.encode()).hexdigest()


def case_content(c: TestCase) -> dict:
    return {"title": c.title, "objective": c.objective, "preconditions": c.preconditions, "test_type": c.test_type, "steps": json.loads(c.steps or "[]"), "expected_result": c.expected_result}


def plan_content(p: TestPlan) -> dict:
    return {"title": p.title, "scope": p.scope, "build_version": p.build_version, "environments": p.environments, "entry_criteria": json.loads(p.entry_criteria or "[]"), "exit_criteria": json.loads(p.exit_criteria or "{}")}


def write_case_revision(db: Session, c: TestCase, actor: uuid.UUID | None, reason: str | None) -> None:
    text, sha = canon(case_content(c), CASE_FIELDS)
    c.content_sha256 = sha
    db.add(TestCaseRevision(case_id=c.id, revision=c.revision, snapshot=text, content_sha256=sha, reason=reason, created_by_id=actor))


def next_key(db: Session, project_code: str, kind: str) -> str:
    return f"{project_code}-{kind}-{next_seq(db, f'{kind.lower()}:{project_code}'):04d}"


# ------------------------------------------------------------------ defects
def defect_actors(d: Defect, user_id: uuid.UUID | None, *, manager: bool, tester: bool) -> set[str]:
    out = set()
    if user_id and user_id == d.assignee_id:
        out.add("assignee")
    if user_id and user_id == d.reporter_id:
        out.add("reporter")
    if manager:
        out.add("manager")
    if tester:
        out.add("tester")
    return out


def defect_transitions_for(d: Defect, user_id, *, manager: bool, tester: bool) -> list[dict]:
    mine = defect_actors(d, user_id, manager=manager, tester=tester)
    out = []
    for t in DEFECT_TRANSITIONS:
        if t["from"] != d.status or not mine & set(t["actors"]):
            continue
        if t["to"] == "VERIFIED" and user_id == d.fixed_by_id:
            continue  # whoever fixed it does not verify it
        out.append({"to": t["to"], "label": t["label"], "reason_required": bool(t.get("reason"))})
    return out


def move_defect(db: Session, d: Defect, to: str, *, user_id: uuid.UUID | None, manager: bool = False, tester: bool = False, comment: str | None = None, system: bool = False, fixed_in_build: str | None = None) -> str:
    rule = next((t for t in DEFECT_TRANSITIONS if t["from"] == d.status and t["to"] == to), None)
    if not rule:
        raise AppError(f"A defect cannot move from {d.status} to {to}.", code="INVALID_TRANSITION")
    mine = {"system"} if system else defect_actors(d, user_id, manager=manager, tester=tester)
    if not mine & set(rule["actors"]):
        raise Forbidden(f"You are not allowed to “{rule['label']}” this defect.", details={"actors": rule["actors"]})
    if to == "VERIFIED" and not system and user_id == d.fixed_by_id:
        raise Forbidden("The person who fixed a defect cannot verify it.", code="SOD_VIOLATION")
    if rule.get("reason") and not (comment or "").strip():
        raise AppError("A reason is required for this action.", code="REASON_REQUIRED")
    old = d.status
    d.status = to
    d.version += 1
    if to == "FIXED":
        d.fixed_by_id = user_id
        d.fixed_in_build = fixed_in_build or d.fixed_in_build
        mark_retest(db, d)
    art.add_event(db, "DEFECT", d.id, "STATUS", None if system else user_id, old, to, comment)
    for uid in {d.assignee_id, d.reporter_id} - {user_id, None}:
        notify(db, uid, "defect.status", f"{d.key}: {old} → {to}", (comment or d.title)[:300], link=f"/testing/{d.project_id}?defect={d.id}")
    return old


def mark_retest(db: Session, d: Defect) -> int:
    """Every open run case whose latest failure is linked to this defect goes back to RETEST (§13.3)."""
    rows = db.execute(select(TestRunCase, TestRun).join(TestRun, TestRun.id == TestRunCase.run_id).join(TestExecution, TestExecution.run_case_id == TestRunCase.id)
                      .where(TestExecution.defect_id == d.id, TestRun.status != "CLOSED").distinct()).all()
    n = 0
    for rc, run in rows:
        if rc.status in ("FAILED", "BLOCKED"):
            rc.status = "RETEST"
            n += 1
            if rc.assignee_id or run.executor_id:
                notify(db, rc.assignee_id or run.executor_id, "test.retest", f"Retest needed in {run.key}", f"Defect {d.key} is fixed{' in ' + d.fixed_in_build if d.fixed_in_build else ''}.", link=f"/testing/{run.project_id}?run={run.id}")
    return n


# ------------------------------------------------------------------ executions
def record_execution(db: Session, rc: TestRunCase, run: TestRun, *, result: str, tester_id: uuid.UUID | None, actual: str | None, cause: str | None, defect: Defect | None,
                     notes: str | None = None, source: str = "MANUAL", external_id: str | None = None, duration: float | None = None) -> TestExecution:
    if run.status == "CLOSED":
        raise AppError(f"Run {run.key} is closed; executions cannot be added.", code="RUN_CLOSED")
    if result not in RESULTS:
        raise AppError(f"Result must be one of {', '.join(RESULTS)}.")
    causes = {c["code"]: c for c in failure_causes(db)}
    retest = rc.status == "RETEST"
    prior = db.execute(select(Defect).join(TestExecution, TestExecution.defect_id == Defect.id).where(TestExecution.run_case_id == rc.id, Defect.status == "FIXED").distinct()).scalars().all() if retest else []
    if retest and result == "FAILED" and defect is None and causes.get(cause or "", {}).get("creates_defect") and prior:
        defect = prior[0]  # a failed retest stays on the defect it was retesting
    if result == "FAILED":
        if not cause:
            raise AppError("A failed execution needs a failure cause.", code="CAUSE_REQUIRED")
        if cause not in causes:
            raise AppError(f"Unknown failure cause {cause}.")
        if causes[cause].get("creates_defect") and defect is None:
            raise AppError("This failure cause needs a defect: link an open one or create a new one.", code="DEFECT_REQUIRED")
        if not causes[cause].get("creates_defect") and defect is not None:
            raise AppError("Only an application defect is linked to a defect; record other causes as analysis.", code="NOT_A_DEFECT")
    elif defect is not None and rc.status != "RETEST":
        raise AppError("Only failed executions (or retests) are linked to defects.")
    ex = TestExecution(run_case_id=rc.id, result=result, actual_result=actual, failure_cause=cause if result == "FAILED" else None, defect_id=defect.id if defect else None, is_retest=retest,
                       tester_id=tester_id, notes=notes, source=source, external_result_id=external_id, duration_seconds=duration, executed_at=utcnow())
    db.add(ex)
    db.flush()
    rc.status = result
    rc.last_execution_id = ex.id
    if run.status == "PLANNED":
        run.status = "IN_PROGRESS"
    case = db.get(TestCase, rc.case_id)
    art.add_event(db, "TEST_CASE", case.id, "EXECUTION", tester_id, run.key, result, cause)
    if retest:
        for d in prior:
            if result == "PASSED":
                move_defect(db, d, "VERIFIED", user_id=tester_id, system=True, comment=f"Retest passed in {run.key} ({case.key}).")
            elif result == "FAILED":
                move_defect(db, d, "IN_PROGRESS", user_id=tester_id, system=True, comment=f"Retest failed in {run.key} ({case.key}).")
    return ex


# ------------------------------------------------------------------ exit criteria
def evaluate_exit(db: Session, run: TestRun) -> dict:
    plan = db.get(TestPlan, run.plan_id)
    crit = {**DEFAULT_EXIT, **json.loads(plan.exit_criteria or "{}")}
    rcs = list(db.execute(select(TestRunCase).where(TestRunCase.run_id == run.id)).scalars())
    total = len(rcs)
    counts: dict[str, int] = {}
    for rc in rcs:
        counts[rc.status] = counts.get(rc.status, 0) + 1
    executed = total - counts.get("NOT_RUN", 0) - counts.get("RETEST", 0)
    passed = counts.get("PASSED", 0)
    rate = round(100.0 * passed / total, 1) if total else 0.0
    checks = []
    if crit.get("all_executed"):
        checks.append({"code": "all_executed", "label": "Every case executed (no case waiting or due for retest)", "ok": total > 0 and executed == total, "detail": f"{executed} of {total} executed"})
    if crit.get("min_pass_rate") is not None:
        checks.append({"code": "min_pass_rate", "label": f"Pass rate at least {crit['min_pass_rate']}%", "ok": rate >= float(crit["min_pass_rate"]), "detail": f"{rate}% passed"})
    sev = crit.get("no_open_defects") or []
    if sev:
        ids = {d for (d,) in db.execute(select(TestExecution.defect_id).join(TestRunCase, TestRunCase.id == TestExecution.run_case_id).where(TestRunCase.run_id == run.id, TestExecution.defect_id.is_not(None))).all()}
        open_ = db.execute(select(Defect).where(Defect.id.in_(ids), Defect.status.in_(OPEN_DEFECT), Defect.severity.in_(sev))).scalars().all() if ids else []
        checks.append({"code": "no_open_defects", "label": f"No open {'/'.join(s.lower() for s in sev)} defects from this run", "ok": not open_, "detail": ", ".join(d.key for d in open_) or "none"})
    manual = [{"code": f"manual_{i}", "label": text, "manual": True} for i, text in enumerate(crit.get("manual") or [])]
    return {"criteria": crit, "checks": checks, "manual": manual, "counts": counts, "total": total, "pass_rate": rate, "automatic_ok": all(c["ok"] for c in checks)}


def run_key(db: Session, project_code: str) -> str:
    return next_key(db, project_code, "RUN")


def last_results_for_cases(db: Session, case_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """Latest execution per test case across all runs, for coverage / RTM columns."""
    if not case_ids:
        return {}
    sub = select(TestRunCase.case_id, func.max(TestExecution.executed_at).label("at")).join(TestExecution, TestExecution.run_case_id == TestRunCase.id).where(TestRunCase.case_id.in_(case_ids)).group_by(TestRunCase.case_id).subquery()
    rows = db.execute(select(TestRunCase.case_id, TestExecution.result, TestExecution.executed_at).join(TestExecution, TestExecution.run_case_id == TestRunCase.id)
                      .join(sub, (sub.c.case_id == TestRunCase.case_id) & (sub.c.at == TestExecution.executed_at))).all()
    return {cid: {"result": res, "at": at.isoformat() if at else None} for cid, res, at in rows}
