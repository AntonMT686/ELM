"""Deployment and software release rules (architecture §14).

Lifecycle (§14.1): PLANNED → AWAITING_APPROVAL → APPROVED → DEPLOYING → DEPLOYED, with REJECTED, FAILED (→ DEPLOYING on an
authorised retry), CANCELLED and ROLLED_BACK (set on the original when a rollback deployment succeeds).

Gates (§14.2) are evaluated before every execution and each failed gate names the exact missing condition.
Execution (§14.3) is a queued attempt run by the worker through an adapter:
* manual          — the operator deploys and records the outcome in ELM (common on isolated networks);
* gitlab_pipeline — ELM triggers a pipeline in a registered GitLab repository and follows it;
* script          — an approved script from ELM_DEPLOY_SCRIPTS_DIR, named in the approved configuration (never from
                    the browser), run without a shell, with a timeout and secrets passed only as environment variables.
CI systems may also report through a signed (HMAC-SHA256) callback. Logs are stored with secrets masked; a health check
runs after a successful execution. Retries are new attempts; rollbacks are new deployments.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.errors import AppError, Forbidden
from app.models import Document, DocumentType, Project, User
from app.models.artifacts import ArtifactLink, ArtifactReview
from app.models.deployment import Deployment, DeploymentAttempt, DeploymentEnvironment
from app.models.scm import ScmRepository
from app.models.testing import Defect, TestRun
from app.services import artifacts as art
from app.services import audit as auditsvc
from app.services.notify import notify

A = "DEPLOYMENT"
ADAPTERS = ("manual", "gitlab_pipeline", "script")
STATES = [
    {"code": "PLANNED", "label": "Planned", "color": "gray"}, {"code": "AWAITING_APPROVAL", "label": "Awaiting approval", "color": "violet"},
    {"code": "APPROVED", "label": "Approved", "color": "cyan"}, {"code": "REJECTED", "label": "Rejected", "color": "red"},
    {"code": "DEPLOYING", "label": "Deploying", "color": "blue"}, {"code": "DEPLOYED", "label": "Deployed", "color": "teal"},
    {"code": "FAILED", "label": "Failed", "color": "red"}, {"code": "ROLLED_BACK", "label": "Rolled back", "color": "orange"},
    {"code": "CANCELLED", "label": "Cancelled", "color": "gray"},
]
CANCELLABLE = ("PLANNED", "AWAITING_APPROVAL", "APPROVED")
OPEN_DEFECT = ("OPEN", "IN_PROGRESS", "FIXED")
DEFAULT_CONFIG: dict = {
    "requires_approval": True,
    "approvals_required": 1,
    "require_config_approval": True,
    "require_test_run": True,
    "match_test_build": True,
    "blocking_defect_severities": ["CRITICAL"],
    "required_document_types": [],
    "checklist": [],
    "require_commit": False,
    "secrets": [],
    "change_window": None,  # {"days": [0..6, Monday = 0], "start": "HH:MM", "end": "HH:MM"} in ELM_TIMEZONE
    "blackout_dates": [],
    "adapter": "manual",
    "adapter_config": {},  # gitlab_pipeline: {"repository_id", "variables"}; script: {"script"}
    "health_check": None,  # {"url", "expect_status", "expect_text", "timeout_seconds", "retries"}
}
SECRET_NAME = re.compile(r"^[A-Z0-9_]{2,60}$")
SCRIPT_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_MASK_PATTERNS = [
    re.compile(r"(?i)((?:password|passwd|pwd|token|secret|api[_-]?key|private[_-]token)\s*[=:]\s*)(\"?)[^\s\"']+"),
    re.compile(r"(?i)(authorization:\s*(?:bearer|basic|token)\s+)\S+"),
    re.compile(r"glpat-[A-Za-z0-9_\-]{10,}"),
]
MAX_LOG = 200_000


# ------------------------------------------------------------------ configuration
def canon(obj) -> tuple[str, str]:
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return text, hashlib.sha256(text.encode()).hexdigest()


def validate_config(db: Session, project_id: uuid.UUID, cfg: dict) -> dict:
    unknown = set(cfg) - set(DEFAULT_CONFIG)
    if unknown:
        raise AppError(f"Unknown setting: {', '.join(sorted(unknown))}.")
    c = {**DEFAULT_CONFIG, **cfg}
    errors: list[str] = []
    if not isinstance(c["approvals_required"], int) or not 1 <= c["approvals_required"] <= 5:
        errors.append("Approvals required must be between 1 and 5.")
    for s in c["blocking_defect_severities"]:
        if s not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            errors.append(f"Unknown defect severity {s}.")
    for code in c["required_document_types"]:
        if not db.execute(select(DocumentType.id).where(DocumentType.code == code)).first():
            errors.append(f"Unknown document type {code}.")
    if not all(isinstance(x, str) and x.strip() for x in c["checklist"]):
        errors.append("Checklist items must be non-empty text.")
    for s in c["secrets"]:
        if not SECRET_NAME.match(str(s)):
            errors.append(f"Secret name {s} must be upper-case letters, digits and underscores (it is read from ELM_DEPLOY_SECRET_{s}).")
    w = c["change_window"]
    if w:
        if not isinstance(w, dict) or not HHMM.match(str(w.get("start", ""))) or not HHMM.match(str(w.get("end", ""))) or not w.get("days") or not set(w["days"]) <= set(range(7)):
            errors.append("Change window needs days (0 = Monday … 6 = Sunday) and start/end times as HH:MM.")
    for dstr in c["blackout_dates"]:
        try:
            datetime.strptime(str(dstr), "%Y-%m-%d")
        except ValueError:
            errors.append(f"Blackout date {dstr} must be YYYY-MM-DD.")
    if c["adapter"] not in ADAPTERS:
        errors.append(f"Adapter must be one of {', '.join(ADAPTERS)}.")
    ac = c["adapter_config"] or {}
    if c["adapter"] == "gitlab_pipeline":
        rid = ac.get("repository_id")
        repo = db.get(ScmRepository, uuid.UUID(str(rid))) if rid else None
        if not repo or repo.project_id != project_id:
            errors.append("The GitLab pipeline adapter needs a repository registered for this project.")
        if not isinstance(ac.get("variables", {}), dict):
            errors.append("Pipeline variables must be name → value pairs.")
    if c["adapter"] == "script" and not SCRIPT_NAME.match(str(ac.get("script", ""))):
        errors.append("The script adapter needs a script file name (letters, digits, . _ -) from the server's deployment-script folder.")
    hc = c["health_check"]
    if hc:
        if not isinstance(hc, dict) or not re.match(r"^https?://", str(hc.get("url", ""))):
            errors.append("The health check needs an http(s) URL.")
        elif not 1 <= int(hc.get("retries", 3)) <= 10 or not 1 <= int(hc.get("timeout_seconds", 10)) <= 120:
            errors.append("Health check retries must be 1–10 and timeout 1–120 seconds.")
    if errors:
        raise AppError("The environment configuration is not valid.", code="CONFIG_INVALID", details={"errors": errors})
    return c


def env_config(env: DeploymentEnvironment) -> dict:
    return {**DEFAULT_CONFIG, **json.loads(env.config or "{}")}


def set_config(env: DeploymentEnvironment, cfg: dict, user_id: uuid.UUID) -> bool:
    text, sha = canon(cfg)
    changed = sha != env.config_sha256
    env.config, env.config_sha256, env.config_changed_by_id = text, sha, user_id
    if changed:
        env.config_status = "DRAFT"  # an edited configuration must be approved again
    return changed


# ------------------------------------------------------------------ deployments
def content_hash(d: Deployment) -> str:
    return canon({"env": str(d.environment_id), "version": d.version_label, "ref": d.git_ref, "commit": d.commit_sha, "repo": str(d.repository_id) if d.repository_id else None,
                  "run": str(d.test_run_id) if d.test_run_id else None, "notes": d.release_notes or "", "rollback_of": str(d.rollback_of_id) if d.rollback_of_id else None})[1]


def set_status(db: Session, d: Deployment, to: str, actor: uuid.UUID | None, reason: str | None = None) -> None:
    if d.status != to:
        art.add_event(db, A, d.id, "STATUS", actor, d.status, to, reason)
        d.status = to
        d.status_reason = (reason or "")[:1000] or None
        d.version += 1


def current_on(db: Session, env_id: uuid.UUID) -> Deployment | None:
    return db.execute(select(Deployment).where(Deployment.environment_id == env_id, Deployment.status == "DEPLOYED").order_by(Deployment.deployed_at.desc())).scalars().first()


def approvals(db: Session, d: Deployment) -> list[ArtifactReview]:
    cycle = art.current_cycle(db, A, d.id)
    return list(db.execute(select(ArtifactReview).where(ArtifactReview.artifact_type == A, ArtifactReview.artifact_id == d.id, ArtifactReview.cycle == cycle)).scalars()) if cycle else []


# ------------------------------------------------------------------ gates
def _gate(code: str, label: str, ok: bool, detail: str) -> dict:
    return {"code": code, "label": label, "ok": bool(ok), "detail": detail}


def evaluate_gates(db: Session, d: Deployment, now: datetime | None = None) -> list[dict]:
    """§14.2. Each entry says exactly what is missing when it fails."""
    env = db.get(DeploymentEnvironment, d.environment_id)
    c = env_config(env)
    s = get_settings()
    out: list[dict] = []
    busy = db.execute(select(Deployment.key).where(Deployment.environment_id == env.id, Deployment.status == "DEPLOYING", Deployment.id != d.id)).scalars().first()
    out.append(_gate("target", "Correct target project and environment", env.active and env.project_id == d.project_id and not busy,
                     f"{env.code} is switched off" if not env.active else f"{busy} is deploying to {env.code} right now" if busy else f"{env.code} of this project"))

    # version / tag / commit
    if d.repository_id:
        repo = db.get(ScmRepository, d.repository_id)
        if not d.commit_sha:
            out.append(_gate("version", "Approved version, tag and commit", False, "No commit SHA is recorded for this deployment."))
        elif not (s.gitlab_enabled and s.gitlab_token):
            out.append(_gate("version", "Approved version, tag and commit", False, "GitLab is switched off, so the tag/commit cannot be verified."))
        else:
            from app.services.gitlab_client import GitLab, GitLabError

            try:
                commit = GitLab.from_settings().commit(repo.external_id, d.git_ref or d.commit_sha)
                ok = str(commit.get("id", "")).startswith(d.commit_sha.lower()) or d.commit_sha.lower().startswith(str(commit.get("id", ""))[:12])
                out.append(_gate("version", "Approved version, tag and commit", ok, f"{d.git_ref or d.commit_sha[:12]} is commit {str(commit.get('id', ''))[:12]}" + ("" if ok else f", not the approved {d.commit_sha[:12]}")))
            except GitLabError as e:
                out.append(_gate("version", "Approved version, tag and commit", False, e.message))
    else:
        out.append(_gate("version", "Approved version, tag and commit", not c["require_commit"], f"version {d.version_label}" + (" (this environment requires a registered repository and commit)" if c["require_commit"] else " (no repository linked)")))

    # approval
    if c["requires_approval"]:
        rows = approvals(db, d)
        good = [r for r in rows if r.role == "APPROVER" and r.status == "APPROVED" and r.content_sha256 == d.content_sha256]
        ok = d.status in ("APPROVED", "FAILED") and len(good) >= c["approvals_required"]
        out.append(_gate("approval", f"{c['approvals_required']} approval(s) of this exact request", ok, f"{len(good)} of {c['approvals_required']} approved" + ("" if rows or ok else "; not submitted for approval")))
    else:
        out.append(_gate("approval", "Approval", d.status in ("APPROVED", "FAILED"), "not required for this environment" if d.status in ("APPROVED", "FAILED") else "submit the request first"))

    # test run
    if c["require_test_run"]:
        run = db.get(TestRun, d.test_run_id) if d.test_run_id else None
        if not run:
            out.append(_gate("test", "Required test run closed and passed", False, "No test run is linked."))
        else:
            ev = json.loads(run.closure_evaluation or "{}")
            closed = run.status == "CLOSED" and run.project_id == d.project_id
            build_ok = not (c["match_test_build"] and run.build_version and run.build_version != d.version_label)
            detail = f"{run.key} is {run.status.lower().replace('_', ' ')}" + (f", {ev.get('pass_rate')}% passed" if closed else "") + ("" if build_ok else f"; it tested build {run.build_version}, not {d.version_label}")
            out.append(_gate("test", "Required test run closed and passed", closed and build_ok, detail))

    # defects
    sev = c["blocking_defect_severities"]
    if sev:
        rows = db.execute(select(Defect.key).where(Defect.project_id == d.project_id, Defect.status.in_(OPEN_DEFECT), Defect.severity.in_(sev))).scalars().all()
        out.append(_gate("defects", f"No open {'/'.join(x.lower() for x in sev)} defects", not rows, ", ".join(rows) if rows else "none open"))

    # documents and checklist
    docs = []
    for code in c["required_document_types"]:
        linked = db.execute(select(Document).join(ArtifactLink, (ArtifactLink.to_id == Document.id) & (ArtifactLink.to_type == "DOCUMENT")).join(DocumentType, DocumentType.id == Document.type_id)
                            .where(ArtifactLink.from_type == A, ArtifactLink.from_id == d.id, DocumentType.code == code)).scalars().all()
        if not any(x.status == "RELEASED" for x in linked):
            docs.append(f"a released {code} document" + (f" ({', '.join(x.number + ' is ' + x.status.lower() for x in linked)})" if linked else ""))
    ticked = json.loads(d.checklist or "{}")
    open_items = [i for i in c["checklist"] if not ticked.get(i)]
    if c["required_document_types"] or c["checklist"]:
        missing = docs + [f"checklist: {i}" for i in open_items]
        out.append(_gate("documents", "Release documents and checklist complete", not missing, "missing " + "; ".join(missing) if missing else "complete"))

    # configuration
    if c["require_config_approval"]:
        ok = env.config_status == "APPROVED" and env.config_approved_sha256 == env.config_sha256
        out.append(_gate("config", "Deployment configuration approved", ok, "approved" if ok else f"the {env.code} configuration was changed and is not approved"))

    # credentials
    missing_secrets = [n for n in c["secrets"] if not os.environ.get(f"ELM_DEPLOY_SECRET_{n}")]
    adapter_problem = None
    if c["adapter"] == "gitlab_pipeline" and not (s.gitlab_enabled and s.gitlab_token):
        adapter_problem = "GitLab integration is not configured"
    if c["adapter"] == "script":
        p = script_path(c["adapter_config"].get("script", ""))
        if p is None:
            adapter_problem = f"script {c['adapter_config'].get('script')} is not in the deployment-script folder (ELM_DEPLOY_SCRIPTS_DIR)"
    if c["secrets"] or c["adapter"] != "manual":
        problems = [f"ELM_DEPLOY_SECRET_{n} is not set on the server" for n in missing_secrets] + ([adapter_problem] if adapter_problem else [])
        out.append(_gate("credentials", "Credentials and adapter available", not problems, "; ".join(problems) if problems else "available"))

    # change window and blackout dates
    w = c["change_window"]
    local = (now or utcnow()).astimezone(ZoneInfo(s.timezone))
    if w or c["blackout_dates"]:
        problems = []
        if local.strftime("%Y-%m-%d") in c["blackout_dates"]:
            problems.append(f"{local:%Y-%m-%d} is a blackout date")
        if w:
            hm = local.strftime("%H:%M")
            in_time = w["start"] <= hm < w["end"] if w["start"] <= w["end"] else (hm >= w["start"] or hm < w["end"])
            if local.weekday() not in w["days"] or not in_time:
                names = "Mon Tue Wed Thu Fri Sat Sun".split()
                problems.append(f"outside the change window ({', '.join(names[i] for i in sorted(w['days']))} {w['start']}–{w['end']} {s.timezone}; now {local:%a %H:%M})")
        out.append(_gate("window", "Change window and ADA conditions", not problems, "; ".join(problems) if problems else f"inside the window ({local:%a %H:%M})"))
    return out


# ------------------------------------------------------------------ execution
def script_path(name: str) -> Path | None:
    s = get_settings()
    if not s.deploy_scripts_dir or not SCRIPT_NAME.match(name or ""):
        return None
    root = Path(s.deploy_scripts_dir).resolve()
    p = (root / name).resolve()
    if p.parent != root or not p.is_file():
        return None
    return p


def secret_values(c: dict) -> list[str]:
    vals = [os.environ.get(f"ELM_DEPLOY_SECRET_{n}", "") for n in c["secrets"]]
    s = get_settings()
    vals += [s.gitlab_token, s.deploy_callback_secret]
    return [v for v in vals if v and len(v) >= 4]


def mask(text: str | None, secrets: list[str]) -> str:
    out = text or ""
    for v in sorted(secrets, key=len, reverse=True):
        out = out.replace(v, "****")
    for pat in _MASK_PATTERNS:
        out = pat.sub(lambda m: (m.group(1) if m.groups() else "") + "****", out)
    return out[-MAX_LOG:]


def queue(db: Session, d: Deployment, user_id: uuid.UUID) -> DeploymentAttempt:
    if d.status not in ("APPROVED", "FAILED"):
        raise AppError(f"A {d.status.lower().replace('_', ' ')} deployment cannot be executed.", code="INVALID_STATE")
    gates = evaluate_gates(db, d)
    failed = [f"{g['label']}: {g['detail']}" for g in gates if not g["ok"]]
    if failed:
        raise AppError("Validation gates are not met.", code="GATE_BLOCKED", details={"errors": failed, "gates": gates})
    env = db.get(DeploymentEnvironment, d.environment_id)
    n = len(db.execute(select(DeploymentAttempt.id).where(DeploymentAttempt.deployment_id == d.id)).all()) + 1
    a = DeploymentAttempt(deployment_id=d.id, attempt_no=n, adapter=env_config(env)["adapter"], status="QUEUED", queued_at=utcnow(), triggered_by_id=user_id,
                          target=f"{env.code} {d.version_label}"[:200], gate_snapshot=json.dumps(gates))
    db.add(a)
    set_status(db, d, "DEPLOYING", user_id, f"attempt {n} queued")
    db.flush()
    return a


def _log(a: DeploymentAttempt, line: str, secrets: list[str]) -> None:
    a.log = mask((a.log or "") + f"[{utcnow():%Y-%m-%d %H:%M:%S}Z] {line}\n", secrets)


def health_check(c: dict, d: Deployment) -> dict:
    hc = c["health_check"]
    if not hc:
        return {"ok": True, "skipped": True}
    url = str(hc["url"]).replace("{version}", d.version_label)
    expect, text = int(hc.get("expect_status", 200)), hc.get("expect_text")
    tries = []
    for i in range(int(hc.get("retries", 3))):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ADA-ELM-health"}), timeout=int(hc.get("timeout_seconds", 10))) as r:  # noqa: S310 - URL from approved config
                body = r.read(20000).decode("utf-8", "replace")
                ok = r.status == expect and (not text or text.replace("{version}", d.version_label) in body)
                tries.append({"status": r.status, "ok": ok})
                if ok:
                    return {"ok": True, "url": url, "tries": tries}
        except urllib.error.HTTPError as e:
            tries.append({"status": e.code, "ok": False})
        except (urllib.error.URLError, OSError) as e:
            tries.append({"error": str(getattr(e, "reason", e))[:200], "ok": False})
        if i + 1 < int(hc.get("retries", 3)):
            time.sleep(float(get_settings().deploy_health_retry_seconds))
    return {"ok": False, "url": url, "tries": tries, "expected": {"status": expect, "text": text}}


def finish(db: Session, a: DeploymentAttempt, success: bool, reason: str | None, actor: uuid.UUID | None) -> None:
    """Ends an attempt. Success runs the health check first; the deployment only becomes DEPLOYED when it passes."""
    d = db.get(Deployment, a.deployment_id)
    env = db.get(DeploymentEnvironment, d.environment_id)
    c = env_config(env)
    secrets = secret_values(c)
    if success:
        h = health_check(c, d)
        a.health = json.dumps(h)
        if not h["ok"]:
            success, reason = False, f"Health check failed at {h.get('url')}"
            _log(a, reason, secrets)
    a.finished_at = utcnow()
    a.status = "SUCCEEDED" if success else "FAILED"
    a.failure_reason = None if success else mask(reason or "failed", secrets)[:1000]
    if success:
        d.deployed_at = utcnow()
        set_status(db, d, "DEPLOYED", actor, f"attempt {a.attempt_no} succeeded")
        if d.rollback_of_id:
            orig = db.get(Deployment, d.rollback_of_id)
            if orig and orig.status == "DEPLOYED":
                set_status(db, orig, "ROLLED_BACK", actor, f"rolled back by {d.key}")
    else:
        set_status(db, d, "FAILED", actor, a.failure_reason)
    auditsvc.record(db, actor_id=actor, action="deployment.finish", entity_type="deployment", entity_id=d.id, summary=f"{d.key} attempt {a.attempt_no} {a.status.lower()} on {env.code}",
                    data={"attempt": str(a.id), "reason": a.failure_reason, "health": json.loads(a.health) if a.health else None})
    if d.requested_by_id:
        notify(db, d.requested_by_id, "deployment.result", f"{d.key} {'deployed to' if success else 'failed on'} {env.code}", a.failure_reason or d.version_label,
               link=f"/deployments/{d.project_id}?open={d.id}", severity="info" if success else "warning")


def run_pending(db: Session, now: datetime | None = None) -> int:
    """Worker step: start queued attempts, follow running pipelines, time out stuck ones."""
    now = now or utcnow()
    s = get_settings()
    n = 0
    for a in db.execute(select(DeploymentAttempt).where(DeploymentAttempt.status.in_(["QUEUED", "WAITING"])).order_by(DeploymentAttempt.queued_at)).scalars().all():
        d = db.get(Deployment, a.deployment_id)
        env = db.get(DeploymentEnvironment, d.environment_id)
        c = env_config(env)
        secrets = secret_values(c)
        try:
            if a.status == "QUEUED":
                a.status, a.started_at, a.worker = "RUNNING", now, socket.gethostname()[:120]
                _log(a, f"Attempt {a.attempt_no}: {a.adapter} deployment of {d.version_label} to {env.code} started", secrets)
                _start(db, a, d, env, c, secrets)
                n += 1
            elif a.status == "WAITING":
                if a.adapter == "gitlab_pipeline":
                    n += _poll_pipeline(db, a, d, c, secrets)
                if a.status == "WAITING" and a.started_at and now - a.started_at > timedelta(hours=s.deploy_timeout_hours):
                    _log(a, "No result within the time limit", secrets)
                    finish(db, a, False, f"No result after {s.deploy_timeout_hours} h", None)
                    n += 1
        except AppError as e:
            _log(a, f"Error: {e.message}", secrets)
            finish(db, a, False, e.message, None)
            n += 1
    return n


def _start(db: Session, a: DeploymentAttempt, d: Deployment, env: DeploymentEnvironment, c: dict, secrets: list[str]) -> None:
    if a.adapter == "manual":
        a.status = "WAITING"
        _log(a, "Waiting for the operator to deploy and record the outcome in ELM", secrets)
        return
    if a.adapter == "gitlab_pipeline":
        from app.services.gitlab_client import GitLab

        repo = db.get(ScmRepository, uuid.UUID(str(c["adapter_config"]["repository_id"])))
        variables = {**{str(k): str(v) for k, v in (c["adapter_config"].get("variables") or {}).items()}, "ELM_DEPLOYMENT": d.key, "ELM_ENVIRONMENT": env.code, "ELM_VERSION": d.version_label, "ELM_COMMIT": d.commit_sha or ""}
        p = GitLab.from_settings().create_pipeline(repo.external_id, d.git_ref or repo.default_branch, variables)
        a.status, a.external_ref, a.external_url = "WAITING", str(p.get("id")), p.get("web_url")
        _log(a, f"GitLab pipeline {p.get('id')} created on {d.git_ref or repo.default_branch} in {repo.path}", secrets)
        return
    path = script_path(c["adapter_config"].get("script", ""))
    if path is None:
        raise AppError("The deployment script is not available on the server.")
    child_env = {"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "ELM_DEPLOYMENT": d.key, "ELM_ENVIRONMENT": env.code, "ELM_VERSION": d.version_label, "ELM_COMMIT": d.commit_sha or "", "ELM_REF": d.git_ref or ""}
    child_env.update({f"ELM_DEPLOY_SECRET_{n}": os.environ.get(f"ELM_DEPLOY_SECRET_{n}", "") for n in c["secrets"]})
    cmd = [str(path), env.code, d.version_label, d.commit_sha or ""]
    if path.suffix.lower() == ".ps1":
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", *cmd]
    elif path.suffix.lower() == ".py":
        import sys

        cmd = [sys.executable, *cmd]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=get_settings().deploy_script_timeout_seconds, env=child_env, cwd=str(path.parent), shell=False)  # noqa: S603 - approved script, no shell
        _log(a, f"$ {path.name} {env.code} {d.version_label}\n{r.stdout}{r.stderr}exit code {r.returncode}", secrets)
        finish(db, a, r.returncode == 0, None if r.returncode == 0 else f"{path.name} exited with code {r.returncode}", None)
    except subprocess.TimeoutExpired:
        _log(a, f"{path.name} did not finish within {get_settings().deploy_script_timeout_seconds} s and was stopped", secrets)
        finish(db, a, False, "Deployment script timed out", None)


def _poll_pipeline(db: Session, a: DeploymentAttempt, d: Deployment, c: dict, secrets: list[str]) -> int:
    from app.services.gitlab_client import GitLab

    repo = db.get(ScmRepository, uuid.UUID(str(c["adapter_config"]["repository_id"])))
    p = GitLab.from_settings().pipeline(repo.external_id, a.external_ref)
    st = p.get("status")
    if st == "success":
        _log(a, f"Pipeline {a.external_ref} succeeded", secrets)
        finish(db, a, True, None, None)
        return 1
    if st in ("failed", "canceled", "skipped"):
        _log(a, f"Pipeline {a.external_ref} {st}", secrets)
        finish(db, a, False, f"GitLab pipeline {a.external_ref} {st}", None)
        return 1
    return 0


# ------------------------------------------------------------------ CI callback
def verify_callback(body: bytes, signature: str | None) -> bool:
    secret = get_settings().deploy_callback_secret
    if not secret or not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature[7:])


# ------------------------------------------------------------------ helpers for the API
def check_approvers(db: Session, project_id: uuid.UUID, ids: list[uuid.UUID]) -> None:
    from app.services.authz import load_principal

    for uid in ids:
        u = db.get(User, uid)
        if not u or not load_principal(db, u).has("deploy.approve", project_id=project_id):
            raise Forbidden(f"{u.full_name if u else 'That person'} does not hold the deployment approval permission for this project.", details={"permission": "deploy.approve"})


def next_key(db: Session, project: Project) -> str:
    from app.services.numbering import next_seq

    return f"{project.code}-DEP-{next_seq(db, 'dep:' + project.code):04d}"
