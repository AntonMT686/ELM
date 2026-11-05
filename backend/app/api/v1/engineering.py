"""Projects/programmes and the configurable product breakdown (Aircraft → System → Subsystem → LRU → SRU)."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.deps import Ctx, get_ctx, get_or_404
from app.core.errors import AppError, Conflict
from app.models import (
    Document,
    EngineeringItem,
    EngineeringItemOrg,
    HierarchyLevel,
    OrgUnit,
    ProcessDomain,
    Project,
    ProjectMember,
    ProjectOrgAssignment,
    User,
    WorkItem,
)
from app.services.authz import document_visibility_clause
from app.services.planning import require_view_project
from app.services.progress import item_rollup
from app.services.serial import iso, org_brief, user_brief
from app.services.task_lifecycle import closed_statuses

router = APIRouter(tags=["projects & engineering"])


def _require_project_access(ctx: Ctx, p: Project) -> None:
    # Head Directorate oversight reads every programme's structure through the release register.
    if not ctx.p.has_any("release.view_all"):
        require_view_project(ctx.db, ctx.p, p.id)


def _project_dict(ctx: Ctx, p: Project) -> dict:
    lead = ctx.db.get(OrgUnit, p.lead_org_unit_id) if p.lead_org_unit_id else None
    orgs = ctx.db.execute(select(OrgUnit, ProjectOrgAssignment.participation).join(ProjectOrgAssignment, ProjectOrgAssignment.org_unit_id == OrgUnit.id).where(ProjectOrgAssignment.project_id == p.id)).all()
    return {
        "id": str(p.id), "code": p.code, "name": p.name, "programme": p.programme, "description": p.description, "status": p.status, "color": p.color,
        "classification": p.classification, "start_date": iso(p.start_date), "end_date": iso(p.end_date), "lead_org": org_brief(lead),
        "orgs": [{**org_brief(o), "participation": part} for o, part in orgs],
        "levels": [{"id": str(lv.id), "level_no": lv.level_no, "code": lv.code, "name": lv.name, "icon": lv.icon, "color": lv.color} for lv in p.levels],
    }


@router.get("/projects")
def list_projects(ctx: Ctx = Depends(get_ctx)):
    projects = ctx.db.execute(select(Project).order_by(Project.code)).scalars().all()
    if not (ctx.p.has_global("project.view") or ctx.p.has_any("release.view_all")):
        mine = set(ctx.db.execute(select(ProjectMember.project_id).where(ProjectMember.user_id == ctx.user.id)).scalars())
        mine |= {g.scope_id for g in ctx.p.grants if g.scope_type == "PROJECT"}
        projects = [p for p in projects if p.id in mine]
    vis = document_visibility_clause(ctx.db, ctx.p)
    out = []
    for p in projects:
        q = select(Document.status, func.count()).where(Document.project_id == p.id)
        if vis is not None:
            q = q.where(vis)
        counts = dict(ctx.db.execute(q.group_by(Document.status)).all())
        items = ctx.db.execute(select(func.count(EngineeringItem.id)).where(EngineeringItem.project_id == p.id)).scalar()
        out.append({**_project_dict(ctx, p), "doc_counts": counts, "item_count": items})
    return out


class LevelIn(BaseModel):
    code: str = Field(pattern=r"^[A-Z0-9_]{2,30}$")
    name: str
    icon: str | None = None
    color: str | None = None


class ProjectIn(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str
    programme: str | None = None
    description: str | None = None
    status: str = "ACTIVE"
    lead_org_unit_id: uuid.UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    color: str | None = None
    classification: str | None = None
    levels: list[LevelIn] = Field(default_factory=list)
    contributing_org_ids: list[uuid.UUID] = Field(default_factory=list)


@router.post("/projects")
def create_project(body: ProjectIn, ctx: Ctx = Depends(get_ctx)):
    ctx.p.require("project.manage")
    if ctx.db.execute(select(Project.id).where(Project.code == body.code)).first():
        raise Conflict("Project code already exists.")
    p = Project(**body.model_dump(exclude={"levels", "contributing_org_ids"}))
    ctx.db.add(p)
    ctx.db.flush()
    levels = body.levels or [LevelIn(code="AIRCRAFT", name="Aircraft"), LevelIn(code="SYSTEM", name="System"), LevelIn(code="SUBSYSTEM", name="Subsystem"), LevelIn(code="LRU", name="LRU")]
    for i, lv in enumerate(levels, 1):
        ctx.db.add(HierarchyLevel(project_id=p.id, level_no=i, **lv.model_dump()))
    if body.lead_org_unit_id:
        ctx.db.add(ProjectOrgAssignment(project_id=p.id, org_unit_id=body.lead_org_unit_id, participation="LEAD"))
    for oid in set(body.contributing_org_ids) - {body.lead_org_unit_id}:
        ctx.db.add(ProjectOrgAssignment(project_id=p.id, org_unit_id=oid, participation="CONTRIBUTOR"))
    ctx.audit("project.create", "project", p.id, f"Project {p.code} created", {"levels": [lv.code for lv in levels]})
    ctx.db.commit()
    ctx.db.refresh(p)
    return _project_dict(ctx, p)


@router.get("/projects/{pid}")
def get_project(pid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    p = get_or_404(ctx.db, Project, pid, "Project")
    _require_project_access(ctx, p)
    return _project_dict(ctx, p)


@router.get("/projects/{pid}/tree")
def project_tree(pid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    """Flat list (client builds the tree) with explainable progress roll-up per node."""
    p = get_or_404(ctx.db, Project, pid, "Project")
    _require_project_access(ctx, p)
    vis = document_visibility_clause(ctx.db, ctx.p)
    visible = None
    if vis is not None:
        visible = set(ctx.db.execute(select(Document.id).where(Document.project_id == p.id, vis)).scalars())
    roll = item_rollup(ctx.db, p.id, visible)
    items = ctx.db.execute(select(EngineeringItem).where(EngineeringItem.project_id == p.id).order_by(EngineeringItem.sort_order, EngineeringItem.code)).scalars().all()
    orgs = {o.id: o for o in ctx.db.execute(select(OrgUnit)).scalars()}
    return {
        "project": _project_dict(ctx, p),
        "items": [
            {
                "id": str(i.id), "parent_id": str(i.parent_id) if i.parent_id else None, "code": i.code, "name": i.name, "part_number": i.part_number,
                "level": {"code": i.level.code, "name": i.level.name, "no": i.level.level_no, "color": i.level.color, "icon": i.level.icon},
                "lifecycle_phase": i.lifecycle_phase, "status": i.status, "lead_org": org_brief(orgs.get(i.lead_org_unit_id)),
                "rollup": roll.get(str(i.id), {"counts": {}, "total": 0, "released": 0, "progress": 0}),
            }
            for i in items
        ],
    }


class ItemIn(BaseModel):
    parent_id: uuid.UUID | None = None
    level_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=2, max_length=200)
    part_number: str | None = None
    description: str | None = None
    domain_id: uuid.UUID | None = None
    lead_org_unit_id: uuid.UUID | None = None
    technical_owner_id: uuid.UUID | None = None
    lifecycle_phase: str = "CONCEPT"
    contributor_org_ids: list[uuid.UUID] = Field(default_factory=list)


def _item_scope_check(ctx: Ctx, p: Project, parent: EngineeringItem | None):
    if not ctx.p.has("item.manage", project_id=p.id, item_path=parent.path if parent else None):
        ctx.p.require("item.manage", project_id=p.id)


@router.post("/projects/{pid}/items")
def create_item(pid: uuid.UUID, body: ItemIn, ctx: Ctx = Depends(get_ctx)):
    p = get_or_404(ctx.db, Project, pid, "Project")
    parent = ctx.db.get(EngineeringItem, body.parent_id) if body.parent_id else None
    _item_scope_check(ctx, p, parent)
    if ctx.db.execute(select(EngineeringItem.id).where(EngineeringItem.project_id == p.id, EngineeringItem.code == body.code)).first():
        raise Conflict(f"Item code {body.code} already exists in {p.code}.")
    if body.level_id:
        level = get_or_404(ctx.db, HierarchyLevel, body.level_id, "Level")
    else:  # smart default: next level below the parent
        want = (parent.level.level_no + 1) if parent else 1
        level = ctx.db.execute(select(HierarchyLevel).where(HierarchyLevel.project_id == p.id, HierarchyLevel.level_no == want)).scalar_one_or_none()
        if not level:
            raise AppError("No further breakdown level is configured below this item.")
    if parent and level.level_no <= parent.level.level_no:
        raise AppError(f"A {level.name} cannot be placed under a {parent.level.name}.")
    it = EngineeringItem(project_id=p.id, parent_id=parent.id if parent else None, level_id=level.id, **body.model_dump(exclude={"parent_id", "level_id", "contributor_org_ids"}))
    it.id = uuid.uuid4()
    it.lead_org_unit_id = body.lead_org_unit_id or (parent.lead_org_unit_id if parent else p.lead_org_unit_id)
    it.domain_id = body.domain_id or (parent.domain_id if parent else None)
    it.path = (parent.path if parent else "/") + f"{it.id}/"
    ctx.db.add(it)
    ctx.db.flush()
    for oid in set(body.contributor_org_ids):
        ctx.db.add(EngineeringItemOrg(item_id=it.id, org_unit_id=oid, role="CONTRIBUTOR"))
    ctx.audit("item.create", "engineering_item", it.id, f"{level.name} {it.code} — {it.name} added to {p.code}")
    ctx.db.commit()
    return {"id": str(it.id)}


@router.put("/items/{iid}")
def update_item(iid: uuid.UUID, body: ItemIn, ctx: Ctx = Depends(get_ctx)):
    it = get_or_404(ctx.db, EngineeringItem, iid, "Item")
    p = ctx.db.get(Project, it.project_id)
    ctx.p.require("item.manage", project_id=p.id, item_path=it.path)
    for k in ("code", "name", "part_number", "description", "domain_id", "lead_org_unit_id", "technical_owner_id", "lifecycle_phase"):
        setattr(it, k, getattr(body, k))
    for row in ctx.db.execute(select(EngineeringItemOrg).where(EngineeringItemOrg.item_id == it.id)).scalars():
        ctx.db.delete(row)
    ctx.db.flush()
    for oid in set(body.contributor_org_ids):
        ctx.db.add(EngineeringItemOrg(item_id=it.id, org_unit_id=oid, role="CONTRIBUTOR"))
    it.version += 1
    ctx.audit("item.update", "engineering_item", it.id, f"{it.code} updated")
    ctx.db.commit()
    return {"ok": True}


@router.get("/items/{iid}")
def item_detail(iid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    it = get_or_404(ctx.db, EngineeringItem, iid, "Item")
    p = ctx.db.get(Project, it.project_id)
    _require_project_access(ctx, p)
    chain = []
    for x in [x for x in it.path.strip("/").split("/") if x]:
        a = ctx.db.get(EngineeringItem, uuid.UUID(x))
        if a:
            chain.append({"id": str(a.id), "code": a.code, "name": a.name, "level": a.level.name})
    contrib = ctx.db.execute(select(OrgUnit).join(EngineeringItemOrg, EngineeringItemOrg.org_unit_id == OrgUnit.id).where(EngineeringItemOrg.item_id == it.id)).scalars().all()
    dom = ctx.db.get(ProcessDomain, it.domain_id) if it.domain_id else None
    tasks = ctx.db.execute(select(WorkItem).where(WorkItem.item_id == it.id, WorkItem.status.not_in(closed_statuses(ctx.db))).order_by(WorkItem.due_date)).scalars().all()
    return {
        "id": str(it.id), "code": it.code, "name": it.name, "part_number": it.part_number, "description": it.description, "lifecycle_phase": it.lifecycle_phase, "status": it.status,
        "level": {"code": it.level.code, "name": it.level.name, "no": it.level.level_no}, "project": {"id": str(p.id), "code": p.code, "name": p.name},
        "domain": {"id": str(dom.id), "code": dom.code, "name": dom.name} if dom else None,
        "lead_org": org_brief(ctx.db.get(OrgUnit, it.lead_org_unit_id)) if it.lead_org_unit_id else None,
        "technical_owner": user_brief(ctx.db.get(User, it.technical_owner_id)) if it.technical_owner_id else None,
        "contributors": [org_brief(o) for o in contrib], "breadcrumb": chain,
        "open_tasks": [{"id": str(t.id), "key": t.key, "title": t.title, "status": t.status, "due_date": iso(t.due_date), "assignee": user_brief(ctx.db.get(User, t.assignee_id)) if t.assignee_id else None} for t in tasks],
        "can_manage": ctx.p.has("item.manage", project_id=p.id, item_path=it.path),
        "updated_at": iso(it.updated_at),
    }
