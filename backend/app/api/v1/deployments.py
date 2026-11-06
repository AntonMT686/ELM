"""Deployment and software release API (architecture §14). Environments with approved configurations, deployment
requests with hash-bound approvals, validation gates, queued execution, manual / CI results, retry, cancel, rollback.
Every mutation is audited in the same transaction; scope is checked on every endpoint."""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.db import get_db, utcnow
from app.core.deps import Ctx, get_ctx, get_or_404
from app.core.errors import AppError, Conflict, Forbidden, Unauthorized
from app.models import Document, Project, WorkItem
from app.models.artifacts import ArtifactReview
from app.models.deployment import Deployment, DeploymentAttempt, DeploymentEnvironment
from app.models.scm import ScmLink, ScmRepository
from app.models.testing import TestRun
from app.services import artifacts as art
from app.services import deployment as svc
from app.services.authz import can_view_document
from app.services.planning import can_view_project, can_view_task, require_view_project
from app.services.serial import iso, user_brief

router = APIRouter(tags=["deployments"])
A = svc.A


def _project(ctx: Ctx, pid: uuid.UUID) -> Project:
    p = get_or_404(ctx.db, Project, pid, "Project")
    require_view_project(ctx.db, ctx.p, pid)
    return p


def _need(ctx: Ctx, perm: str, project_id: uuid.UUID, what: str) -> None:
    if not ctx.p.has(perm, project_id=project_id):
        raise Forbidden(f"{what} needs the {perm} permission for this project.", details={"permission": perm})


def _users(ctx: Ctx, ids) -> dict:
    return art._users(ctx.db, ids)


# ------------------------------------------------------------------ environments
class EnvIn(BaseModel):
    code: str = Field(pattern=r"^[A-Z0-9_-]{2,30}$")
    name: str = Field(min_length=2, max_length=150)
    description: str | None = None
    sort_order: int = 0
    active: bool = True
    config: dict = Field(default_factory=dict)


def _env_dict(ctx: Ctx, e: DeploymentEnvironment) -> dict:
    cur = svc.current_on(ctx.db, e.id)
    users = _users(ctx, {e.config_approved_by_id, e.config_changed_by_id})
    return {"id": str(e.id), "project_id": str(e.project_id), "code": e.code, "name": e.name, "description": e.description, "sort_order": e.sort_order, "active": e.active,
            "config": svc.env_config(e), "config_sha256": e.config_sha256, "config_status": "APPROVED" if e.config_status == "APPROVED" and e.config_approved_sha256 == e.config_sha256 else "DRAFT",
            "config_approved_by": user_brief(users.get(e.config_approved_by_id)), "config_approved_at": iso(e.config_approved_at), "config_changed_by": user_brief(users.get(e.config_changed_by_id)),
            "current": {"id": str(cur.id), "key": cur.key, "version_label": cur.version_label, "deployed_at": iso(cur.deployed_at)} if cur else None, "version": e.version}


