"""Source-control integration (architecture §12.2–12.3) with the self-hosted GitLab.

* Repositories are allow-listed per ELM project; ELM never calls a GitLab project that is not registered.
* Developers clone, edit and commit in their normal Git tools. ELM creates task branches and merge requests, keeps
  traceability (task ↔ branch / commit / merge request) and follows GitLab through webhooks and on-demand sync.
* No Git command line runs on the server and nothing from the browser is passed to a shell.
* Each operation ELM performs is recorded (ScmOperation) and audited. A failed call leaves nothing half-done in ELM:
  the link is only written after GitLab confirms the change.
* Code-review approval stays an ELM decision (separation of duties); a merge seen in GitLab moves an approved task to
  Merged through the lifecycle's "system" actor only when the lifecycle allows it.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.errors import AppError
from app.models import Project, WorkItem, WorkItemEvent
from app.models.scm import ScmLink, ScmOperation, ScmRepository, ScmWebhookEvent
from app.services import audit as auditsvc
from app.services.gitlab_client import GitLab, GitLabError
from app.services.notify import notify

KEY_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9_]{1,39}-\d{1,9})(?![0-9])")
BRANCH_OK = re.compile(r"^(?!/)(?!.*\.\.)(?!.*//)(?!.*@\{)[A-Za-z0-9._/-]{1,200}(?<![./])$")
MR_STATES = {"opened", "merged", "closed", "locked"}


def public_url() -> str:
    s = get_settings()
    return (s.gitlab_public_url or s.gitlab_url).rstrip("/")


def _web_url(url: str | None) -> str | None:
    """GitLab reports URLs with its own external_url; show users the public one when they differ."""
    if not url:
        return url
    s = get_settings()
    if s.gitlab_public_url and url.startswith(s.gitlab_url.rstrip("/")):
        return public_url() + url[len(s.gitlab_url.rstrip("/")):]
    return url


def _when(v) -> datetime | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00").replace(" UTC", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def slug(text: str, n: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:n].rstrip("-") or "work"


def task_keys(*texts: str | None) -> set[str]:
    out: set[str] = set()
    for t in texts:
        if t:
            out |= set(KEY_RE.findall(t))
    return out


# ------------------------------------------------------------------ operation log
class Operation:
    """Context manager that records one GitLab call. On failure the row is kept as FAILED and the error re-raised."""

    def __init__(self, db: Session, op: str, *, actor_id=None, repo: ScmRepository | None = None, task: WorkItem | None = None, request: dict | None = None):
        self.db = db
        self.row = ScmOperation(operation=op, actor_id=actor_id, repository_id=repo.id if repo else None, work_item_id=task.id if task else None, request=json.dumps(request or {}, default=str))
        db.add(self.row)
        db.flush()

    def __enter__(self):
        return self

    def done(self, result: dict) -> None:
        self.row.result = json.dumps(result, default=str)[:20000]

    def __exit__(self, exc_type, exc, tb):
        self.row.finished_at = utcnow()
        if exc is None:
            self.row.status = "SUCCEEDED"
            return False
        # The request fails as a whole, so the caller's unsaved work is discarded; only the failure record is kept.
        failed = ScmOperation(operation=self.row.operation, actor_id=self.row.actor_id, repository_id=self.row.repository_id, work_item_id=self.row.work_item_id,
                              request=self.row.request, status="FAILED", error=(getattr(exc, "message", None) or str(exc))[:1000], at=self.row.at or utcnow(), finished_at=utcnow())
        self.db.rollback()
        self.db.add(failed)
        self.db.commit()
        return False


# ------------------------------------------------------------------ repositories
def register_repository(db: Session, actor_id: uuid.UUID, project: Project, path: str, *, item_id=None, branch_prefix: str = "task/") -> ScmRepository:
    gl = GitLab.from_settings()
    with Operation(db, "lookup", actor_id=actor_id, request={"path": path}) as op:
        info = gl.project(path.strip().strip("/"))
        op.done({"id": info.get("id"), "path": info.get("path_with_namespace")})
    ext = str(info["id"])
    if db.execute(select(ScmRepository.id).where(ScmRepository.project_id == project.id, ScmRepository.provider == "gitlab", ScmRepository.external_id == ext)).first():
        raise AppError(f"{info.get('path_with_namespace')} is already registered for {project.code}.", code="DUPLICATE")
    repo = ScmRepository(project_id=project.id, provider="gitlab", external_id=ext, path=info.get("path_with_namespace") or path, name=info.get("name") or path,
                         web_url=_web_url(info.get("web_url")), default_branch=info.get("default_branch") or "main", branch_prefix=branch_prefix, item_id=item_id, created_by_id=actor_id)
    db.add(repo)
    db.flush()
    op.row.repository_id = repo.id
    return repo


def project_repositories(db: Session, project_id) -> list[ScmRepository]:
    return list(db.execute(select(ScmRepository).where(ScmRepository.project_id == project_id).order_by(ScmRepository.path)).scalars())


def repo_dict(r: ScmRepository) -> dict:
    return {"id": str(r.id), "project_id": str(r.project_id), "provider": r.provider, "external_id": r.external_id, "path": r.path, "name": r.name, "web_url": r.web_url,
            "default_branch": r.default_branch, "branch_prefix": r.branch_prefix, "item_id": str(r.item_id) if r.item_id else None, "active": r.active, "version": r.version,
            "last_event_at": r.last_event_at.isoformat() if r.last_event_at else None}


def link_dict(link: ScmLink, repo: ScmRepository | None) -> dict:
    return {"id": str(link.id), "kind": link.kind, "ref": link.ref, "title": link.title, "url": link.url, "state": link.state, "source_branch": link.source_branch, "target_branch": link.target_branch,
            "author": link.author, "origin": link.origin, "external_at": link.external_at.isoformat() if link.external_at else None, "created_at": link.created_at.isoformat() if link.created_at else None,
            "repository": {"id": str(repo.id), "path": repo.path, "web_url": repo.web_url} if repo else None}


# ------------------------------------------------------------------ links
def upsert_link(db: Session, task: WorkItem, repo: ScmRepository, kind: str, ref: str, *, origin: str, actor_id=None, **fields) -> tuple[ScmLink, bool]:
    ref = str(ref)[:255]
    link = db.execute(select(ScmLink).where(ScmLink.work_item_id == task.id, ScmLink.repository_id == repo.id, ScmLink.kind == kind, ScmLink.ref == ref)).scalar_one_or_none()
    created = link is None
    if created:
        link = ScmLink(work_item_id=task.id, repository_id=repo.id, kind=kind, ref=ref, origin=origin, created_by_id=actor_id)
        db.add(link)
    for k, v in fields.items():
        if v is not None:
            setattr(link, k, v[:500] if isinstance(v, str) and k in ("title", "url") else v)
    db.flush()
    if created:
        label = {"BRANCH": "Branch", "COMMIT": "Commit", "MERGE_REQUEST": "Merge request"}[kind]
        shown = f"!{ref}" if kind == "MERGE_REQUEST" else (ref[:10] if kind == "COMMIT" else ref)
        db.add(WorkItemEvent(work_item_id=task.id, actor_id=actor_id, kind="SCM", to_value=f"{label} {shown}"[:120], comment=(fields.get("title") or "")[:500] or None))
    return link, created


def _mr_fields(mr: dict) -> dict:
    author = mr.get("author") or {}
    return {"title": mr.get("title"), "url": _web_url(mr.get("web_url") or mr.get("url")), "state": mr.get("state") if mr.get("state") in MR_STATES else None,
            "source_branch": mr.get("source_branch"), "target_branch": mr.get("target_branch"), "author": author.get("username") or author.get("name") or mr.get("author_username"),
            "external_at": _when(mr.get("merged_at") or mr.get("updated_at") or mr.get("created_at"))}


def _commit_fields(c: dict, repo: ScmRepository) -> dict:
    url = c.get("web_url") or c.get("url") or (f"{repo.web_url}/-/commit/{c.get('id')}" if repo.web_url else None)
    author = c.get("author_name") or (c.get("author") or {}).get("name")
    return {"title": (c.get("title") or (c.get("message") or "").split("\n", 1)[0])[:500], "url": _web_url(url), "author": author, "external_at": _when(c.get("committed_date") or c.get("timestamp"))}


def _branch_url(repo: ScmRepository, name: str) -> str | None:
    return f"{repo.web_url}/-/tree/{name}" if repo.web_url else None


# ------------------------------------------------------------------ task operations
def create_branch(db: Session, actor_id: uuid.UUID, repo: ScmRepository, task: WorkItem, name: str | None = None, ref: str | None = None) -> ScmLink:
    _require_usable(repo, task)
    name = (name or f"{repo.branch_prefix}{task.key}-{slug(task.title)}").strip()
    if not BRANCH_OK.match(name):
        raise AppError("That is not a valid branch name (letters, digits, . _ - / only; no '..', '//' or trailing '/').", code="INVALID_BRANCH")
    if task.key not in name:
        raise AppError(f"The branch name must contain the task key {task.key}, so commits and merge requests stay traceable.", code="INVALID_BRANCH")
    gl = GitLab.from_settings()
    with Operation(db, "create_branch", actor_id=actor_id, repo=repo, task=task, request={"branch": name, "ref": ref or repo.default_branch}) as op:
        b = gl.create_branch(repo.external_id, name, ref or repo.default_branch)
        op.done({"branch": b.get("name"), "commit": (b.get("commit") or {}).get("id")})
    link, _ = upsert_link(db, task, repo, "BRANCH", b.get("name") or name, origin="ELM", actor_id=actor_id, title=f"from {ref or repo.default_branch}", url=_web_url(b.get("web_url")) or _branch_url(repo, name), state="active")
    return link


def create_merge_request(db: Session, actor_id: uuid.UUID, repo: ScmRepository, task: WorkItem, *, source: str | None, target: str | None, title: str | None, elm_url: str | None) -> ScmLink:
    _require_usable(repo, task)
    if not source:
        branch = db.execute(select(ScmLink).where(ScmLink.work_item_id == task.id, ScmLink.repository_id == repo.id, ScmLink.kind == "BRANCH").order_by(ScmLink.created_at.desc())).scalars().first()
        if not branch:
            raise AppError("Create or link a branch for this task first, or name the source branch.", code="NO_BRANCH")
        source = branch.ref
    target = target or repo.default_branch
    if source == target:
        raise AppError("The source and target branches must differ.")
    title = (title or f"{task.key}: {task.title}")[:255]
    if task.key not in title:
        title = f"{task.key}: {title}"[:255]
    desc = f"ELM task {task.key}: {task.title}" + (f"\n\n{elm_url}" if elm_url else "") + "\n\nCreated from ADA-ELM. Code-review approval is recorded in ELM."
    gl = GitLab.from_settings()
    with Operation(db, "create_merge_request", actor_id=actor_id, repo=repo, task=task, request={"source": source, "target": target, "title": title}) as op:
        mr = gl.create_merge_request(repo.external_id, source, target, title, desc)
        op.done({"iid": mr.get("iid"), "state": mr.get("state")})
    link, _ = upsert_link(db, task, repo, "MERGE_REQUEST", str(mr["iid"]), origin="ELM", actor_id=actor_id, **_mr_fields(mr))
    _automate(db, task, link)
    return link


def sync_task(db: Session, actor_id: uuid.UUID | None, task: WorkItem) -> dict:
    """Pull branches, merge requests and commits that mention the task key from every active repository of its project."""
    gl = GitLab.from_settings()
    counts = {"branches": 0, "merge_requests": 0, "commits": 0, "repositories": 0}
    for repo in project_repositories(db, task.project_id):
        if not repo.active:
            continue
        counts["repositories"] += 1
        with Operation(db, "sync", actor_id=actor_id, repo=repo, task=task, request={"key": task.key}) as op:
            branches = [b for b in gl.branches(repo.external_id, search=task.key) if task.key in b.get("name", "")]
            known = {x.ref for x in db.execute(select(ScmLink).where(ScmLink.work_item_id == task.id, ScmLink.repository_id == repo.id, ScmLink.kind == "BRANCH")).scalars()}
            names = {b["name"] for b in branches} | known
            for b in branches:
                _, new = upsert_link(db, task, repo, "BRANCH", b["name"], origin="SYNC", actor_id=actor_id, url=_web_url(b.get("web_url")) or _branch_url(repo, b["name"]), state="active")
                counts["branches"] += new
            for gone in known - {b["name"] for b in branches}:
                link = db.execute(select(ScmLink).where(ScmLink.work_item_id == task.id, ScmLink.repository_id == repo.id, ScmLink.kind == "BRANCH", ScmLink.ref == gone)).scalar_one()
                try:
                    gl.branch(repo.external_id, gone)
                except GitLabError as e:
                    if e.gitlab_status == 404:
                        link.state = "deleted"
            for name in sorted(names):
                for mr in gl.merge_requests(repo.external_id, source_branch=name):
                    _, new = upsert_link(db, task, repo, "MERGE_REQUEST", str(mr["iid"]), origin="SYNC", actor_id=actor_id, **_mr_fields(mr))
                    counts["merge_requests"] += new
                for c in gl.commits(repo.external_id, name, limit=50):
                    if task.key in (c.get("message") or c.get("title") or "") or name in known or task.key in name:
                        _, new = upsert_link(db, task, repo, "COMMIT", c["id"], origin="SYNC", actor_id=actor_id, **_commit_fields(c, repo))
                        counts["commits"] += new
            op.done(counts)
    for link in db.execute(select(ScmLink).where(ScmLink.work_item_id == task.id, ScmLink.kind == "MERGE_REQUEST")).scalars():
        _automate(db, task, link)
    return counts


def _require_usable(repo: ScmRepository, task: WorkItem) -> None:
    if not repo.active:
        raise AppError(f"Repository {repo.path} is switched off in ELM.", code="REPO_INACTIVE")
    if repo.project_id != task.project_id:
        raise AppError("That repository is not registered for this task's project.", code="REPO_NOT_ALLOWED")


# ------------------------------------------------------------------ automation and gates
def _automate(db: Session, task: WorkItem, link: ScmLink) -> None:
    """Lifecycle moves that GitLab facts justify. Only transitions whose actors include "system" are used."""
    from app.services import task_lifecycle as lc

    life = lc.lifecycle_for(db, task)
    allowed = {(t["from"], t["to"]) for t in life["transitions"] if "system" in t.get("actors", [])}
    target = None
    if link.kind == "MERGE_REQUEST" and link.state == "opened" and (task.status, "CODE_REVIEW") in allowed:
        target = "CODE_REVIEW"
    elif link.kind == "MERGE_REQUEST" and link.state == "merged" and (task.status, "MERGED") in allowed:
        target = "MERGED"
    if not target:
        return
    try:
        old = lc.transition(db, task, target, user_id=None, is_manager=False, comment=f"GitLab merge request !{link.ref} is {link.state}.", system=True)
    except AppError:
        return  # a gate blocks it; people will see the reason when they act on the task
    auditsvc.record(db, actor_id=None, action="task.transition", entity_type="work_item", entity_id=task.id, summary=f"{task.key} {old} → {task.status} (GitLab !{link.ref} {link.state})", data={"from": old, "to": task.status, "source": "gitlab"})
    for uid in {task.assignee_id, task.reporter_id} - {None}:
        notify(db, uid, "task.status", f"{task.key}: {old} → {task.status}", f"GitLab merge request !{link.ref} is {link.state}.", link=f"/tasks?open={task.id}")


def completion_blockers(db: Session, w: WorkItem) -> list[str]:
    """A development task in a project with registered repositories completes only after its code is merged.
    Projects without repositories (manual reference mode, other tools) are not blocked."""
    if not w.project_id or not db.execute(select(ScmRepository.id).where(ScmRepository.project_id == w.project_id, ScmRepository.active.is_(True))).first():
        return []
    mrs = list(db.execute(select(ScmLink).where(ScmLink.work_item_id == w.id, ScmLink.kind == "MERGE_REQUEST")).scalars())
    if not mrs:
        return ["No merge request is linked to this development task."]
    out = []
    if not any(m.state == "merged" for m in mrs):
        out.append("No linked merge request has been merged yet.")
    out += [f"Merge request !{m.ref} is still open." for m in mrs if m.state in ("opened", "locked")]
    return out


# ------------------------------------------------------------------ webhook
def verify_webhook_token(token: str | None) -> bool:
    secret = get_settings().gitlab_webhook_secret
    return bool(secret) and hmac.compare_digest((token or "").encode(), secret.encode())


def handle_webhook(db: Session, event: str, delivery_id: str | None, body: bytes) -> dict:
    digest = hashlib.sha256(body).hexdigest()
    if delivery_id and db.execute(select(ScmWebhookEvent.id).where(ScmWebhookEvent.delivery_id == delivery_id)).first():
        return {"status": "DUPLICATE"}
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        raise AppError("The webhook body is not JSON.") from None
    ext = str((payload.get("project") or {}).get("id") or payload.get("project_id") or "")
    rec = ScmWebhookEvent(delivery_id=delivery_id, event=event[:60], external_project_id=ext or None, payload_sha256=digest)
    db.add(rec)
    repos = list(db.execute(select(ScmRepository).where(ScmRepository.provider == "gitlab", ScmRepository.external_id == ext, ScmRepository.active.is_(True))).scalars()) if ext else []
    if not repos:
        rec.status, rec.note = "IGNORED", "The GitLab project is not registered in ELM."
        return {"status": rec.status}
    rec.repository_id = repos[0].id
    created = 0
    for repo in repos:
        repo.last_event_at = utcnow()
        if event == "Push Hook":
            created += _on_push(db, repo, payload)
        elif event == "Merge Request Hook":
            created += _on_merge_request(db, repo, payload)
        else:
            rec.status, rec.note = "IGNORED", f"{event} is not used by ELM."
            return {"status": rec.status}
    rec.status, rec.links_created = "PROCESSED", created
    auditsvc.record(db, actor_id=None, action="scm.webhook", entity_type="scm_repository", entity_id=repos[0].id, summary=f"GitLab {event} for {repos[0].path}: {created} new link(s)", data={"delivery": delivery_id, "sha256": digest})
    return {"status": rec.status, "links_created": created}


def _tasks_for(db: Session, repo: ScmRepository, keys: set[str]) -> list[WorkItem]:
    if not keys:
        return []
    return list(db.execute(select(WorkItem).where(WorkItem.key.in_(keys), WorkItem.project_id == repo.project_id)).scalars())


def _on_push(db: Session, repo: ScmRepository, p: dict) -> int:
    ref = p.get("ref") or ""
    if not ref.startswith("refs/heads/"):
        return 0
    branch = ref[len("refs/heads/"):]
    deleted = (p.get("after") or "").strip("0") == ""
    n = 0
    for task in _tasks_for(db, repo, task_keys(branch)):
        _, new = upsert_link(db, task, repo, "BRANCH", branch, origin="WEBHOOK", url=_branch_url(repo, branch), state="deleted" if deleted else "active")
        n += new
    for c in p.get("commits") or []:
        for task in _tasks_for(db, repo, task_keys(c.get("message"), branch)):
            _, new = upsert_link(db, task, repo, "COMMIT", c.get("id", ""), origin="WEBHOOK", **_commit_fields(c, repo))
            n += new
    return n


def _on_merge_request(db: Session, repo: ScmRepository, p: dict) -> int:
    a = p.get("object_attributes") or {}
    if not a.get("iid"):
        return 0
    mr = {**a, "author": {"username": (p.get("user") or {}).get("username")}}
    n = 0
    for task in _tasks_for(db, repo, task_keys(a.get("title"), a.get("description"), a.get("source_branch"))):
        link, new = upsert_link(db, task, repo, "MERGE_REQUEST", str(a["iid"]), origin="WEBHOOK", **_mr_fields(mr))
        n += new
        _automate(db, task, link)
    return n
