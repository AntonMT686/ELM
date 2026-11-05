from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import aware, get_db, utcnow
from app.core.deps import Ctx, get_ctx
from app.core.errors import AppError, Unauthorized
from app.core.security import create_session_token, hash_password, new_csrf_token, verify_password
from app.models import OrgUnit, Project, ProjectMember, User, UserOrgAssignment, WorkflowTask
from app.services import audit
from app.services.serial import org_brief

router = APIRouter(prefix="/auth", tags=["auth"])
LOCK_AFTER = 5
LOCK_MINUTES = 15


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


def _set_cookies(resp: Response, token: str) -> None:
    s = get_settings()
    resp.set_cookie(s.cookie_name, token, httponly=True, secure=s.cookie_secure, samesite="strict", max_age=s.access_token_minutes * 60, path="/")
    resp.set_cookie(s.csrf_cookie_name, new_csrf_token(), httponly=False, secure=s.cookie_secure, samesite="strict", max_age=s.access_token_minutes * 60, path="/")


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else None
    user = db.execute(select(User).where(func.lower(User.username) == body.username.strip().lower())).scalar_one_or_none()
    generic = "Invalid username or password."
    if not user or not user.is_active:
        audit.record(db, actor_id=None, action="auth.login_failed", entity_type="auth", entity_id=None, summary=f"Login failed for '{body.username[:40]}'", ip=ip, outcome="FAILURE")
        db.commit()
        raise Unauthorized(generic)
    if user.locked_until and aware(user.locked_until) > utcnow():
        raise Unauthorized("Account temporarily locked after repeated failures. Try again later.")
    if user.auth_source != "local":
        raise AppError("Directory (LDAP/AD) sign-in is not configured in this environment.", code="LDAP_NOT_CONFIGURED")
    if not verify_password(body.password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= LOCK_AFTER:
            user.locked_until = utcnow() + timedelta(minutes=LOCK_MINUTES)
            user.failed_logins = 0
        audit.record(db, actor_id=user.id, action="auth.login_failed", entity_type="auth", entity_id=user.id, summary="Login failed (bad password)", ip=ip, outcome="FAILURE")
        db.commit()
        raise Unauthorized(generic)
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    audit.record(db, actor_id=user.id, action="auth.login", entity_type="auth", entity_id=user.id, summary=f"{user.username} signed in", ip=ip)
    db.commit()
    _set_cookies(response, create_session_token(str(user.id)))
    return {"ok": True}


@router.post("/logout")
def logout(response: Response, ctx: Ctx = Depends(get_ctx)):
    s = get_settings()
    ctx.audit("auth.logout", "auth", ctx.user.id, f"{ctx.user.username} signed out")
    ctx.db.commit()
    response.delete_cookie(s.cookie_name, path="/")
    response.delete_cookie(s.csrf_cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
def me(ctx: Ctx = Depends(get_ctx)):
    db, u, p = ctx.db, ctx.user, ctx.p
    orgs = db.execute(select(OrgUnit, UserOrgAssignment.position).join(UserOrgAssignment, UserOrgAssignment.org_unit_id == OrgUnit.id).where(UserOrgAssignment.user_id == u.id)).all()
    if p.has_global("project.view") or p.has_any("release.view_all"):
        projects = db.execute(select(Project).order_by(Project.code)).scalars().all()
    else:
        pids = set(db.execute(select(ProjectMember.project_id).where(ProjectMember.user_id == u.id)).scalars())
        pids |= {g.scope_id for g in p.grants if g.scope_type == "PROJECT" and g.scope_id}
        projects = db.execute(select(Project).where(Project.id.in_(pids)).order_by(Project.code)).scalars().all() if pids else []
    pending = db.execute(select(func.count(WorkflowTask.id)).where(WorkflowTask.assignee_id == u.id, WorkflowTask.status == "PENDING")).scalar()
    perms = sorted(p.all_perms())
    oversight = any(o.is_oversight for o, _ in orgs) or p.has_any("release.view_all")
    return {
        "user": {"id": str(u.id), "username": u.username, "full_name": u.full_name, "email": u.email, "designation": u.designation, "employee_no": u.employee_no, "is_system_admin": u.is_system_admin},
        "orgs": [{**org_brief(o), "position": pos, "is_oversight": o.is_oversight} for o, pos in orgs],
        "projects": [{"id": str(x.id), "code": x.code, "name": x.name, "color": x.color} for x in projects],
        "roles": sorted(p.role_codes()),
        "permissions": perms,
        "perspective": "OVERSIGHT" if oversight else ("ADMIN" if u.is_system_admin and len(p.grants) == 1 else "ENGINEER"),
        "pending_tasks": pending,
        "preferences": json.loads(u.preferences) if u.preferences else {},
        "settings": {"onlyoffice_enabled": get_settings().onlyoffice_enabled, "environment": get_settings().environment, "app_name": get_settings().app_name},
    }


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


@router.post("/change-password")
def change_password(body: PasswordIn, ctx: Ctx = Depends(get_ctx)):
    if not verify_password(body.current_password, ctx.user.password_hash):
        raise AppError("Current password is incorrect.", code="BAD_PASSWORD")
    ctx.user.password_hash = hash_password(body.new_password)
    ctx.audit("auth.password_change", "user", ctx.user.id, "Password changed")
    ctx.db.commit()
    return {"ok": True}


@router.put("/preferences")
def save_prefs(body: dict, ctx: Ctx = Depends(get_ctx)):
    data = json.dumps(body)[:8000]
    ctx.user.preferences = data
    ctx.db.commit()
    return {"ok": True}
