"""Traceability API: the end-to-end trace graph, activities derived from a requirement, and GitLab links for design
records, test cases and defects (architecture §19, §12.3)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.deps import Ctx, get_ctx, get_or_404
from app.core.errors import AppError, Forbidden
from app.models import Requirement, RequirementWorkItem
from app.models.design import DesignRecord, DesignType
from app.models.scm import ScmRepository
from app.models.testing import Defect, TestCase
from app.services import artifacts as art
from app.services import scm as scmsvc
from app.services import trace as tr
from app.services.planning import require_view_project
from app.services.requirements import add_event, can_view as can_view_requirement

router = APIRouter(tags=["traceability"])
ART_MODELS = {"DESIGN": (DesignRecord, "design.edit"), "TEST_CASE": (TestCase, "test.edit"), "DEFECT": (Defect, "defect.manage")}


@router.get("/trace")
def trace(type: str = Query(..., pattern=r"^(DOCUMENT|REQUIREMENT|DESIGN|TASK|TEST_CASE|TEST_RUN|DEFECT|DEPLOYMENT)$"), id: uuid.UUID = Query(...), depth: int = Query(4, ge=1, le=8), ctx: Ctx = Depends(get_ctx)):
    """Everything linked to one record, up to `depth` steps, as nodes and edges (for the trace view and reports)."""
    return tr.Tracer(ctx.db, ctx.p).walk(type, id, depth=depth)


# ------------------------------------------------------------------ activities from a requirement
class DeriveIn(BaseModel):
    kind: str = Field(pattern=r"^(DESIGN|TASK|DEVELOPMENT|TEST_CASE)$")
    title: str | None = Field(default=None, min_length=3, max_length=300)
    design_type_id: uuid.UUID | None = None
    assignee_id: uuid.UUID | None = None


@router.post("/requirements/{rid}/derive")
def derive(rid: uuid.UUID, body: DeriveIn, ctx: Ctx = Depends(get_ctx)):
    """Start the next activity from a requirement: a design record (satisfies), a task or development task
    (implements) or a test case (verifies). The new record inherits project and breakdown item and is linked at once."""
    r = get_or_404(ctx.db, Requirement, rid, "Requirement")
    if not can_view_requirement(ctx.db, ctx.p, r):
        raise Forbidden("You do not have access to this requirement.")
    title = body.title or f"{r.key}: {r.title}"[:300]
    if body.kind == "DESIGN":
        from app.api.v1.design import DesignIn, create_design

        tid = body.design_type_id or ctx.db.execute(select(DesignType.id).where(DesignType.active.is_(True), DesignType.code == "ARCH")).scalar() or ctx.db.execute(select(DesignType.id).where(DesignType.active.is_(True))).scalar()
        if not tid:
            raise AppError("No design type is configured.")
        out = create_design(r.project_id, DesignIn(type_id=tid, title=title, description=r.description, item_id=r.item_id, org_unit_id=r.org_unit_id, owner_id=body.assignee_id), ctx)
        art.add_link(ctx.db, from_type="DESIGN", from_id=uuid.UUID(out["id"]), to_type="REQUIREMENT", to_id=r.id, link_type="satisfies", section=None, actor=ctx.user.id)
        new = {"type": "DESIGN", "id": out["id"], "key": out["key"], "route": f"/design/{r.project_id}?open={out['id']}"}
    elif body.kind in ("TASK", "DEVELOPMENT"):
        from app.api.v1.tasks import WorkItemIn, create_work_item

        out = create_work_item(WorkItemIn(title=title, description=r.description, kind=body.kind, project_id=r.project_id, item_id=r.item_id, org_unit_id=r.org_unit_id, assignee_id=body.assignee_id or ctx.user.id), ctx)
        ctx.db.add(RequirementWorkItem(requirement_id=r.id, work_item_id=uuid.UUID(out["id"]), link_type="implements", created_by_id=ctx.user.id))
        new = {"type": "TASK", "id": out["id"], "key": out["key"], "route": f"/tasks?open={out['id']}"}
    else:
        from app.api.v1.testing import CaseIn, create_case

        out = create_case(r.project_id, CaseIn(title=title, objective=f"Verify {r.key}: {r.title}"[:2000], expected_result=r.acceptance_criteria, item_id=r.item_id, owner_id=body.assignee_id,
                                                 steps=[{"action": "Describe the first step", "expected": r.acceptance_criteria or "Expected result"}]), ctx)
        art.add_link(ctx.db, from_type="TEST_CASE", from_id=uuid.UUID(out["id"]), to_type="REQUIREMENT", to_id=r.id, link_type="verifies", section=None, actor=ctx.user.id)
        new = {"type": "TEST_CASE", "id": out["id"], "key": out["key"], "route": f"/testing/{r.project_id}?case={out['id']}"}
    add_event(ctx.db, r, "DERIVED", ctx.user.id, to=new["key"], comment=f"{body.kind.lower().replace('_', ' ')} created from this requirement")
    ctx.audit("requirement.derive", "requirement", r.id, f"{r.key}: {new['key']} ({body.kind.lower()}) created and linked", new)
    ctx.db.commit()
    return new


# ------------------------------------------------------------------ GitLab links on design records, test cases, defects
def _artifact(ctx: Ctx, a_type: str, aid: uuid.UUID):
    if a_type not in ART_MODELS:
        raise AppError("Unknown record type.")
    o = get_or_404(ctx.db, ART_MODELS[a_type][0], aid, "Record")
    require_view_project(ctx.db, ctx.p, o.project_id)
    return o


@router.get("/artifacts/{a_type}/{aid}/scm")
def artifact_scm(a_type: str, aid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    o = _artifact(ctx, a_type, aid)
    return {"key": o.key, "links": scmsvc.artifact_links(ctx.db, a_type, o.id), "repositories": [scmsvc.repo_dict(r) for r in scmsvc.project_repositories(ctx.db, o.project_id)],
            "can_edit": ctx.p.has(ART_MODELS[a_type][1], project_id=o.project_id),
            "hint": f"Put {o.key} in a commit message, branch name or merge request title in a registered repository and ELM links it."}


class ArtifactScmIn(BaseModel):
    repository_id: uuid.UUID
    kind: str = Field(pattern=r"^(BRANCH|COMMIT|MERGE_REQUEST)$")
    ref: str = Field(min_length=1, max_length=255)
    title: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, max_length=500, pattern=r"^https?://")


@router.post("/artifacts/{a_type}/{aid}/scm")
def add_artifact_scm(a_type: str, aid: uuid.UUID, body: ArtifactScmIn, ctx: Ctx = Depends(get_ctx)):
    """Manual reference: link a commit, branch or merge request (for example a test script or a model file) by hand."""
    o = _artifact(ctx, a_type, aid)
    if not ctx.p.has(ART_MODELS[a_type][1], project_id=o.project_id):
        raise Forbidden("You cannot change this record.", details={"permission": ART_MODELS[a_type][1]})
    repo = get_or_404(ctx.db, ScmRepository, body.repository_id, "Repository")
    if repo.project_id != o.project_id:
        raise AppError("That repository is not registered for this project.", code="REPO_NOT_ALLOWED")
    if body.kind == "COMMIT" and not all(c in "0123456789abcdef" for c in body.ref.lower()):
        raise AppError("A commit reference is its SHA in hexadecimal.")
    if body.kind == "MERGE_REQUEST" and not body.ref.isdigit():
        raise AppError("A merge request reference is its number (iid).")
    _, created = scmsvc.upsert_artifact_link(ctx.db, a_type, o, repo, body.kind, body.ref, origin="MANUAL", actor_id=ctx.user.id, title=body.title, url=body.url)
    if not created:
        raise AppError("That reference is already linked.", code="DUPLICATE")
    ctx.audit("scm.link.manual", a_type.lower(), o.id, f"{o.key}: {body.kind.lower()} {body.ref} linked by hand", {"repository": repo.path})
    ctx.db.commit()
    return {"links": scmsvc.artifact_links(ctx.db, a_type, o.id)}


# ------------------------------------------------------------------ phase reports
@router.get("/report-kinds")
def report_kinds(ctx: Ctx = Depends(get_ctx)):
    from app.services import reports

    return [{"kind": k, "title": v} for k, v in reports.KINDS.items()]


@router.get("/projects/{pid}/reports/{kind}.{fmt}")
def project_report(pid: uuid.UUID, kind: str, fmt: str, ctx: Ctx = Depends(get_ctx)):
    """Phase report as PDF or CSV. Only records the requester may see are included."""
    from fastapi.responses import Response

    from app.models import Project
    from app.services import reports

    if kind not in reports.KINDS or fmt not in ("pdf", "csv"):
        raise AppError("Unknown report or format.", status_code=404, code="NOT_FOUND")
    project = get_or_404(ctx.db, Project, pid, "Project")
    require_view_project(ctx.db, ctx.p, pid)
    tables = reports.BUILDERS[kind](ctx.db, ctx.p, project)
    ctx.audit("report.generate", "project", pid, f"{project.code}: {reports.KINDS[kind]} ({fmt.upper()}) generated", {"kind": kind, "rows": sum(len(t.rows) for t in tables)})
    ctx.db.commit()
    name = f"{project.code}-{kind}-{__import__('datetime').date.today():%Y%m%d}.{fmt}"
    if fmt == "csv":
        return Response(reports.to_csv(tables), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})
    return Response(reports.to_pdf(reports.KINDS[kind], project, ctx.user, tables), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})
