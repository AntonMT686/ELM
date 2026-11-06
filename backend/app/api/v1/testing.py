"""Testing, verification and defects API (architecture §13). Scope is enforced on every endpoint and every mutation is
audited in the same transaction. Rules live in services/testing.py and services/artifacts.py."""
from __future__ import annotations

import hmac
import json
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.core.config import get_settings
from app.core.db import get_db, utcnow
from app.core.deps import Ctx, get_ctx, get_or_404
from app.core.errors import AppError, Conflict, Forbidden, Unauthorized
from app.models import EngineeringItem, FileObject, Project, Requirement, SystemSetting, WorkItem
from app.models.artifacts import ArtifactReview
from app.models.testing import Defect, TestAutomationJob, TestCase, TestCaseRevision, TestEvidence, TestExecution, TestPlan, TestRun, TestRunCase, TestSuite, TestSuiteCase
from app.services import artifacts as art
from app.services import audit as auditsvc
from app.services import storage
from app.services import testing as svc
from app.services.planning import can_view_project, can_view_task, require_view_project
from app.services.requirements import can_view as can_view_requirement
from app.services.serial import iso, user_brief

router = APIRouter(tags=["testing"])
TEST_TYPES = r"^(FUNCTIONAL|INTEGRATION|SYSTEM|REGRESSION|PERFORMANCE|SAFETY|SECURITY|ACCEPTANCE|OTHER)$"
SEVERITIES = r"^(LOW|MEDIUM|HIGH|CRITICAL)$"


# ------------------------------------------------------------------ helpers
def _project(ctx: Ctx, pid: uuid.UUID) -> Project:
    p = get_or_404(ctx.db, Project, pid, "Project")
    require_view_project(ctx.db, ctx.p, pid)
    return p


def _view(ctx: Ctx, project_id: uuid.UUID, a_type: str | None = None, a_id: uuid.UUID | None = None) -> None:
    if can_view_project(ctx.db, ctx.p, project_id):
        return
    if a_type and a_id and art.is_reviewer(ctx.db, a_type, a_id, ctx.user.id):
        return
    raise Forbidden("You do not have access to this project.")


def _need(ctx: Ctx, perm: str, project_id: uuid.UUID, what: str) -> None:
    if not ctx.p.has(perm, project_id=project_id):
        raise Forbidden(f"{what} needs the {perm} permission for this project.", details={"permission": perm})


def _check_version(version: int | None, obj) -> None:
    if version is not None and version != obj.version:
        raise Conflict("This record was changed by someone else. Refresh and try again.")


def _users(ctx: Ctx, ids) -> dict:
    return art._users(ctx.db, ids)


def _see(ctx: Ctx):
    def check(t: str, oid) -> bool:
        db = ctx.db
        if t == "REQUIREMENT":
            o = db.get(Requirement, oid)
            return bool(o) and can_view_requirement(db, ctx.p, o)
        if t == "TASK":
            o = db.get(WorkItem, oid)
            return bool(o) and can_view_task(db, ctx.p, o)
        s = art.target_summary(db, t, oid)
        return bool(s) and bool(s.get("project_id")) and can_view_project(db, ctx.p, uuid.UUID(s["project_id"]))
    return check


class SubmitIn(BaseModel):
    reviewers: list[uuid.UUID] = Field(default_factory=list)
    approvers: list[uuid.UUID] = Field(min_length=1)


class DecisionIn(BaseModel):
    decision: str = Field(pattern=r"^(approve|request_changes)$")
    comment: str | None = Field(default=None, max_length=4000)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class LinkIn(BaseModel):
    to_type: str = Field(pattern=r"^(REQUIREMENT|DESIGN|TASK|DOCUMENT)$")
    to_id: uuid.UUID
    link_type: str = Field(default="verifies", pattern=r"^(verifies|related_to|implements|affects)$")


# ------------------------------------------------------------------ configuration
@router.get("/test-config")
def test_config(ctx: Ctx = Depends(get_ctx)):
    return {"failure_causes": svc.failure_causes(ctx.db), "defect_states": svc.DEFECT_STATES, "default_exit_criteria": svc.DEFAULT_EXIT, "runners": _runners()}


class CausesIn(BaseModel):
    causes: list[dict] = Field(min_length=1)