@router.get("/projects/{pid}/deploy-environments")
def list_environments(pid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    _project(ctx, pid)
    rows = ctx.db.execute(select(DeploymentEnvironment).where(DeploymentEnvironment.project_id == pid).order_by(DeploymentEnvironment.sort_order, DeploymentEnvironment.code)).scalars().all()
    return {"can_configure": ctx.p.has("deploy.configure", project_id=pid), "can_approve": ctx.p.has("deploy.approve", project_id=pid), "default_config": svc.DEFAULT_CONFIG,
            "adapters": list(svc.ADAPTERS), "items": [_env_dict(ctx, e) for e in rows]}


@router.post("/projects/{pid}/deploy-environments")
def create_environment(pid: uuid.UUID, body: EnvIn, ctx: Ctx = Depends(get_ctx)):
    _project(ctx, pid)
    _need(ctx, "deploy.configure", pid, "Configuring deployment environments")
    if ctx.db.execute(select(DeploymentEnvironment.id).where(DeploymentEnvironment.project_id == pid, DeploymentEnvironment.code == body.code)).first():
        raise AppError(f"Environment {body.code} exists already.", code="DUPLICATE")
    cfg = svc.validate_config(ctx.db, pid, body.config)
    e = DeploymentEnvironment(project_id=pid, code=body.code, name=body.name, description=body.description, sort_order=body.sort_order, active=body.active, config="", config_sha256="")
    svc.set_config(e, cfg, ctx.user.id)
    ctx.db.add(e)
    ctx.db.flush()
    ctx.audit("deploy.env.create", "deploy_environment", e.id, f"Deployment environment {e.code} created", {"config_sha256": e.config_sha256})
    ctx.db.commit()
    return _env_dict(ctx, e)


@router.put("/deploy-environments/{eid}")
def update_environment(eid: uuid.UUID, body: EnvIn, version: int | None = None, ctx: Ctx = Depends(get_ctx)):
    e = get_or_404(ctx.db, DeploymentEnvironment, eid, "Environment")
    _project(ctx, e.project_id)
    _need(ctx, "deploy.configure", e.project_id, "Configuring deployment environments")
    if version is not None and version != e.version:
        raise Conflict("The environment was changed by someone else. Refresh and try again.")
    if body.code != e.code:
        raise AppError("The environment code cannot change.")
    cfg = svc.validate_config(ctx.db, e.project_id, body.config)
    changed = svc.set_config(e, cfg, ctx.user.id)
    e.name, e.description, e.sort_order, e.active = body.name, body.description, body.sort_order, body.active
    e.version += 1
    ctx.audit("deploy.env.update", "deploy_environment", e.id, f"Deployment environment {e.code} updated" + (" (configuration needs approval again)" if changed else ""), {"config_sha256": e.config_sha256, "config_changed": changed})
    ctx.db.commit()
    return _env_dict(ctx, e)


@router.post("/deploy-environments/{eid}/approve-config")
def approve_config(eid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    e = get_or_404(ctx.db, DeploymentEnvironment, eid, "Environment")
    _project(ctx, e.project_id)
    _need(ctx, "deploy.approve", e.project_id, "Approving a deployment configuration")
    if e.config_changed_by_id == ctx.user.id:
        raise Forbidden("The person who last changed the configuration cannot approve it.", code="SOD_VIOLATION")
    e.config_status, e.config_approved_sha256, e.config_approved_by_id, e.config_approved_at = "APPROVED", e.config_sha256, ctx.user.id, utcnow()
    e.version += 1
    ctx.audit("deploy.env.approve", "deploy_environment", e.id, f"Configuration of {e.code} approved", {"config_sha256": e.config_sha256})
    ctx.db.commit()
    return _env_dict(ctx, e)


# ------------------------------------------------------------------ deployments
class DeploymentIn(BaseModel):
    environment_id: uuid.UUID
    title: str | None = Field(default=None, max_length=300)
    version_label: str = Field(min_length=1, max_length=120)
    repository_id: uuid.UUID | None = None
    git_ref: str | None = Field(default=None, max_length=255)
    commit_sha: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{7,64}$")
    release_notes: str | None = Field(default=None, max_length=50000)
    test_run_id: uuid.UUID | None = None
    task_ids: list[uuid.UUID] = Field(default_factory=list)


def _deployment(ctx: Ctx, did: uuid.UUID) -> Deployment:
    d = get_or_404(ctx.db, Deployment, did, "Deployment")
    if not (can_view_project(ctx.db, ctx.p, d.project_id) or art.is_reviewer(ctx.db, A, d.id, ctx.user.id)):
        raise Forbidden("You do not have access to this deployment.")
    return d


def _brief(d: Deployment, envs: dict, users: dict) -> dict:
    e = envs.get(d.environment_id)
    return {"id": str(d.id), "key": d.key, "title": d.title, "version_label": d.version_label, "git_ref": d.git_ref, "commit_sha": d.commit_sha, "status": d.status, "status_reason": d.status_reason,
            "environment": {"id": str(e.id), "code": e.code, "name": e.name} if e else None, "requested_by": user_brief(users.get(d.requested_by_id)), "deployed_at": iso(d.deployed_at),
            "rollback_of_id": str(d.rollback_of_id) if d.rollback_of_id else None, "created_at": iso(d.created_at), "version": d.version}


def _validate(ctx: Ctx, pid: uuid.UUID, body: DeploymentIn) -> DeploymentEnvironment:
    env = get_or_404(ctx.db, DeploymentEnvironment, body.environment_id, "Environment")
    if env.project_id != pid:
        raise AppError("The environment belongs to another project.")
    if body.repository_id:
        repo = get_or_404(ctx.db, ScmRepository, body.repository_id, "Repository")
        if repo.project_id != pid:
            raise AppError("The repository is not registered for this project.", code="REPO_NOT_ALLOWED")
    if body.test_run_id:
        run = get_or_404(ctx.db, TestRun, body.test_run_id, "Test run")
        if run.project_id != pid:
            raise AppError("The test run belongs to another project.")
    return env


def _draft_notes(ctx: Ctx, task_ids: list[uuid.UUID]) -> str | None:
    """Release notes from the linked tasks and their merge requests (§12 traceability)."""
    if not task_ids:
        return None
    lines = []
    for t in ctx.db.execute(select(WorkItem).where(WorkItem.id.in_(task_ids)).order_by(WorkItem.key)).scalars():
        mrs = ctx.db.execute(select(ScmLink).where(ScmLink.work_item_id == t.id, ScmLink.kind == "MERGE_REQUEST")).scalars().all()
        lines.append(f"- {t.key} {t.title}" + (f" ({', '.join('!' + m.ref + ' ' + (m.state or '') for m in mrs)})" if mrs else ""))
    return "Changes in this release:\n" + "\n".join(lines)


@router.get("/projects/{pid}/deployments")
def list_deployments(pid: uuid.UUID, environment_id: uuid.UUID | None = None, ctx: Ctx = Depends(get_ctx)):
    _project(ctx, pid)
    q = select(Deployment).where(Deployment.project_id == pid)
    if environment_id:
        q = q.where(Deployment.environment_id == environment_id)
    rows = ctx.db.execute(q.order_by(Deployment.created_at.desc())).scalars().all()
    envs = {e.id: e for e in ctx.db.execute(select(DeploymentEnvironment).where(DeploymentEnvironment.project_id == pid)).scalars()}
    users = _users(ctx, {d.requested_by_id for d in rows})
    return {"states": svc.STATES, "can_request": ctx.p.has("deploy.request", project_id=pid), "items": [_brief(d, envs, users) for d in rows]}


@router.post("/projects/{pid}/deployments")
def create_deployment(pid: uuid.UUID, body: DeploymentIn, ctx: Ctx = Depends(get_ctx)):
    p = _project(ctx, pid)
    _need(ctx, "deploy.request", pid, "Requesting a deployment")
    env = _validate(ctx, pid, body)
    for tid in body.task_ids:
        t = get_or_404(ctx.db, WorkItem, tid, "Task")
        if t.project_id != pid or not can_view_task(ctx.db, ctx.p, t):
            raise AppError("Every linked task must be a task of this project that you can see.")
    d = Deployment(project_id=pid, environment_id=env.id, key=svc.next_key(ctx.db, p), title=body.title or f"{body.version_label} to {env.code}", version_label=body.version_label,
                   repository_id=body.repository_id, git_ref=body.git_ref, commit_sha=body.commit_sha.lower() if body.commit_sha else None,
                   release_notes=body.release_notes or _draft_notes(ctx, body.task_ids), test_run_id=body.test_run_id, checklist="{}", requested_by_id=ctx.user.id, content_sha256="")
    d.content_sha256 = svc.content_hash(d)
    ctx.db.add(d)
    ctx.db.flush()
    for tid in body.task_ids:
        art.add_link(ctx.db, from_type=A, from_id=d.id, to_type="TASK", to_id=tid, link_type="includes", section=None, actor=ctx.user.id)
    art.add_event(ctx.db, A, d.id, "CREATED", ctx.user.id, to="PLANNED")
    ctx.audit("deployment.create", "deployment", d.id, f"{d.key} requested: {d.version_label} to {env.code}", {"sha256": d.content_sha256})
    ctx.db.commit()
    return _detail(ctx, d)


def _detail(ctx: Ctx, d: Deployment) -> dict:
    db = ctx.db
    env = db.get(DeploymentEnvironment, d.environment_id)
    c = svc.env_config(env)
    attempts = db.execute(select(DeploymentAttempt).where(DeploymentAttempt.deployment_id == d.id).order_by(DeploymentAttempt.attempt_no.desc())).scalars().all()
    users = _users(ctx, {d.requested_by_id} | {a.triggered_by_id for a in attempts})
    run = db.get(TestRun, d.test_run_id) if d.test_run_id else None
    repo = db.get(ScmRepository, d.repository_id) if d.repository_id else None
    pid = d.project_id
    can_exec = ctx.p.has("deploy.execute", project_id=pid)
    gates = svc.evaluate_gates(db, d) if d.status in ("PLANNED", "AWAITING_APPROVAL", "APPROVED", "FAILED") else None
    ticked = json.loads(d.checklist or "{}")

    def see(t, oid):
        if t == "DOCUMENT":
            o = db.get(Document, oid)
            return bool(o) and can_view_document(db, ctx.p, o)
        if t == "TASK":
            o = db.get(WorkItem, oid)
            return bool(o) and can_view_task(db, ctx.p, o)
        return True

    return {
        **_brief(d, {env.id: env}, users), "project_id": str(pid), "release_notes": d.release_notes, "sha256": d.content_sha256,
        "repository": {"id": str(repo.id), "path": repo.path, "web_url": repo.web_url} if repo else None,
        "test_run": {"id": str(run.id), "key": run.key, "title": run.title, "status": run.status, "build_version": run.build_version} if run else None,
        "rollback_of": _brief(db.get(Deployment, d.rollback_of_id), {env.id: env}, {}) if d.rollback_of_id else None,
        "environment_config": {"requires_approval": c["requires_approval"], "approvals_required": c["approvals_required"], "adapter": c["adapter"], "health_check": bool(c["health_check"])},
        "checklist": [{"text": i, "done": bool(ticked.get(i))} for i in c["checklist"]], "gates": gates,
        "approvals": art.reviews(db, A, d.id, ctx.user.id), "links": art.links(db, A, d.id, see), "history": art.history(db, A, d.id),
        "attempts": [{"id": str(a.id), "attempt_no": a.attempt_no, "adapter": a.adapter, "status": a.status, "queued_at": iso(a.queued_at), "started_at": iso(a.started_at), "finished_at": iso(a.finished_at),
                      "worker": a.worker, "target": a.target, "external_ref": a.external_ref, "external_url": a.external_url, "log": a.log, "health": json.loads(a.health) if a.health else None,
                      "failure_reason": a.failure_reason, "triggered_by": user_brief(users.get(a.triggered_by_id)), "gates": json.loads(a.gate_snapshot or "[]")} for a in attempts],
        "can_edit": d.status == "PLANNED" and (d.requested_by_id == ctx.user.id or ctx.p.has("deploy.request", project_id=pid)),
        "can_execute": can_exec, "can_report": can_exec and any(a.status == "WAITING" and a.adapter == "manual" for a in attempts),
        "can_rollback": can_exec and d.status == "DEPLOYED" and not d.rollback_of_id and _previous(db, d) is not None,
    }


@router.get("/deployments/{did}")
def get_deployment(did: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    return _detail(ctx, _deployment(ctx, did))


@router.put("/deployments/{did}")
def update_deployment(did: uuid.UUID, body: DeploymentIn, version: int | None = None, ctx: Ctx = Depends(get_ctx)):
    d = _deployment(ctx, did)
    if d.status != "PLANNED":
        raise Conflict("Only a planned deployment can be changed; cancel it and request a new one.", code="LOCKED")
    if d.requested_by_id != ctx.user.id and not ctx.p.has("deploy.request", project_id=d.project_id):
        raise Forbidden("Only the requester can change this deployment.")
    if version is not None and version != d.version:
        raise Conflict("The deployment was changed by someone else. Refresh and try again.")
    env = _validate(ctx, d.project_id, body)
    d.environment_id, d.title, d.version_label, d.repository_id, d.git_ref = env.id, body.title or d.title, body.version_label, body.repository_id, body.git_ref
    d.commit_sha, d.release_notes, d.test_run_id = body.commit_sha.lower() if body.commit_sha else None, body.release_notes, body.test_run_id
    d.content_sha256 = svc.content_hash(d)
    d.version += 1
    ctx.audit("deployment.update", "deployment", d.id, f"{d.key} updated", {"sha256": d.content_sha256})
    ctx.db.commit()
    return _detail(ctx, d)


class ChecklistIn(BaseModel):
    item: str = Field(min_length=1, max_length=500)
    done: bool


@router.post("/deployments/{did}/checklist")
def tick_checklist(did: uuid.UUID, body: ChecklistIn, ctx: Ctx = Depends(get_ctx)):
    d = _deployment(ctx, did)
    if d.status not in ("PLANNED", "AWAITING_APPROVAL", "APPROVED", "FAILED"):
        raise Conflict("The checklist is closed once execution has started.", code="LOCKED")
    if d.requested_by_id != ctx.user.id and not ctx.p.has("deploy.execute", project_id=d.project_id):
        raise Forbidden("Only the requester or someone who may execute deployments can tick the checklist.")
    env = ctx.db.get(DeploymentEnvironment, d.environment_id)
    if body.item not in svc.env_config(env)["checklist"]:
        raise AppError("That item is not on this environment's checklist.")
    ticked = json.loads(d.checklist or "{}")
    ticked[body.item] = body.done
    d.checklist = json.dumps(ticked)
    art.add_event(ctx.db, A, d.id, "CHECKLIST", ctx.user.id, None, ("done: " if body.done else "undone: ") + body.item[:100])
    ctx.audit("deployment.checklist", "deployment", d.id, f"{d.key}: checklist '{body.item}' {'done' if body.done else 'not done'}")
    ctx.db.commit()
    return _detail(ctx, d)


class LinkIn(BaseModel):
    to_type: str = Field(pattern=r"^(DOCUMENT|TASK)$")
    to_id: uuid.UUID
    link_type: str = Field(default="includes", pattern=r"^(includes|release_document|related_to)$")


@router.post("/deployments/{did}/links")
def link_deployment(did: uuid.UUID, body: LinkIn, ctx: Ctx = Depends(get_ctx)):
    d = _deployment(ctx, did)
    if d.status not in ("PLANNED", "AWAITING_APPROVAL", "APPROVED", "FAILED"):
        raise Conflict("Links are closed once execution has started.", code="LOCKED")
    if d.requested_by_id != ctx.user.id and not ctx.p.has("deploy.request", project_id=d.project_id):
        raise Forbidden("Only the requester can link records to this deployment.")
    o = ctx.db.get(Document if body.to_type == "DOCUMENT" else WorkItem, body.to_id)
    if not o or (body.to_type == "DOCUMENT" and not can_view_document(ctx.db, ctx.p, o)) or (body.to_type == "TASK" and not can_view_task(ctx.db, ctx.p, o)):
        raise Forbidden("You do not have access to that record.")
    art.add_link(ctx.db, from_type=A, from_id=d.id, to_type=body.to_type, to_id=body.to_id, link_type=body.link_type, section=None, actor=ctx.user.id)
    ctx.audit("deployment.link", "deployment", d.id, f"{d.key} linked to {body.to_type.lower()}")
    ctx.db.commit()
    return _detail(ctx, d)


class SubmitIn(BaseModel):
    approvers: list[uuid.UUID] = Field(default_factory=list)


@router.post("/deployments/{did}/submit")
def submit_deployment(did: uuid.UUID, body: SubmitIn, ctx: Ctx = Depends(get_ctx)):
    """Planned → Awaiting approval (or straight to Approved where the environment needs no approval)."""
    d = _deployment(ctx, did)
    if d.status != "PLANNED":
        raise AppError("Only a planned deployment can be submitted.", code="INVALID_STATE")
    if d.requested_by_id != ctx.user.id and not ctx.p.has("deploy.request", project_id=d.project_id):
        raise Forbidden("Only the requester can submit this deployment.")
    env = ctx.db.get(DeploymentEnvironment, d.environment_id)
    c = svc.env_config(env)
    d.content_sha256 = svc.content_hash(d)
    if not c["requires_approval"]:
        svc.set_status(ctx.db, d, "APPROVED", ctx.user.id, "no approval required for this environment")
    else:
        if len(set(body.approvers)) < c["approvals_required"]:
            raise AppError(f"{env.code} needs {c['approvals_required']} approver(s).", code="APPROVER_REQUIRED")
        svc.check_approvers(ctx.db, d.project_id, body.approvers)
        art.submit(ctx.db, a_type=A, a_id=d.id, revision=1, sha=d.content_sha256, submitter_id=ctx.user.id, reviewers=[], approvers=body.approvers, excluded={d.requested_by_id},
                   title=f"{d.key} {d.version_label} to {env.code}", link=f"/deployments/{d.project_id}?open={d.id}")
        svc.set_status(ctx.db, d, "AWAITING_APPROVAL", ctx.user.id)
    ctx.audit("deployment.submit", "deployment", d.id, f"{d.key} submitted ({d.status.lower().replace('_', ' ')})", {"sha256": d.content_sha256, "approvers": [str(x) for x in body.approvers]})
    ctx.db.commit()
    return _detail(ctx, d)


class DecisionIn(BaseModel):
    decision: str = Field(pattern=r"^(approve|request_changes)$")
    comment: str | None = Field(default=None, max_length=4000)


@router.post("/deployments/{did}/approvals/{rid}/decide")
def decide_deployment(did: uuid.UUID, rid: uuid.UUID, body: DecisionIn, ctx: Ctx = Depends(get_ctx)):
    d = _deployment(ctx, did)
    r = get_or_404(ctx.db, ArtifactReview, rid, "Approval")
    if r.artifact_type != A or r.artifact_id != d.id:
        raise AppError("That approval belongs to another deployment.")
    if d.status != "AWAITING_APPROVAL":
        raise AppError("This deployment is not awaiting approval.", code="INVALID_STATE")
    _need(ctx, "deploy.approve", d.project_id, "Approving a deployment")
    env = ctx.db.get(DeploymentEnvironment, d.environment_id)
    outcome = art.decide(ctx.db, review=r, user_id=ctx.user.id, decision=body.decision, comment=body.comment, revision=1, sha=svc.content_hash(d),
                         title=f"{d.key} {d.version_label} to {env.code}", link=f"/deployments/{d.project_id}?open={d.id}", owner_id=d.requested_by_id)
    art.add_event(ctx.db, A, d.id, "DECISION", ctx.user.id, r.role, r.status, r.comment)
    if outcome == "APPROVED":
        svc.set_status(ctx.db, d, "APPROVED", ctx.user.id)
    elif outcome == "CHANGES_REQUESTED":
        svc.set_status(ctx.db, d, "REJECTED", ctx.user.id, r.comment)
    ctx.audit("deployment.decide", "deployment", d.id, f"{d.key}: approval {body.decision.replace('_', ' ')}", {"outcome": outcome, "sha256": r.content_sha256, "reason": body.comment})
    ctx.db.commit()
    return _detail(ctx, d)


@router.get("/deployments/{did}/gates")
def deployment_gates(did: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    d = _deployment(ctx, did)
    return {"gates": svc.evaluate_gates(ctx.db, d)}


@router.post("/deployments/{did}/execute")
def execute_deployment(did: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    """Validation gates, then a queued attempt for the worker. Also used for an authorised retry after a failure."""
    d = _deployment(ctx, did)
    _need(ctx, "deploy.execute", d.project_id, "Executing a deployment")
    retry = d.status == "FAILED"
    a = svc.queue(ctx.db, d, ctx.user.id)
    ctx.audit("deployment.retry" if retry else "deployment.execute", "deployment", d.id, f"{d.key} attempt {a.attempt_no} queued ({a.adapter})", {"attempt": str(a.id)})
    ctx.db.commit()
    return {"job_id": str(a.id), "attempt_no": a.attempt_no, "status": a.status, "deployment": _detail(ctx, d)}


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


@router.post("/deployments/{did}/cancel")
def cancel_deployment(did: uuid.UUID, body: ReasonIn, ctx: Ctx = Depends(get_ctx)):
    d = _deployment(ctx, did)
    if d.requested_by_id != ctx.user.id and not ctx.p.has("deploy.execute", project_id=d.project_id):
        raise Forbidden("Only the requester or someone who may execute deployments can cancel it.")
    if d.status not in svc.CANCELLABLE:
        raise AppError(f"A {d.status.lower().replace('_', ' ')} deployment cannot be cancelled.", code="INVALID_STATE")
    art.withdraw(ctx.db, A, d.id)
    svc.set_status(ctx.db, d, "CANCELLED", ctx.user.id, body.reason)
    ctx.audit("deployment.cancel", "deployment", d.id, f"{d.key} cancelled", {"reason": body.reason})
    ctx.db.commit()
    return _detail(ctx, d)


def _previous(db, d: Deployment) -> Deployment | None:
    """The deployment that was current on the environment before d: a prior approved and deployed version."""
    if not d.deployed_at:
        return None
    return db.execute(select(Deployment).where(Deployment.environment_id == d.environment_id, Deployment.id != d.id, Deployment.deployed_at.is_not(None), Deployment.deployed_at < d.deployed_at,
                                              Deployment.rollback_of_id.is_(None)).order_by(Deployment.deployed_at.desc())).scalars().first()


@router.post("/deployments/{did}/rollback")
def rollback_deployment(did: uuid.UUID, body: ReasonIn, ctx: Ctx = Depends(get_ctx)):
    """A NEW deployment that puts the previous version back. The original record is not rewritten; it becomes
    ROLLED_BACK only when the rollback has actually been deployed."""
    d = _deployment(ctx, did)
    _need(ctx, "deploy.execute", d.project_id, "Rolling back a deployment")
    if d.status != "DEPLOYED":
        raise AppError("Only a deployed version can be rolled back.", code="INVALID_STATE")
    if svc.current_on(ctx.db, d.environment_id).id != d.id:
        raise AppError("Only the version that is currently on the environment can be rolled back.")
    prev = _previous(ctx.db, d)
    if not prev:
        raise AppError("There is no earlier deployed version on this environment to roll back to.", code="NO_PREVIOUS")
    p = ctx.db.get(Project, d.project_id)
    env = ctx.db.get(DeploymentEnvironment, d.environment_id)
    r = Deployment(project_id=d.project_id, environment_id=d.environment_id, key=svc.next_key(ctx.db, p), title=f"Rollback of {d.key}: {d.version_label} → {prev.version_label}", version_label=prev.version_label,
                   repository_id=prev.repository_id, git_ref=prev.git_ref, commit_sha=prev.commit_sha, release_notes=f"Rollback of {d.key} ({d.version_label}) to {prev.key} ({prev.version_label}).\nReason: {body.reason}",
                   test_run_id=prev.test_run_id, checklist=prev.checklist, rollback_of_id=d.id, requested_by_id=ctx.user.id, content_sha256="")
    r.content_sha256 = svc.content_hash(r)
    ctx.db.add(r)
    ctx.db.flush()
    art.add_event(ctx.db, A, r.id, "CREATED", ctx.user.id, to="PLANNED", comment=body.reason)
    art.add_event(ctx.db, A, d.id, "ROLLBACK", ctx.user.id, None, r.key, body.reason)
    ctx.audit("deployment.rollback", "deployment", r.id, f"{r.key}: rollback of {d.key} on {env.code} to {prev.version_label} requested", {"reason": body.reason, "of": str(d.id), "to": str(prev.id)})
    ctx.db.commit()
    return _detail(ctx, r)


class ReportIn(BaseModel):
    outcome: str = Field(pattern=r"^(SUCCEEDED|FAILED)$")
    log: str | None = Field(default=None, max_length=100000)
    reason: str | None = Field(default=None, max_length=1000)


@router.post("/deployment-attempts/{aid}/report")
def report_attempt(aid: uuid.UUID, body: ReportIn, ctx: Ctx = Depends(get_ctx)):
    """Manual adapter: the operator records what happened. The health check still decides success."""
    a = get_or_404(ctx.db, DeploymentAttempt, aid, "Attempt")
    d = _deployment(ctx, a.deployment_id)
    _need(ctx, "deploy.execute", d.project_id, "Recording a deployment result")
    if a.status != "WAITING" or a.adapter != "manual":
        raise AppError("This attempt is not waiting for a manual result.", code="INVALID_STATE")
    if body.outcome == "FAILED" and not (body.reason or "").strip():
        raise AppError("Say why the deployment failed.", code="REASON_REQUIRED")
    env = ctx.db.get(DeploymentEnvironment, d.environment_id)
    secrets = svc.secret_values(svc.env_config(env))
    svc._log(a, f"Result recorded by {ctx.user.full_name}: {body.outcome}\n{body.log or ''}", secrets)
    svc.finish(ctx.db, a, body.outcome == "SUCCEEDED", body.reason, ctx.user.id)
    ctx.audit("deployment.report", "deployment", d.id, f"{d.key} attempt {a.attempt_no}: {body.outcome.lower()} recorded", {"reason": body.reason})
    ctx.db.commit()
    return _detail(ctx, d)


class CallbackIn(BaseModel):
    attempt_id: uuid.UUID
    status: str = Field(pattern=r"^(success|failed)$")
    log: str | None = Field(default=None, max_length=200000)
    reason: str | None = Field(default=None, max_length=1000)
    external_url: str | None = Field(default=None, max_length=500)


@router.post("/deployments/callback")
async def ci_callback(request: Request, x_elm_signature: str | None = Header(None), db=Depends(get_db)):
    """Signed CI/CD callback: X-ELM-Signature: sha256=<HMAC-SHA256(ELM_DEPLOY_CALLBACK_SECRET, body)>."""
    raw = await request.body()
    if not svc.verify_callback(raw, x_elm_signature):
        raise Unauthorized("Invalid or missing callback signature.")
    body = CallbackIn.model_validate_json(raw)
    a = db.get(DeploymentAttempt, body.attempt_id)
    if not a or a.status not in ("WAITING", "RUNNING"):
        raise AppError("Unknown or finished attempt.", code="JOB_STATE", status_code=409)
    d = db.get(Deployment, a.deployment_id)
    env = db.get(DeploymentEnvironment, d.environment_id)
    secrets = svc.secret_values(svc.env_config(env))
    if body.external_url:
        a.external_url = body.external_url
    svc._log(a, f"CI callback: {body.status}\n{body.log or ''}", secrets)
    svc.finish(db, a, body.status == "success", body.reason or (None if body.status == "success" else "CI reported a failure"), None)
    db.commit()
    return {"ok": True, "status": a.status}


@router.get("/projects/{pid}/deployment-overview")
def overview(pid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    """What runs where: the current version per environment and what is in flight."""
    _project(ctx, pid)
    envs = ctx.db.execute(select(DeploymentEnvironment).where(DeploymentEnvironment.project_id == pid).order_by(DeploymentEnvironment.sort_order)).scalars().all()
    out = []
    for e in envs:
        cur = svc.current_on(ctx.db, e.id)
        flight = ctx.db.execute(select(Deployment).where(Deployment.environment_id == e.id, Deployment.status.in_(["AWAITING_APPROVAL", "APPROVED", "DEPLOYING", "FAILED"])).order_by(Deployment.created_at.desc())).scalars().all()
        out.append({"environment": {"id": str(e.id), "code": e.code, "name": e.name, "active": e.active}, "current": _brief(cur, {e.id: e}, {}) if cur else None,
                    "in_flight": [_brief(x, {e.id: e}, {}) for x in flight]})
    return out

