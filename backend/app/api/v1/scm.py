"""GitLab integration API (architecture §12.2–12.3). Registered repositories per project, task branches, merge requests,
traceability links, sync and the webhook. The GitLab token never leaves the server."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import Ctx, get_ctx, get_or_404
from app.core.errors import AppError, Forbidden, Unauthorized
from app.models import EngineeringItem, Project, WorkItem, WorkItemEvent
from app.models.scm import ScmLink, ScmOperation, ScmRepository, ScmWebhookEvent
from app.services import scm as svc
from app.services.gitlab_client import GitLab
from app.services.planning import can_manage_task, can_view_task, require_view_project
from app.services.serial import iso

router = APIRouter(tags=["source-control"])


def _project(ctx: Ctx, pid: uuid.UUID) -> Project:
    p = get_or_404(ctx.db, Project, pid, "Project")
    require_view_project(ctx.db, ctx.p, pid)
    return p


def _repo(ctx: Ctx, rid: uuid.UUID) -> ScmRepository:
    r = get_or_404(ctx.db, ScmRepository, rid, "Repository")
    require_view_project(ctx.db, ctx.p, r.project_id)
    return r


def _task(ctx: Ctx, wid: uuid.UUID, *, edit: bool = False) -> WorkItem:
    w = get_or_404(ctx.db, WorkItem, wid, "Task")
    if not can_view_task(ctx.db, ctx.p, w):
        raise Forbidden("You do not have access to this task.")
    if edit and ctx.user.id not in (w.assignee_id, w.reporter_id) and not can_manage_task(ctx.db, ctx.p, w):
        raise Forbidden("Only the assignee, reporter or a task manager in this scope can do this.")
    if not w.project_id:
        raise AppError("Source control is available for project tasks only.")
    return w


def _require_manage(ctx: Ctx, project_id: uuid.UUID) -> None:
    if not ctx.p.has("scm.manage", project_id=project_id):
        raise Forbidden("Registering repositories needs the source-control management permission for this project.", details={"permission": "scm.manage"})


# ------------------------------------------------------------------ status
@router.get("/scm/status")
def scm_status(check: bool = False, ctx: Ctx = Depends(get_ctx)):
    s = get_settings()
    out = {"enabled": s.gitlab_enabled, "configured": bool(s.gitlab_token), "url": svc.public_url(), "webhook_url": "/api/v1/scm/gitlab/webhook", "webhook_secret_set": bool(s.gitlab_webhook_secret)}
    if check and s.gitlab_enabled:
        try:
            out["version"] = GitLab.from_settings().version().get("version")
            out["reachable"] = True
        except AppError as e:
            out["reachable"], out["error"] = False, e.message
    return out


# ------------------------------------------------------------------ repositories
class RepoIn(BaseModel):
    path: str = Field(min_length=1, max_length=300, description="GitLab path_with_namespace (group/project) or numeric id")
    item_id: uuid.UUID | None = None
    branch_prefix: str = Field(default="task/", pattern=r"^[A-Za-z0-9._/-]{0,60}$")


class RepoPatch(BaseModel):
    active: bool | None = None
    branch_prefix: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._/-]{0,60}$")
    default_branch: str | None = Field(default=None, min_length=1, max_length=200)
    item_id: uuid.UUID | None = None


@router.get("/projects/{pid}/repositories")
def list_repositories(pid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    _project(ctx, pid)
    return {"can_manage": ctx.p.has("scm.manage", project_id=pid), "items": [svc.repo_dict(r) for r in svc.project_repositories(ctx.db, pid)]}


@router.post("/projects/{pid}/repositories")
def register_repository(pid: uuid.UUID, body: RepoIn, ctx: Ctx = Depends(get_ctx)):
    p = _project(ctx, pid)
    _require_manage(ctx, pid)
    if body.item_id:
        it = get_or_404(ctx.db, EngineeringItem, body.item_id, "Item")
        if it.project_id != pid:
            raise AppError("The engineering item belongs to a different project.")
    r = svc.register_repository(ctx.db, ctx.user.id, p, body.path, item_id=body.item_id, branch_prefix=body.branch_prefix)
    ctx.audit("scm.repository.register", "scm_repository", r.id, f"GitLab {r.path} registered for {p.code}", {"external_id": r.external_id})
    ctx.db.commit()
    return svc.repo_dict(r)


@router.patch("/repositories/{rid}")
def update_repository(rid: uuid.UUID, body: RepoPatch, version: int | None = None, ctx: Ctx = Depends(get_ctx)):
    r = _repo(ctx, rid)
    _require_manage(ctx, r.project_id)
    if version is not None and version != r.version:
        raise AppError("Repository settings were changed by someone else. Refresh and try again.", code="CONFLICT", status_code=409)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(r, k, v)
    r.version += 1
    ctx.audit("scm.repository.update", "scm_repository", r.id, f"GitLab {r.path} settings changed", {k: str(v) for k, v in changes.items()})
    ctx.db.commit()
    return svc.repo_dict(r)


@router.get("/repositories/{rid}/branches")
def repository_branches(rid: uuid.UUID, search: str | None = Query(None, max_length=100), ctx: Ctx = Depends(get_ctx)):
    r = _repo(ctx, rid)
    rows = GitLab.from_settings().branches(r.external_id, search=search)
    return [{"name": b.get("name"), "default": b.get("default"), "protected": b.get("protected"), "merged": b.get("merged"), "commit": (b.get("commit") or {}).get("short_id"), "web_url": svc._web_url(b.get("web_url"))} for b in rows]


@router.get("/repositories/{rid}/compare")
def repository_compare(rid: uuid.UUID, head: str = Query(..., max_length=200), base: str | None = Query(None, max_length=200), ctx: Ctx = Depends(get_ctx)):
    """Change summary of a branch against its target, for reviewers (read-only)."""
    r = _repo(ctx, rid)
    d = GitLab.from_settings().compare(r.external_id, base or r.default_branch, head)
    return {"commits": [{"id": c.get("id"), "short_id": c.get("short_id"), "title": c.get("title"), "author": c.get("author_name"), "at": c.get("created_at")} for c in d.get("commits") or []],
            "files": [{"old_path": f.get("old_path"), "new_path": f.get("new_path"), "new_file": f.get("new_file"), "deleted_file": f.get("deleted_file"), "renamed_file": f.get("renamed_file"),
                       "diff": (f.get("diff") or "")[:20000]} for f in (d.get("diffs") or [])[:200]],
            "compare_timeout": d.get("compare_timeout"), "web_url": svc._web_url(d.get("web_url"))}


# ------------------------------------------------------------------ task view and operations
@router.get("/work-items/{wid}/scm")
def task_scm(wid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    w = _task(ctx, wid)
    repos = {r.id: r for r in svc.project_repositories(ctx.db, w.project_id)}
    links = ctx.db.execute(select(ScmLink).where(ScmLink.work_item_id == w.id).order_by(ScmLink.kind, ScmLink.external_at.desc(), ScmLink.created_at.desc())).scalars().all()
    ops = ctx.db.execute(select(ScmOperation).where(ScmOperation.work_item_id == w.id).order_by(ScmOperation.at.desc()).limit(20)).scalars().all()
    s = get_settings()
    return {"enabled": s.gitlab_enabled and bool(s.gitlab_token), "can_operate": ctx.user.id in (w.assignee_id, w.reporter_id) or can_manage_task(ctx.db, ctx.p, w),
            "suggested_branch": f"{{prefix}}{w.key}-{svc.slug(w.title)}", "repositories": [svc.repo_dict(r) for r in repos.values()],
            "links": [svc.link_dict(x, repos.get(x.repository_id)) for x in links], "blockers": svc.completion_blockers(ctx.db, w) if w.kind == "DEVELOPMENT" else [],
            "operations": [{"id": str(o.id), "at": iso(o.at), "operation": o.operation, "status": o.status, "error": o.error} for o in ops]}


class BranchIn(BaseModel):
    repository_id: uuid.UUID
    name: str | None = Field(default=None, max_length=200)
    ref: str | None = Field(default=None, max_length=200)


class MergeRequestIn(BaseModel):
    repository_id: uuid.UUID
    source_branch: str | None = Field(default=None, max_length=200)
    target_branch: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=255)


class ManualLinkIn(BaseModel):
    repository_id: uuid.UUID
    kind: str = Field(pattern=r"^(BRANCH|COMMIT|MERGE_REQUEST)$")
    ref: str = Field(min_length=1, max_length=255)
    title: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, max_length=500, pattern=r"^https?://")
    state: str | None = Field(default=None, pattern=r"^(opened|merged|closed|active)$")


def _task_repo(ctx: Ctx, w: WorkItem, rid: uuid.UUID) -> ScmRepository:
    r = get_or_404(ctx.db, ScmRepository, rid, "Repository")
    if r.project_id != w.project_id:
        raise AppError("That repository is not registered for this task's project.", code="REPO_NOT_ALLOWED")
    return r


@router.post("/work-items/{wid}/scm/branch")
def create_task_branch(wid: uuid.UUID, body: BranchIn, ctx: Ctx = Depends(get_ctx)):
    w = _task(ctx, wid, edit=True)
    r = _task_repo(ctx, w, body.repository_id)
    link = svc.create_branch(ctx.db, ctx.user.id, r, w, body.name, body.ref)
    ctx.audit("scm.branch.create", "work_item", w.id, f"{w.key}: branch {link.ref} created in {r.path}", {"repository": r.path, "branch": link.ref})
    ctx.db.commit()
    return svc.link_dict(link, r)


@router.post("/work-items/{wid}/scm/merge-request")
def create_task_merge_request(wid: uuid.UUID, body: MergeRequestIn, request: Request, ctx: Ctx = Depends(get_ctx)):
    w = _task(ctx, wid, edit=True)
    r = _task_repo(ctx, w, body.repository_id)
    origin = request.headers.get("origin") or ""
    link = svc.create_merge_request(ctx.db, ctx.user.id, r, w, source=body.source_branch, target=body.target_branch, title=body.title, elm_url=f"{origin}/tasks?open={w.id}" if origin else None)
    ctx.audit("scm.merge_request.create", "work_item", w.id, f"{w.key}: merge request !{link.ref} opened in {r.path}", {"repository": r.path, "iid": link.ref, "source": link.source_branch, "target": link.target_branch})
    ctx.db.commit()
    return svc.link_dict(link, r)


@router.post("/work-items/{wid}/scm/sync")
def sync_task(wid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    w = _task(ctx, wid)
    counts = svc.sync_task(ctx.db, ctx.user.id, w)
    ctx.audit("scm.sync", "work_item", w.id, f"{w.key}: synchronised with GitLab", counts)
    ctx.db.commit()
    return counts


@router.post("/work-items/{wid}/scm/links")
def add_manual_link(wid: uuid.UUID, body: ManualLinkIn, ctx: Ctx = Depends(get_ctx)):
    """Manual reference mode (§12.2): record a branch, commit or merge request ELM did not create or cannot reach."""
    w = _task(ctx, wid, edit=True)
    r = _task_repo(ctx, w, body.repository_id)
    if body.kind == "MERGE_REQUEST" and not body.ref.isdigit():
        raise AppError("A merge request reference is its number (iid), for example 12.")
    if body.kind == "COMMIT" and not all(c in "0123456789abcdef" for c in body.ref.lower()):
        raise AppError("A commit reference is its SHA in hexadecimal.")
    link, created = svc.upsert_link(ctx.db, w, r, body.kind, body.ref, origin="MANUAL", actor_id=ctx.user.id, title=body.title, url=body.url, state=body.state)
    if not created:
        raise AppError("That reference is already linked to this task.", code="DUPLICATE")
    ctx.audit("scm.link.manual", "work_item", w.id, f"{w.key}: {body.kind.lower()} {body.ref} linked by hand", {"repository": r.path})
    ctx.db.commit()
    return svc.link_dict(link, r)


@router.delete("/work-items/{wid}/scm/links/{lid}")
def remove_manual_link(wid: uuid.UUID, lid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    w = _task(ctx, wid, edit=True)
    link = get_or_404(ctx.db, ScmLink, lid, "Link")
    if link.work_item_id != w.id:
        raise AppError("That link belongs to another task.")
    if link.origin != "MANUAL":
        raise AppError("Only links added by hand can be removed; GitLab-confirmed links are kept for traceability.", code="IMMUTABLE")
    ctx.db.add(WorkItemEvent(work_item_id=w.id, actor_id=ctx.user.id, kind="SCM", from_value=f"{link.kind} {link.ref}"[:120], comment="Manual link removed"))
    ctx.db.delete(link)
    ctx.audit("scm.link.remove", "work_item", w.id, f"{w.key}: manual {link.kind.lower()} {link.ref} removed")
    ctx.db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ webhook (no session; authenticated by the secret token)
@router.post("/scm/gitlab/webhook")
async def gitlab_webhook(request: Request, x_gitlab_token: str | None = Header(None), x_gitlab_event: str = Header(""), x_gitlab_event_uuid: str | None = Header(None), db=Depends(get_db)):
    if not svc.verify_webhook_token(x_gitlab_token):
        raise Unauthorized("Invalid or missing GitLab webhook token.")
    body = await request.body()
    if len(body) > 5_000_000:
        raise AppError("Webhook payload too large.", status_code=413)
    result = svc.handle_webhook(db, x_gitlab_event, (x_gitlab_event_uuid or "")[:80] or None, body)
    db.commit()
    return result


@router.get("/projects/{pid}/scm/webhook-events")
def webhook_events(pid: uuid.UUID, limit: int = Query(50, le=200), ctx: Ctx = Depends(get_ctx)):
    _project(ctx, pid)
    _require_manage(ctx, pid)
    ids = [r.id for r in svc.project_repositories(ctx.db, pid)]
    rows = ctx.db.execute(select(ScmWebhookEvent).where(ScmWebhookEvent.repository_id.in_(ids)).order_by(ScmWebhookEvent.received_at.desc()).limit(limit)).scalars().all() if ids else []
    return [{"id": str(e.id), "received_at": iso(e.received_at), "event": e.event, "status": e.status, "links_created": e.links_created, "note": e.note} for e in rows]