@router.put("/test-config/failure-causes")
def set_failure_causes(body: CausesIn, ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("workflow.configure")
    codes = [c.get("code") for c in body.causes]
    if len(set(codes)) != len(codes) or not all(codes) or not all(c.get("label") for c in body.causes):
        raise AppError("Every failure cause needs a unique code and a label.")
    if not any(c.get("creates_defect") for c in body.causes):
        raise AppError("At least one cause must create a defect (application defect).")
    row = ctx.db.get(SystemSetting, "test.failure_causes")
    value = json.dumps([{"code": c["code"], "label": c["label"], "creates_defect": bool(c.get("creates_defect"))} for c in body.causes])
    if row:
        row.value = value
    else:
        ctx.db.add(SystemSetting(key="test.failure_causes", value=value, description="Test failure taxonomy (architecture §13.3)"))
    ctx.audit("test.config.failure_causes", "system_setting", None, "Test failure causes updated", {"codes": codes})
    ctx.db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ test cases
class CaseIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    objective: str | None = None
    preconditions: str | None = None
    test_type: str = Field(default="FUNCTIONAL", pattern=TEST_TYPES)
    steps: list[dict] = Field(default_factory=list)
    expected_result: str | None = None
    item_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    automation_id: str | None = Field(default=None, max_length=200)
    automation_tool: str | None = Field(default=None, max_length=40)
    reason: str | None = Field(default=None, max_length=1000)


def _case(ctx: Ctx, cid: uuid.UUID) -> TestCase:
    c = get_or_404(ctx.db, TestCase, cid, "Test case")
    _view(ctx, c.project_id, "TEST_CASE", c.id)
    return c


def _case_brief(c: TestCase, users: dict, last: dict | None = None) -> dict:
    return {"id": str(c.id), "key": c.key, "title": c.title, "status": c.status, "test_type": c.test_type, "revision": c.revision, "owner": user_brief(users.get(c.owner_id)),
            "automation_id": c.automation_id, "automation_tool": c.automation_tool, "item_id": str(c.item_id) if c.item_id else None, "last_result": last, "updated_at": iso(c.updated_at), "version": c.version}


def _steps(steps: list[dict]) -> str:
    clean = []
    for i, s in enumerate(steps, 1):
        if not (s.get("action") or "").strip():
            raise AppError(f"Step {i} has no action.")
        clean.append({"action": s["action"].strip(), "expected": (s.get("expected") or "").strip()})
    return json.dumps(clean, ensure_ascii=False)


@router.get("/projects/{pid}/test-cases")
def list_cases(pid: uuid.UUID, q: str | None = None, status: str | None = None, ctx: Ctx = Depends(get_ctx)):
    _project(ctx, pid)
    s = select(TestCase).where(TestCase.project_id == pid)
    if q:
        s = s.where(or_(TestCase.title.ilike(f"%{q}%"), TestCase.key.ilike(f"%{q}%")))
    if status:
        s = s.where(TestCase.status.in_(status.split(",")))
    rows = ctx.db.execute(s.order_by(TestCase.key)).scalars().all()
    last = svc.last_results_for_cases(ctx.db, [c.id for c in rows])
    users = _users(ctx, {c.owner_id for c in rows})
    return {"can_edit": ctx.p.has("test.edit", project_id=pid), "can_approve": ctx.p.has("test.approve", project_id=pid), "items": [_case_brief(c, users, last.get(c.id)) for c in rows]}


@router.post("/projects/{pid}/test-cases")
def create_case(pid: uuid.UUID, body: CaseIn, ctx: Ctx = Depends(get_ctx)):
    p = _project(ctx, pid)
    _need(ctx, "test.edit", pid, "Writing test cases")
    if body.item_id and get_or_404(ctx.db, EngineeringItem, body.item_id, "Item").project_id != pid:
        raise AppError("The engineering item belongs to a different project.")
    c = TestCase(project_id=pid, key=svc.next_key(ctx.db, p.code, "TC"), title=body.title, objective=body.objective, preconditions=body.preconditions, test_type=body.test_type, steps=_steps(body.steps),
                 expected_result=body.expected_result, item_id=body.item_id, owner_id=body.owner_id or ctx.user.id, automation_id=body.automation_id, automation_tool=body.automation_tool, created_by_id=ctx.user.id, content_sha256="")
    ctx.db.add(c)
    ctx.db.flush()
    svc.write_case_revision(ctx.db, c, ctx.user.id, "Created")
    art.add_event(ctx.db, "TEST_CASE", c.id, "CREATED", ctx.user.id, to="DRAFT")
    ctx.audit("test.case.create", "test_case", c.id, f"{c.key} created: {c.title}")
    ctx.db.commit()
    return _case_detail(ctx, c)


def _case_detail(ctx: Ctx, c: TestCase) -> dict:
    db = ctx.db
    revs = db.execute(select(TestCaseRevision).where(TestCaseRevision.case_id == c.id).order_by(TestCaseRevision.revision.desc())).scalars().all()
    used = db.execute(select(TestRunCase, TestRun).join(TestRun, TestRun.id == TestRunCase.run_id).where(TestRunCase.case_id == c.id).order_by(TestRun.created_at.desc()).limit(20)).all()
    users = _users(ctx, {c.owner_id} | {r.created_by_id for r in revs})
    editable = c.owner_id == ctx.user.id or ctx.p.has("test.edit", project_id=c.project_id)
    return {**_case_brief(c, users, svc.last_results_for_cases(db, [c.id]).get(c.id)), "project_id": str(c.project_id), "objective": c.objective, "preconditions": c.preconditions,
            "steps": json.loads(c.steps or "[]"), "expected_result": c.expected_result, "sha256": c.content_sha256, "can_edit": editable,
            "revisions": [{"revision": r.revision, "sha256": r.content_sha256, "reason": r.reason, "at": iso(r.created_at), "by": user_brief(users.get(r.created_by_id))} for r in revs],
            "reviews": art.reviews(db, "TEST_CASE", c.id, ctx.user.id), "links": art.links(db, "TEST_CASE", c.id, _see(ctx)), "history": art.history(db, "TEST_CASE", c.id),
            "runs": [{"run": {"id": str(run.id), "key": run.key, "title": run.title, "status": run.status}, "status": rc.status, "revision": rc.case_revision} for rc, run in used]}


@router.get("/test-cases/{cid}")
def get_case(cid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    return _case_detail(ctx, _case(ctx, cid))


@router.put("/test-cases/{cid}")
def update_case(cid: uuid.UUID, body: CaseIn, version: int | None = None, ctx: Ctx = Depends(get_ctx)):
    c = _case(ctx, cid)
    if c.owner_id != ctx.user.id and not ctx.p.has("test.edit", project_id=c.project_id):
        raise Forbidden("Only the owner or someone with test edit permission can change this test case.")
    _check_version(version, c)
    if c.status == "UNDER_REVIEW":
        raise Conflict("This test case is locked while it is in review. Withdraw it first.", code="LOCKED")
    if c.status == "OBSOLETE":
        raise Conflict("An obsolete test case cannot change.", code="LOCKED")
    before = c.content_sha256
    c.title, c.objective, c.preconditions, c.test_type, c.steps, c.expected_result = body.title, body.objective, body.preconditions, body.test_type, _steps(body.steps), body.expected_result
    c.item_id, c.automation_id, c.automation_tool = body.item_id, body.automation_id, body.automation_tool
    if body.owner_id:
        c.owner_id = body.owner_id
    _, sha = svc.canon(svc.case_content(c), svc.CASE_FIELDS)
    if sha != before:
        if c.status == "APPROVED" and not (body.reason or "").strip():
            raise AppError(f"{c.key} is approved. Give a reason: the change makes revision {c.revision + 1} and it needs approval again.", code="REASON_REQUIRED")
        c.revision += 1
        svc.write_case_revision(ctx.db, c, ctx.user.id, body.reason)
        if c.status == "APPROVED":
            art.add_event(ctx.db, "TEST_CASE", c.id, "STATUS", ctx.user.id, "APPROVED", "DRAFT", body.reason)
            c.status = "DRAFT"
        art.add_event(ctx.db, "TEST_CASE", c.id, "VERSION", ctx.user.id, c.revision - 1, c.revision, body.reason)
    c.version += 1
    ctx.audit("test.case.update", "test_case", c.id, f"{c.key} updated (revision {c.revision})", {"reason": body.reason})
    ctx.db.commit()
    return _case_detail(ctx, c)


@router.post("/test-cases/{cid}/submit")
def submit_case(cid: uuid.UUID, body: SubmitIn, ctx: Ctx = Depends(get_ctx)):
    c = _case(ctx, cid)
    if c.owner_id != ctx.user.id and not ctx.p.has("test.edit", project_id=c.project_id):
        raise Forbidden("Only the owner or someone with test edit permission can submit this test case.")
    if c.status != "DRAFT":
        raise AppError("Only a draft test case can be submitted for review.", code="INVALID_STATE")
    if not json.loads(c.steps or "[]"):
        raise AppError("Add at least one step before submitting.", code="FIELD_REQUIRED")
    art.submit(ctx.db, a_type="TEST_CASE", a_id=c.id, revision=c.revision, sha=c.content_sha256, submitter_id=ctx.user.id, reviewers=body.reviewers, approvers=body.approvers,
               excluded={c.owner_id}, title=f"{c.key} {c.title}", link=f"/testing/{c.project_id}?case={c.id}")
    art.add_event(ctx.db, "TEST_CASE", c.id, "STATUS", ctx.user.id, c.status, "UNDER_REVIEW")
    c.status, c.version = "UNDER_REVIEW", c.version + 1
    ctx.audit("test.case.submit", "test_case", c.id, f"{c.key} revision {c.revision} submitted", {"sha256": c.content_sha256})
    ctx.db.commit()
    return _case_detail(ctx, c)


@router.post("/test-cases/{cid}/withdraw")
def withdraw_case(cid: uuid.UUID, body: ReasonIn, ctx: Ctx = Depends(get_ctx)):
    c = _case(ctx, cid)
    if c.owner_id != ctx.user.id and not ctx.p.has("test.edit", project_id=c.project_id):
        raise Forbidden("Only the owner or someone with test edit permission can withdraw this test case.")
    if c.status != "UNDER_REVIEW":
        raise AppError("Only a test case in review can be withdrawn.")
    art.withdraw(ctx.db, "TEST_CASE", c.id)
    art.add_event(ctx.db, "TEST_CASE", c.id, "STATUS", ctx.user.id, c.status, "DRAFT", body.reason)
    c.status, c.version = "DRAFT", c.version + 1
    ctx.audit("test.case.withdraw", "test_case", c.id, f"{c.key} withdrawn from review", {"reason": body.reason})
    ctx.db.commit()
    return _case_detail(ctx, c)


@router.post("/test-cases/{cid}/reviews/{rid}/decide")
def decide_case(cid: uuid.UUID, rid: uuid.UUID, body: DecisionIn, ctx: Ctx = Depends(get_ctx)):
    c = _case(ctx, cid)
    r = get_or_404(ctx.db, ArtifactReview, rid, "Review")
    if r.artifact_type != "TEST_CASE" or r.artifact_id != c.id:
        raise AppError("That review belongs to another record.")
    outcome = art.decide(ctx.db, review=r, user_id=ctx.user.id, decision=body.decision, comment=body.comment, revision=c.revision, sha=c.content_sha256, title=f"{c.key} {c.title}",
                         link=f"/testing/{c.project_id}?case={c.id}", owner_id=c.owner_id)
    art.add_event(ctx.db, "TEST_CASE", c.id, "DECISION", ctx.user.id, r.role, r.status, r.comment)
    if outcome != "PENDING":
        to = "APPROVED" if outcome == "APPROVED" else "DRAFT"
        art.add_event(ctx.db, "TEST_CASE", c.id, "STATUS", ctx.user.id, c.status, to)
        c.status = to
    c.version += 1
    ctx.audit("test.case.decide", "test_case", c.id, f"{c.key}: {r.role.lower()} {body.decision.replace('_', ' ')}", {"revision": r.revision, "sha256": r.content_sha256, "outcome": outcome})
    ctx.db.commit()
    return _case_detail(ctx, c)


@router.post("/test-cases/{cid}/obsolete")
def obsolete_case(cid: uuid.UUID, body: ReasonIn, ctx: Ctx = Depends(get_ctx)):
    c = _case(ctx, cid)
    _need(ctx, "test.approve", c.project_id, "Making a test case obsolete")
    art.withdraw(ctx.db, "TEST_CASE", c.id)
    art.add_event(ctx.db, "TEST_CASE", c.id, "STATUS", ctx.user.id, c.status, "OBSOLETE", body.reason)
    c.status, c.version = "OBSOLETE", c.version + 1
    ctx.audit("test.case.obsolete", "test_case", c.id, f"{c.key} made obsolete", {"reason": body.reason})
    ctx.db.commit()
    return _case_detail(ctx, c)


@router.post("/test-cases/{cid}/links")
def link_case(cid: uuid.UUID, body: LinkIn, ctx: Ctx = Depends(get_ctx)):
    c = _case(ctx, cid)
    _need(ctx, "test.edit", c.project_id, "Linking test cases")
    if not _see(ctx)(body.to_type, body.to_id):
        raise Forbidden("You do not have access to the record you are linking.")
    art.add_link(ctx.db, from_type="TEST_CASE", from_id=c.id, to_type=body.to_type, to_id=body.to_id, link_type=body.link_type, section=None, actor=ctx.user.id)
    s = art.target_summary(ctx.db, body.to_type, body.to_id)
    art.add_event(ctx.db, "TEST_CASE", c.id, "LINK", ctx.user.id, None, f"{body.link_type} {s['key']}")
    ctx.audit("test.case.link", "test_case", c.id, f"{c.key} {body.link_type} {s['key']}")
    ctx.db.commit()
    return _case_detail(ctx, c)


@router.delete("/test-cases/{cid}/links/{lid}")
def unlink_case(cid: uuid.UUID, lid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    from app.models.artifacts import ArtifactLink

    c = _case(ctx, cid)
    _need(ctx, "test.edit", c.project_id, "Changing test case links")
    link = get_or_404(ctx.db, ArtifactLink, lid, "Link")
    if link.from_type != "TEST_CASE" or link.from_id != c.id:
        raise AppError("That link belongs to another record.")
    ctx.db.delete(link)
    art.add_event(ctx.db, "TEST_CASE", c.id, "LINK", ctx.user.id, f"{link.link_type} {link.to_type}", None, "removed")
    ctx.audit("test.case.unlink", "test_case", c.id, f"{c.key} link removed")
    ctx.db.commit()
    return _case_detail(ctx, c)


# ------------------------------------------------------------------ plans and suites
class PlanIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    scope: str | None = None
    build_version: str | None = Field(default=None, max_length=120)
    environments: str | None = Field(default=None, max_length=500)
    entry_criteria: list[str] = Field(default_factory=list)
    exit_criteria: dict = Field(default_factory=lambda: dict(svc.DEFAULT_EXIT))
    start_date: date | None = None
    end_date: date | None = None
    owner_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=1000)


def _exit(x: dict) -> str:
    unknown = set(x) - set(svc.DEFAULT_EXIT)
    if unknown:
        raise AppError(f"Unknown exit criterion: {', '.join(sorted(unknown))}.")
    rate = x.get("min_pass_rate")
    if rate is not None and not (0 <= float(rate) <= 100):
        raise AppError("The minimum pass rate must be between 0 and 100.")
    bad = set(x.get("no_open_defects") or []) - {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    if bad:
        raise AppError("Defect severities must be LOW, MEDIUM, HIGH or CRITICAL.")
    return json.dumps({**svc.DEFAULT_EXIT, **x})


def _plan(ctx: Ctx, pid: uuid.UUID) -> TestPlan:
    p = get_or_404(ctx.db, TestPlan, pid, "Test plan")
    _view(ctx, p.project_id, "TEST_PLAN", p.id)
    return p


def _plan_brief(p: TestPlan, users: dict) -> dict:
    return {"id": str(p.id), "key": p.key, "title": p.title, "status": p.status, "build_version": p.build_version, "environments": p.environments, "start_date": iso(p.start_date), "end_date": iso(p.end_date),
            "owner": user_brief(users.get(p.owner_id)), "revision": p.revision, "version": p.version}


@router.get("/projects/{pid}/test-plans")
def list_plans(pid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    _project(ctx, pid)
    rows = ctx.db.execute(select(TestPlan).where(TestPlan.project_id == pid).order_by(TestPlan.key)).scalars().all()
    users = _users(ctx, {p.owner_id for p in rows})
    return [_plan_brief(p, users) for p in rows]


@router.post("/projects/{pid}/test-plans")
def create_plan(pid: uuid.UUID, body: PlanIn, ctx: Ctx = Depends(get_ctx)):
    proj = _project(ctx, pid)
    _need(ctx, "test.edit", pid, "Creating test plans")
    p = TestPlan(project_id=pid, key=svc.next_key(ctx.db, proj.code, "TP"), title=body.title, scope=body.scope, build_version=body.build_version, environments=body.environments,
                 entry_criteria=json.dumps(body.entry_criteria), exit_criteria=_exit(body.exit_criteria), start_date=body.start_date, end_date=body.end_date, owner_id=body.owner_id or ctx.user.id, created_by_id=ctx.user.id, content_sha256="")
    _, p.content_sha256 = svc.canon(svc.plan_content(p), svc.PLAN_FIELDS)
    ctx.db.add(p)
    ctx.db.flush()
    ctx.db.add(TestSuite(plan_id=p.id, name="Main suite"))
    art.add_event(ctx.db, "TEST_PLAN", p.id, "CREATED", ctx.user.id, to="DRAFT")
    ctx.audit("test.plan.create", "test_plan", p.id, f"{p.key} created: {p.title}")
    ctx.db.commit()
    return _plan_detail(ctx, p)


def _plan_detail(ctx: Ctx, p: TestPlan) -> dict:
    db = ctx.db
    suites = db.execute(select(TestSuite).where(TestSuite.plan_id == p.id).order_by(TestSuite.sort_order, TestSuite.created_at)).scalars().all()
    sc = db.execute(select(TestSuiteCase, TestCase).join(TestCase, TestCase.id == TestSuiteCase.case_id).where(TestSuiteCase.suite_id.in_([s.id for s in suites] or [uuid.uuid4()])).order_by(TestSuiteCase.sort_order, TestCase.key)).all()
    runs = db.execute(select(TestRun).where(TestRun.plan_id == p.id).order_by(TestRun.created_at.desc())).scalars().all()
    users = _users(ctx, {p.owner_id} | {r.executor_id for r in runs})
    by_suite: dict = {}
    for x, c in sc:
        by_suite.setdefault(x.suite_id, []).append({"id": str(c.id), "key": c.key, "title": c.title, "status": c.status, "revision": c.revision})
    return {**_plan_brief(p, users), "project_id": str(p.project_id), "scope": p.scope, "entry_criteria": json.loads(p.entry_criteria or "[]"), "exit_criteria": json.loads(p.exit_criteria or "{}"),
            "sha256": p.content_sha256, "can_edit": p.owner_id == ctx.user.id or ctx.p.has("test.edit", project_id=p.project_id), "can_approve": ctx.p.has("test.approve", project_id=p.project_id),
            "suites": [{"id": str(s.id), "name": s.name, "parent_id": str(s.parent_id) if s.parent_id else None, "cases": by_suite.get(s.id, [])} for s in suites],
            "runs": [{"id": str(r.id), "key": r.key, "title": r.title, "status": r.status, "build_version": r.build_version, "executor": user_brief(users.get(r.executor_id)), "created_at": iso(r.created_at)} for r in runs],
            "reviews": art.reviews(db, "TEST_PLAN", p.id, ctx.user.id), "history": art.history(db, "TEST_PLAN", p.id)}


@router.get("/test-plans/{pid}")
def get_plan(pid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    return _plan_detail(ctx, _plan(ctx, pid))


@router.put("/test-plans/{pid}")
def update_plan(pid: uuid.UUID, body: PlanIn, version: int | None = None, ctx: Ctx = Depends(get_ctx)):
    p = _plan(ctx, pid)
    if p.owner_id != ctx.user.id and not ctx.p.has("test.edit", project_id=p.project_id):
        raise Forbidden("Only the owner or someone with test edit permission can change this plan.")
    _check_version(version, p)
    if p.status in ("UNDER_REVIEW", "CLOSED"):
        raise Conflict(f"A plan that is {p.status.lower().replace('_', ' ')} cannot change.", code="LOCKED")
    before = p.content_sha256
    p.title, p.scope, p.build_version, p.environments = body.title, body.scope, body.build_version, body.environments
    p.entry_criteria, p.exit_criteria, p.start_date, p.end_date = json.dumps(body.entry_criteria), _exit(body.exit_criteria), body.start_date, body.end_date
    if body.owner_id:
        p.owner_id = body.owner_id
    _, p.content_sha256 = svc.canon(svc.plan_content(p), svc.PLAN_FIELDS)
    if p.content_sha256 != before:
        if p.status in ("APPROVED", "ACTIVE"):
            if not (body.reason or "").strip():
                raise AppError(f"{p.key} is {p.status.lower()}. Give a reason: the change needs approval again.", code="REASON_REQUIRED")
            art.add_event(ctx.db, "TEST_PLAN", p.id, "STATUS", ctx.user.id, p.status, "DRAFT", body.reason)
            p.status = "DRAFT"
        p.revision += 1
    p.version += 1
    ctx.audit("test.plan.update", "test_plan", p.id, f"{p.key} updated", {"reason": body.reason})
    ctx.db.commit()
    return _plan_detail(ctx, p)


@router.post("/test-plans/{pid}/submit")
def submit_plan(pid: uuid.UUID, body: SubmitIn, ctx: Ctx = Depends(get_ctx)):
    p = _plan(ctx, pid)
    if p.owner_id != ctx.user.id and not ctx.p.has("test.edit", project_id=p.project_id):
        raise Forbidden("Only the owner or someone with test edit permission can submit this plan.")
    if p.status != "DRAFT":
        raise AppError("Only a draft plan can be submitted.", code="INVALID_STATE")
    art.submit(ctx.db, a_type="TEST_PLAN", a_id=p.id, revision=p.revision, sha=p.content_sha256, submitter_id=ctx.user.id, reviewers=body.reviewers, approvers=body.approvers,
               excluded={p.owner_id}, title=f"{p.key} {p.title}", link=f"/testing/{p.project_id}?plan={p.id}")
    art.add_event(ctx.db, "TEST_PLAN", p.id, "STATUS", ctx.user.id, p.status, "UNDER_REVIEW")
    p.status, p.version = "UNDER_REVIEW", p.version + 1
    ctx.audit("test.plan.submit", "test_plan", p.id, f"{p.key} submitted for approval", {"sha256": p.content_sha256})
    ctx.db.commit()
    return _plan_detail(ctx, p)


@router.post("/test-plans/{pid}/reviews/{rid}/decide")
def decide_plan(pid: uuid.UUID, rid: uuid.UUID, body: DecisionIn, ctx: Ctx = Depends(get_ctx)):
    p = _plan(ctx, pid)
    r = get_or_404(ctx.db, ArtifactReview, rid, "Review")
    if r.artifact_type != "TEST_PLAN" or r.artifact_id != p.id:
        raise AppError("That review belongs to another record.")
    outcome = art.decide(ctx.db, review=r, user_id=ctx.user.id, decision=body.decision, comment=body.comment, revision=p.revision, sha=p.content_sha256, title=f"{p.key} {p.title}",
                         link=f"/testing/{p.project_id}?plan={p.id}", owner_id=p.owner_id)
    art.add_event(ctx.db, "TEST_PLAN", p.id, "DECISION", ctx.user.id, r.role, r.status, r.comment)
    if outcome != "PENDING":
        to = "APPROVED" if outcome == "APPROVED" else "DRAFT"
        art.add_event(ctx.db, "TEST_PLAN", p.id, "STATUS", ctx.user.id, p.status, to)
        p.status = to
    p.version += 1
    ctx.audit("test.plan.decide", "test_plan", p.id, f"{p.key}: {r.role.lower()} {body.decision.replace('_', ' ')}", {"outcome": outcome, "sha256": r.content_sha256})
    ctx.db.commit()
    return _plan_detail(ctx, p)


@router.post("/test-plans/{pid}/activate")
def activate_plan(pid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    p = _plan(ctx, pid)
    _need(ctx, "test.approve", p.project_id, "Activating a test plan")
    if p.status != "APPROVED":
        raise AppError("Only an approved plan can be activated.", code="INVALID_STATE")
    art.add_event(ctx.db, "TEST_PLAN", p.id, "STATUS", ctx.user.id, p.status, "ACTIVE")
    p.status, p.version = "ACTIVE", p.version + 1
    ctx.audit("test.plan.activate", "test_plan", p.id, f"{p.key} activated")
    ctx.db.commit()
    return _plan_detail(ctx, p)


class SuiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None


class SuiteCasesIn(BaseModel):
    case_ids: list[uuid.UUID] = Field(min_length=1)


def _plan_editable(ctx: Ctx, p: TestPlan) -> None:
    if p.owner_id != ctx.user.id and not ctx.p.has("test.edit", project_id=p.project_id):
        raise Forbidden("Only the owner or someone with test edit permission can change this plan.")
    if p.status in ("UNDER_REVIEW", "CLOSED"):
        raise Conflict("The plan is locked.", code="LOCKED")


@router.post("/test-plans/{pid}/suites")
def add_suite(pid: uuid.UUID, body: SuiteIn, ctx: Ctx = Depends(get_ctx)):
    p = _plan(ctx, pid)
    _plan_editable(ctx, p)
    if body.parent_id and get_or_404(ctx.db, TestSuite, body.parent_id, "Suite").plan_id != p.id:
        raise AppError("The parent suite belongs to another plan.")
    s = TestSuite(plan_id=p.id, parent_id=body.parent_id, name=body.name)
    ctx.db.add(s)
    ctx.db.flush()
    ctx.audit("test.suite.create", "test_plan", p.id, f"{p.key}: suite {s.name} added")
    ctx.db.commit()
    return _plan_detail(ctx, p)


@router.post("/test-suites/{sid}/cases")
def add_suite_cases(sid: uuid.UUID, body: SuiteCasesIn, ctx: Ctx = Depends(get_ctx)):
    s = get_or_404(ctx.db, TestSuite, sid, "Suite")
    p = _plan(ctx, s.plan_id)
    _plan_editable(ctx, p)
    have = set(ctx.db.execute(select(TestSuiteCase.case_id).where(TestSuiteCase.suite_id == s.id)).scalars())
    for i, cid in enumerate(body.case_ids):
        c = get_or_404(ctx.db, TestCase, cid, "Test case")
        if c.project_id != p.project_id:
            raise AppError(f"{c.key} belongs to another project.")
        if c.status == "OBSOLETE":
            raise AppError(f"{c.key} is obsolete.")
        if cid not in have:
            ctx.db.add(TestSuiteCase(suite_id=s.id, case_id=cid, sort_order=len(have) + i))
    ctx.audit("test.suite.cases", "test_plan", p.id, f"{p.key}: {len(body.case_ids)} case(s) assigned to {s.name}")
    ctx.db.commit()
    return _plan_detail(ctx, p)


@router.delete("/test-suites/{sid}/cases/{cid}")
def remove_suite_case(sid: uuid.UUID, cid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    s = get_or_404(ctx.db, TestSuite, sid, "Suite")
    p = _plan(ctx, s.plan_id)
    _plan_editable(ctx, p)
    row = ctx.db.execute(select(TestSuiteCase).where(TestSuiteCase.suite_id == s.id, TestSuiteCase.case_id == cid)).scalar_one_or_none()
    if row:
        ctx.db.delete(row)
    ctx.audit("test.suite.cases", "test_plan", p.id, f"{p.key}: case removed from {s.name}")
    ctx.db.commit()
    return _plan_detail(ctx, p)


# ------------------------------------------------------------------ runs
class RunIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    build_version: str | None = Field(default=None, max_length=120)
    environment: str | None = Field(default=None, max_length=200)
    executor_id: uuid.UUID | None = None
    case_ids: list[uuid.UUID] | None = None


def _run(ctx: Ctx, rid: uuid.UUID) -> TestRun:
    r = get_or_404(ctx.db, TestRun, rid, "Test run")
    _view(ctx, r.project_id)
    return r


@router.post("/test-plans/{pid}/runs")
def create_run(pid: uuid.UUID, body: RunIn, ctx: Ctx = Depends(get_ctx)):
    p = _plan(ctx, pid)
    _need(ctx, "test.edit", p.project_id, "Creating test runs")
    if p.status != "ACTIVE":
        raise AppError("Runs can be created only from an active (approved and activated) plan.", code="INVALID_STATE")
    in_plan = list(ctx.db.execute(select(TestSuiteCase.case_id).join(TestSuite, TestSuite.id == TestSuiteCase.suite_id).where(TestSuite.plan_id == p.id)).scalars())
    wanted = body.case_ids or list(dict.fromkeys(in_plan))
    if not wanted:
        raise AppError("The plan has no test cases. Add cases to a suite first.")
    proj = ctx.db.get(Project, p.project_id)
    run = TestRun(plan_id=p.id, project_id=p.project_id, key=svc.run_key(ctx.db, proj.code), title=body.title, build_version=body.build_version or p.build_version, environment=body.environment,
                  executor_id=body.executor_id or ctx.user.id, created_by_id=ctx.user.id)
    ctx.db.add(run)
    ctx.db.flush()
    for i, cid in enumerate(wanted):
        if cid not in in_plan:
            raise AppError("Every case in a run must belong to the plan.")
        c = ctx.db.get(TestCase, cid)
        if c.status != "APPROVED":
            raise AppError(f"{c.key} is {c.status.lower().replace('_', ' ')}; only approved test cases can be executed.", code="CASE_NOT_APPROVED")
        ctx.db.add(TestRunCase(run_id=run.id, case_id=cid, case_revision=c.revision, assignee_id=run.executor_id, sort_order=i))
    ctx.audit("test.run.create", "test_run", run.id, f"{run.key} created from {p.key} ({len(wanted)} cases)", {"build": run.build_version})
    ctx.db.commit()
    return _run_detail(ctx, run)


def _run_detail(ctx: Ctx, run: TestRun) -> dict:
    db = ctx.db
    rows = db.execute(select(TestRunCase, TestCase).join(TestCase, TestCase.id == TestRunCase.case_id).where(TestRunCase.run_id == run.id).order_by(TestRunCase.sort_order)).all()
    exs = db.execute(select(TestExecution).where(TestExecution.run_case_id.in_([rc.id for rc, _ in rows] or [uuid.uuid4()])).order_by(TestExecution.executed_at)).scalars().all()
    ev = db.execute(select(TestEvidence, FileObject).join(FileObject, FileObject.id == TestEvidence.file_id).where(TestEvidence.execution_id.in_([e.id for e in exs] or [uuid.uuid4()]))).all()
    defects = {d.id: d for d in db.execute(select(Defect).where(Defect.id.in_({e.defect_id for e in exs if e.defect_id} | {uuid.uuid4()}))).scalars()}
    users = _users(ctx, {run.executor_id, run.closed_by_id} | {e.tester_id for e in exs})
    evidence: dict = {}
    for t, f in ev:
        evidence.setdefault(t.execution_id, []).append({"id": str(t.id), "kind": t.kind, "name": f.original_name, "size": f.size_bytes, "sha256": f.sha256, "at": iso(t.uploaded_at)})
    by_rc: dict = {}
    for e in exs:
        d = defects.get(e.defect_id)
        by_rc.setdefault(e.run_case_id, []).append({"id": str(e.id), "result": e.result, "actual_result": e.actual_result, "failure_cause": e.failure_cause, "is_retest": e.is_retest, "source": e.source,
                                                    "defect": {"id": str(d.id), "key": d.key, "status": d.status, "severity": d.severity} if d else None, "tester": user_brief(users.get(e.tester_id)),
                                                    "executed_at": iso(e.executed_at), "notes": e.notes, "evidence": evidence.get(e.id, [])})
    plan = db.get(TestPlan, run.plan_id)
    revs = {(r.case_id, r.revision): r for r in db.execute(select(TestCaseRevision).where(TestCaseRevision.case_id.in_([c.id for _, c in rows] or [uuid.uuid4()]))).scalars()}
    can_exec = ctx.p.has("test.edit", project_id=run.project_id)
    return {"id": str(run.id), "key": run.key, "title": run.title, "status": run.status, "build_version": run.build_version, "environment": run.environment, "project_id": str(run.project_id),
            "plan": {"id": str(plan.id), "key": plan.key, "title": plan.title}, "executor": user_brief(users.get(run.executor_id)), "closed_at": iso(run.closed_at), "closed_by": user_brief(users.get(run.closed_by_id)),
            "closure_note": run.closure_note, "can_execute": can_exec and run.status != "CLOSED", "can_close": ctx.p.has("test.approve", project_id=run.project_id) and run.status != "CLOSED", "version": run.version,
            "exit": svc.evaluate_exit(db, run), "failure_causes": svc.failure_causes(db),
            "cases": [{"id": str(rc.id), "status": rc.status, "executions": by_rc.get(rc.id, []),
                       # the steps of the revision that is being executed, even if the case has changed since
                       "case": {"id": str(c.id), "key": c.key, "title": c.title, "revision": rc.case_revision, "automation_id": c.automation_id, "steps": _snapshot_steps(revs.get((c.id, rc.case_revision)))}} for rc, c in rows]}


def _snapshot_steps(rev: TestCaseRevision | None) -> list:
    return json.loads(rev.snapshot).get("steps") or [] if rev else []


@router.get("/projects/{pid}/test-runs")
def list_runs(pid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    _project(ctx, pid)
    rows = ctx.db.execute(select(TestRun).where(TestRun.project_id == pid).order_by(TestRun.created_at.desc())).scalars().all()
    out = []
    for r in rows:
        e = svc.evaluate_exit(ctx.db, r)
        out.append({"id": str(r.id), "key": r.key, "title": r.title, "status": r.status, "build_version": r.build_version, "counts": e["counts"], "total": e["total"], "pass_rate": e["pass_rate"], "created_at": iso(r.created_at)})
    return out


@router.get("/test-runs/{rid}")
def get_run(rid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    return _run_detail(ctx, _run(ctx, rid))


class NewDefectIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    description: str | None = None
    severity: str = Field(default="MEDIUM", pattern=SEVERITIES)
    assignee_id: uuid.UUID | None = None


class ExecuteIn(BaseModel):
    result: str = Field(pattern=r"^(PASSED|FAILED|BLOCKED|SKIPPED)$")
    actual_result: str | None = Field(default=None, max_length=8000)
    failure_cause: str | None = Field(default=None, max_length=40)
    defect_id: uuid.UUID | None = None
    new_defect: NewDefectIn | None = None
    notes: str | None = Field(default=None, max_length=8000)


def _create_defect(ctx: Ctx, project_id: uuid.UUID, body: NewDefectIn, *, found_in: str | None, item_id=None) -> Defect:
    proj = ctx.db.get(Project, project_id)
    d = Defect(project_id=project_id, key=svc.next_key(ctx.db, proj.code, "DEF"), title=body.title, description=body.description, severity=body.severity, assignee_id=body.assignee_id, reporter_id=ctx.user.id,
               found_in_build=found_in, item_id=item_id)
    ctx.db.add(d)
    ctx.db.flush()
    art.add_event(ctx.db, "DEFECT", d.id, "CREATED", ctx.user.id, to="OPEN")
    if d.assignee_id and d.assignee_id != ctx.user.id:
        from app.services.notify import notify

        notify(ctx.db, d.assignee_id, "defect.assigned", f"Defect {d.key} assigned to you", d.title, link=f"/testing/{project_id}?defect={d.id}", severity="warning")
    ctx.audit("defect.create", "defect", d.id, f"{d.key} raised: {d.title}", {"severity": d.severity})
    return d


@router.post("/test-runs/{rid}/cases/{rcid}/execute")
def execute_case(rid: uuid.UUID, rcid: uuid.UUID, body: ExecuteIn, version: int | None = None, ctx: Ctx = Depends(get_ctx)):
    run = _run(ctx, rid)
    _need(ctx, "test.edit", run.project_id, "Recording test results")
    rc = get_or_404(ctx.db, TestRunCase, rcid, "Run case")
    if rc.run_id != run.id:
        raise AppError("That case belongs to another run.")
    defect = None
    if body.defect_id:
        defect = get_or_404(ctx.db, Defect, body.defect_id, "Defect")
        if defect.project_id != run.project_id:
            raise AppError("The defect belongs to another project.")
        if defect.status not in svc.OPEN_DEFECT:
            raise AppError(f"{defect.key} is {defect.status.lower()}; link an open defect or raise a new one.")
    causes = {c["code"]: c for c in svc.failure_causes(ctx.db)}
    case = ctx.db.get(TestCase, rc.case_id)
    if body.result == "FAILED" and causes.get(body.failure_cause or "", {}).get("creates_defect") and defect is None and rc.status != "RETEST":
        nd = body.new_defect or NewDefectIn(title=f"{case.key} fails: {case.title}"[:300], description=body.actual_result, severity="MEDIUM")
        defect = _create_defect(ctx, run.project_id, nd, found_in=run.build_version, item_id=case.item_id)
        art.add_link(ctx.db, from_type="DEFECT", from_id=defect.id, to_type="TEST_CASE", to_id=case.id, link_type="found_by", section=None, actor=ctx.user.id)
    ex = svc.record_execution(ctx.db, rc, run, result=body.result, tester_id=ctx.user.id, actual=body.actual_result, cause=body.failure_cause, defect=defect, notes=body.notes)
    run.version += 1
    ctx.audit("test.execute", "test_run", run.id, f"{run.key} {case.key}: {body.result}{' (retest)' if ex.is_retest else ''}", {"execution": str(ex.id), "cause": body.failure_cause, "defect": str(ex.defect_id) if ex.defect_id else None})
    ctx.db.commit()
    return _run_detail(ctx, run)


@router.post("/test-executions/{eid}/evidence")
async def add_evidence(eid: uuid.UUID, file: UploadFile = File(...), kind: str = Form("ATTACHMENT"), ctx: Ctx = Depends(get_ctx)):
    ex = get_or_404(ctx.db, TestExecution, eid, "Execution")
    rc = ctx.db.get(TestRunCase, ex.run_case_id)
    run = _run(ctx, rc.run_id)
    _need(ctx, "test.edit", run.project_id, "Adding test evidence")
    if kind not in ("SCREENSHOT", "LOG", "VIDEO", "TRACE", "REPORT", "ATTACHMENT"):
        raise AppError("Unknown evidence kind.")
    data = await file.read()
    ext = storage.ext_of(file.filename or "")
    storage.validate_content(data, ext, ["png", "jpg", "jpeg", "pdf", "txt", "log", "json", "xml", "zip", "mp4", "webm", "csv", "html", "docx", "xlsx"])
    fo = storage.put_bytes(ctx.db, data, file.filename or f"evidence.{ext}", ctx.user.id)
    t = TestEvidence(execution_id=ex.id, file_id=fo.id, kind=kind, uploaded_by_id=ctx.user.id)
    ctx.db.add(t)
    ctx.db.flush()
    ctx.audit("test.evidence", "test_run", run.id, f"{run.key}: evidence {fo.original_name} added", {"sha256": fo.sha256, "execution": str(ex.id)})
    ctx.db.commit()
    return {"id": str(t.id), "name": fo.original_name, "sha256": fo.sha256, "size": fo.size_bytes}


@router.get("/test-evidence/{tid}/file")
def evidence_file(tid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    t = get_or_404(ctx.db, TestEvidence, tid, "Evidence")
    ex = ctx.db.get(TestExecution, t.execution_id)
    _run(ctx, ctx.db.get(TestRunCase, ex.run_case_id).run_id)
    f = ctx.db.get(FileObject, t.file_id)
    data = storage.read_bytes(f, verify=True)
    inline = f.extension in ("png", "jpg", "jpeg", "pdf", "txt", "log")
    mime = "text/plain" if f.extension in ("txt", "log", "html") else f.mime_type
    return Response(content=data, media_type=mime, headers={"Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{storage.safe_name(f.original_name)}"', "X-Content-SHA256": f.sha256})


class CloseIn(BaseModel):
    note: str = Field(min_length=3, max_length=4000)
    manual_confirmed: list[bool] = Field(default_factory=list)


@router.post("/test-runs/{rid}/close")
def close_run(rid: uuid.UUID, body: CloseIn, ctx: Ctx = Depends(get_ctx)):
    run = _run(ctx, rid)
    _need(ctx, "test.approve", run.project_id, "Closing a test run")
    if run.status == "CLOSED":
        raise AppError("The run is already closed.")
    if run.executor_id == ctx.user.id:
        raise Forbidden("The executor of a run cannot close it; closure is an independent check.", code="SOD_VIOLATION")
    e = svc.evaluate_exit(ctx.db, run)
    failed = [c["label"] + f" ({c['detail']})" for c in e["checks"] if not c["ok"]]
    if len(body.manual_confirmed) != len(e["manual"]) or not all(body.manual_confirmed):
        failed += [m["label"] for i, m in enumerate(e["manual"]) if i >= len(body.manual_confirmed) or not body.manual_confirmed[i]]
    if failed:
        raise AppError("Exit criteria are not met.", code="GATE_BLOCKED", details={"errors": failed})
    run.status, run.closed_at, run.closed_by_id, run.closure_note = "CLOSED", utcnow(), ctx.user.id, body.note
    run.closure_evaluation = json.dumps(e, default=str)
    run.version += 1
    ctx.audit("test.run.close", "test_run", run.id, f"{run.key} closed ({e['pass_rate']}% passed)", {"evaluation": e["checks"]})
    ctx.db.commit()
    return _run_detail(ctx, run)


# ------------------------------------------------------------------ defects
class DefectIn(NewDefectIn):
    priority: str = Field(default="MEDIUM", pattern=SEVERITIES)
    item_id: uuid.UUID | None = None
    work_item_id: uuid.UUID | None = None
    found_in_build: str | None = Field(default=None, max_length=120)


class DefectMoveIn(BaseModel):
    to: str = Field(min_length=2, max_length=20)
    comment: str | None = Field(default=None, max_length=4000)
    fixed_in_build: str | None = Field(default=None, max_length=120)


def _defect(ctx: Ctx, did: uuid.UUID) -> Defect:
    d = get_or_404(ctx.db, Defect, did, "Defect")
    _view(ctx, d.project_id)
    return d


def _defect_brief(d: Defect, users: dict) -> dict:
    return {"id": str(d.id), "key": d.key, "title": d.title, "severity": d.severity, "priority": d.priority, "status": d.status, "assignee": user_brief(users.get(d.assignee_id)),
            "reporter": user_brief(users.get(d.reporter_id)), "found_in_build": d.found_in_build, "fixed_in_build": d.fixed_in_build, "updated_at": iso(d.updated_at), "version": d.version}


def _defect_detail(ctx: Ctx, d: Defect) -> dict:
    db = ctx.db
    users = _users(ctx, {d.assignee_id, d.reporter_id, d.fixed_by_id})
    manager = ctx.p.has("defect.manage", project_id=d.project_id)
    tester = ctx.p.has("test.edit", project_id=d.project_id)
    exs = db.execute(select(TestExecution, TestRunCase, TestRun, TestCase).join(TestRunCase, TestRunCase.id == TestExecution.run_case_id).join(TestRun, TestRun.id == TestRunCase.run_id)
                     .join(TestCase, TestCase.id == TestRunCase.case_id).where(TestExecution.defect_id == d.id).order_by(TestExecution.executed_at)).all()
    task = db.get(WorkItem, d.work_item_id) if d.work_item_id else None
    return {**_defect_brief(d, users), "project_id": str(d.project_id), "description": d.description, "resolution": d.resolution, "fixed_by": user_brief(users.get(d.fixed_by_id)),
            "task": {"id": str(task.id), "key": task.key, "title": task.title, "status": task.status} if task and can_view_task(db, ctx.p, task) else None,
            "can_edit": manager or ctx.user.id in (d.reporter_id, d.assignee_id), "transitions": svc.defect_transitions_for(d, ctx.user.id, manager=manager, tester=tester),
            "executions": [{"id": str(e.id), "result": e.result, "is_retest": e.is_retest, "at": iso(e.executed_at), "run": {"id": str(r.id), "key": r.key}, "case": {"id": str(c.id), "key": c.key, "title": c.title}} for e, _, r, c in exs],
            "links": art.links(db, "DEFECT", d.id, _see(ctx)), "history": art.history(db, "DEFECT", d.id)}


@router.get("/projects/{pid}/defects")
def list_defects(pid: uuid.UUID, status: str | None = None, severity: str | None = None, ctx: Ctx = Depends(get_ctx)):
    _project(ctx, pid)
    s = select(Defect).where(Defect.project_id == pid)
    if status:
        s = s.where(Defect.status.in_(status.split(",")))
    if severity:
        s = s.where(Defect.severity.in_(severity.split(",")))
    rows = ctx.db.execute(s.order_by(Defect.created_at.desc())).scalars().all()
    users = _users(ctx, {d.assignee_id for d in rows} | {d.reporter_id for d in rows})
    return {"states": svc.DEFECT_STATES, "can_raise": ctx.p.has("test.edit", project_id=pid) or ctx.p.has("defect.manage", project_id=pid), "items": [_defect_brief(d, users) for d in rows]}


@router.post("/projects/{pid}/defects")
def raise_defect(pid: uuid.UUID, body: DefectIn, ctx: Ctx = Depends(get_ctx)):
    _project(ctx, pid)
    if not (ctx.p.has("test.edit", project_id=pid) or ctx.p.has("defect.manage", project_id=pid)):
        raise Forbidden("Raising defects needs test edit or defect management permission in this project.")
    d = _create_defect(ctx, pid, body, found_in=body.found_in_build, item_id=body.item_id)
    d.priority, d.work_item_id = body.priority, body.work_item_id
    ctx.db.commit()
    return _defect_detail(ctx, d)


@router.get("/defects/{did}")
def get_defect(did: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    return _defect_detail(ctx, _defect(ctx, did))


@router.put("/defects/{did}")
def update_defect(did: uuid.UUID, body: DefectIn, version: int | None = None, ctx: Ctx = Depends(get_ctx)):
    d = _defect(ctx, did)
    manager = ctx.p.has("defect.manage", project_id=d.project_id)
    if not manager and ctx.user.id not in (d.reporter_id, d.assignee_id):
        raise Forbidden("Only the reporter, the assignee or a defect manager can change this defect.")
    _check_version(version, d)
    if body.assignee_id != d.assignee_id and not manager:
        raise Forbidden("Assigning defects needs defect management permission.")
    if body.work_item_id:
        t = get_or_404(ctx.db, WorkItem, body.work_item_id, "Task")
        if t.project_id != d.project_id:
            raise AppError("The fix task belongs to another project.")
    old_assignee = d.assignee_id
    d.title, d.description, d.severity, d.priority, d.assignee_id, d.item_id, d.work_item_id = body.title, body.description, body.severity, body.priority, body.assignee_id, body.item_id, body.work_item_id
    d.found_in_build = body.found_in_build
    d.version += 1
    if d.assignee_id and d.assignee_id != old_assignee and d.assignee_id != ctx.user.id:
        from app.services.notify import notify

        notify(ctx.db, d.assignee_id, "defect.assigned", f"Defect {d.key} assigned to you", d.title, link=f"/testing/{d.project_id}?defect={d.id}", severity="warning")
    ctx.audit("defect.update", "defect", d.id, f"{d.key} updated")
    ctx.db.commit()
    return _defect_detail(ctx, d)


@router.post("/defects/{did}/transition")
def move_defect(did: uuid.UUID, body: DefectMoveIn, version: int | None = None, ctx: Ctx = Depends(get_ctx)):
    d = _defect(ctx, did)
    _check_version(version, d)
    old = svc.move_defect(ctx.db, d, body.to, user_id=ctx.user.id, manager=ctx.p.has("defect.manage", project_id=d.project_id), tester=ctx.p.has("test.edit", project_id=d.project_id),
                          comment=body.comment, fixed_in_build=body.fixed_in_build)
    if body.to in ("REJECTED", "CLOSED", "DEFERRED") and body.comment:
        d.resolution = body.comment
    ctx.audit("defect.transition", "defect", d.id, f"{d.key} {old} → {d.status}", {"reason": body.comment, "fixed_in_build": body.fixed_in_build})
    ctx.db.commit()
    return _defect_detail(ctx, d)


@router.post("/defects/{did}/links")
def link_defect(did: uuid.UUID, body: LinkIn, ctx: Ctx = Depends(get_ctx)):
    d = _defect(ctx, did)
    if not (ctx.p.has("defect.manage", project_id=d.project_id) or ctx.user.id in (d.reporter_id, d.assignee_id)):
        raise Forbidden("Only the reporter, the assignee or a defect manager can link this defect.")
    if not _see(ctx)(body.to_type, body.to_id):
        raise Forbidden("You do not have access to the record you are linking.")
    art.add_link(ctx.db, from_type="DEFECT", from_id=d.id, to_type=body.to_type, to_id=body.to_id, link_type="affects" if body.link_type == "verifies" else body.link_type, section=None, actor=ctx.user.id)
    ctx.audit("defect.link", "defect", d.id, f"{d.key} linked to {body.to_type.lower()}")
    ctx.db.commit()
    return _defect_detail(ctx, d)


# ------------------------------------------------------------------ automation (§13.5)
def _runners() -> list[str]:
    return [x.strip().lower() for x in (get_settings().test_runners or "").split(",") if x.strip()]


class AutomationIn(BaseModel):
    tool: str = Field(default="playwright", pattern=r"^[a-z0-9_-]{2,40}$")
    run_case_ids: list[uuid.UUID] | None = None


@router.post("/test-runs/{rid}/automation")
def queue_automation(rid: uuid.UUID, body: AutomationIn, ctx: Ctx = Depends(get_ctx)):
    run = _run(ctx, rid)
    _need(ctx, "test.edit", run.project_id, "Starting automated tests")
    if run.status == "CLOSED":
        raise AppError("The run is closed.", code="RUN_CLOSED")
    rows = ctx.db.execute(select(TestRunCase, TestCase).join(TestCase, TestCase.id == TestRunCase.case_id).where(TestRunCase.run_id == run.id)).all()
    chosen = [rc for rc, c in rows if c.automation_id and (not body.run_case_ids or rc.id in body.run_case_ids) and (c.automation_tool or body.tool) == body.tool]
    if not chosen:
        raise AppError(f"No case in this run is mapped to {body.tool} (set the automation id on the test case).", code="NOTHING_TO_RUN")
    job = TestAutomationJob(run_id=run.id, tool=body.tool, case_ids=json.dumps([str(rc.id) for rc in chosen]), requested_by_id=ctx.user.id)
    ctx.db.add(job)
    ctx.db.flush()
    ctx.audit("test.automation.queue", "test_run", run.id, f"{run.key}: {len(chosen)} case(s) queued for {body.tool}", {"job": str(job.id)})
    ctx.db.commit()
    return _job(job)


def _job(j: TestAutomationJob) -> dict:
    return {"id": str(j.id), "run_id": str(j.run_id), "tool": j.tool, "status": j.status, "cases": len(json.loads(j.case_ids or "[]")), "error": j.error, "results_received": j.results_received,
            "created_at": iso(j.created_at), "started_at": iso(j.started_at), "finished_at": iso(j.finished_at)}


@router.get("/test-runs/{rid}/automation")
def list_automation(rid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    run = _run(ctx, rid)
    return [_job(j) for j in ctx.db.execute(select(TestAutomationJob).where(TestAutomationJob.run_id == run.id).order_by(TestAutomationJob.created_at.desc())).scalars()]


def _runner_auth(token: str | None) -> None:
    secret = get_settings().test_results_token
    if not secret or not hmac.compare_digest((token or "").encode(), secret.encode()):
        raise Unauthorized("Invalid or missing test-runner token.")


@router.post("/test-automation/claim")
def claim_job(tool: str = Query(..., pattern=r"^[a-z0-9_-]{2,40}$"), x_elm_runner_token: str | None = Header(None), db=Depends(get_db)):
    """A registered runner (in its own controlled environment) takes the next queued job for its tool. It gets only the
    automation ids it must run, never database access."""
    _runner_auth(x_elm_runner_token)
    if tool not in _runners():
        raise AppError(f"{tool} is not a registered runner (ELM_TEST_RUNNERS).", code="RUNNER_UNKNOWN", status_code=403)
    job = db.execute(select(TestAutomationJob).where(TestAutomationJob.tool == tool, TestAutomationJob.status == "QUEUED").order_by(TestAutomationJob.created_at).limit(1).with_for_update()).scalar_one_or_none()
    if not job:
        return {"job": None}
    job.status, job.started_at = "RUNNING", utcnow()
    ids = [uuid.UUID(x) for x in json.loads(job.case_ids)]
    rows = db.execute(select(TestRunCase, TestCase).join(TestCase, TestCase.id == TestRunCase.case_id).where(TestRunCase.id.in_(ids))).all()
    run = db.get(TestRun, job.run_id)
    auditsvc.record(db, actor_id=None, action="test.automation.claim", entity_type="test_run", entity_id=run.id, summary=f"{run.key}: {tool} runner started job", data={"job": str(job.id)})
    db.commit()
    return {"job": {"id": str(job.id), "run": run.key, "build_version": run.build_version, "environment": run.environment, "cases": [{"run_case_id": str(rc.id), "key": c.key, "automation_id": c.automation_id} for rc, c in rows]}}


class ResultIn(BaseModel):
    run_case_id: uuid.UUID
    result: str = Field(pattern=r"^(PASSED|FAILED|BLOCKED|SKIPPED)$")
    external_result_id: str = Field(min_length=1, max_length=200)
    actual_result: str | None = Field(default=None, max_length=8000)
    failure_cause: str | None = Field(default=None, max_length=40)
    duration_seconds: float | None = Field(default=None, ge=0)


class ResultsIn(BaseModel):
    job_id: uuid.UUID
    results: list[ResultIn] = Field(default_factory=list)
    finished: bool = True
    error: str | None = Field(default=None, max_length=1000)


@router.post("/test-automation/results")
def ingest_results(body: ResultsIn, x_elm_runner_token: str | None = Header(None), db=Depends(get_db)):
    """Validated ingestion. external_result_id makes re-deliveries idempotent, so retries never duplicate executions.
    An automated failure is recorded with its cause; a defect is never raised automatically (a person triages it)."""
    _runner_auth(x_elm_runner_token)
    job = db.get(TestAutomationJob, body.job_id)
    if not job or job.status not in ("RUNNING", "QUEUED"):
        raise AppError("Unknown or finished job.", code="JOB_STATE", status_code=409)
    run = db.get(TestRun, job.run_id)
    allowed = {uuid.UUID(x) for x in json.loads(job.case_ids)}
    created = duplicates = 0
    for r in body.results:
        if r.run_case_id not in allowed:
            raise AppError("A result refers to a case that is not part of this job.", code="NOT_IN_JOB")
        if db.execute(select(TestExecution.id).where(TestExecution.external_result_id == r.external_result_id)).first():
            duplicates += 1
            continue
        rc = db.get(TestRunCase, r.run_case_id)
        cause = r.failure_cause or ("automation_script" if r.result == "FAILED" else None)
        causes = {c["code"]: c for c in svc.failure_causes(db)}
        if r.result == "FAILED" and causes.get(cause, {}).get("creates_defect"):
            cause = None  # an application defect is a human conclusion; the result is recorded as BLOCKED for triage
            ex = svc.record_execution(db, rc, run, result="BLOCKED", tester_id=None, actual=r.actual_result, cause=None, defect=None, notes="Automated failure reported as an application defect; needs triage.", source="AUTOMATION", external_id=r.external_result_id, duration=r.duration_seconds)
        else:
            ex = svc.record_execution(db, rc, run, result=r.result, tester_id=None, actual=r.actual_result, cause=cause, defect=None, source="AUTOMATION", external_id=r.external_result_id, duration=r.duration_seconds)
        created += 1 if ex else 0
    job.results_received += created
    if body.finished or body.error:
        job.status, job.finished_at, job.error = ("FAILED" if body.error else "SUCCEEDED"), utcnow(), body.error
    auditsvc.record(db, actor_id=None, action="test.automation.results", entity_type="test_run", entity_id=run.id, summary=f"{run.key}: {created} automated result(s) recorded", data={"job": str(job.id), "duplicates": duplicates})
    db.commit()
    return {"recorded": created, "duplicates": duplicates, "job": _job(job)}


def sweep_automation(db, now=None) -> int:
    """Worker step: a queued job for a tool with no registered runner, or one running too long, fails clearly (never a false pass)."""
    now = now or utcnow()
    runners = _runners()
    n = 0
    for j in db.execute(select(TestAutomationJob).where(TestAutomationJob.status.in_(["QUEUED", "RUNNING"]))).scalars():
        if j.status == "QUEUED" and j.tool not in runners:
            j.status, j.finished_at, j.error = "FAILED", now, f"No {j.tool} runner is installed or registered (ELM_TEST_RUNNERS). Nothing was executed."
        elif j.status == "RUNNING" and j.started_at and now - j.started_at > timedelta(hours=get_settings().test_job_timeout_hours):
            j.status, j.finished_at, j.error = "FAILED", now, "The runner did not report back in time."
        else:
            continue
        n += 1
        if j.requested_by_id:
            from app.services.notify import notify

            run = db.get(TestRun, j.run_id)
            notify(db, j.requested_by_id, "test.automation", f"Automated job for {run.key} failed", j.error, link=f"/testing/{run.project_id}?run={run.id}", severity="warning")
    return n


@router.get("/projects/{pid}/test-summary")
def test_summary(pid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    """Coverage of requirements by approved test cases and their latest results (feeds the RTM)."""
    _project(ctx, pid)
    reqs = ctx.db.execute(select(Requirement).where(Requirement.project_id == pid)).scalars().all()
    cover = art.linked_ids(ctx.db, "TEST_CASE", "REQUIREMENT", [r.id for r in reqs], ("verifies",))
    cases = {c.id: c for c in ctx.db.execute(select(TestCase).where(TestCase.project_id == pid)).scalars()}
    last = svc.last_results_for_cases(ctx.db, list(cases))
    covered = sum(1 for r in reqs if any(cases.get(cid) and cases[cid].status == "APPROVED" for cid in cover.get(r.id, [])))
    passing = sum(1 for r in reqs if cover.get(r.id) and all((last.get(cid) or {}).get("result") == "PASSED" for cid in cover[r.id]))
    defects = ctx.db.execute(select(Defect).where(Defect.project_id == pid)).scalars().all()
    by_status: dict = {}
    for d in defects:
        by_status[d.status] = by_status.get(d.status, 0) + 1
    return {"requirements": len(reqs), "covered_by_approved_cases": covered, "all_linked_cases_passing": passing, "cases": len(cases), "defects_by_status": by_status}
