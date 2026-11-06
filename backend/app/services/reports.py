"""Phase reports (architecture §17.5): each report is a list of titled tables, rendered as PDF (A4 landscape, reportlab)
or CSV (formula-safe). The data comes from the same records and rules the screens use, filtered to what the viewer
may see.

Reports: documents, requirements (with RTM), design, development, testing (test summary), defects, deployment,
traceability (requirement → document, design, task, code, test, defect, deployment).
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.models import Document, DocumentRevision, DocumentType, EngineeringItem, HierarchyLevel, Project, Requirement, RequirementWorkItem, User, WorkflowInstance, WorkItem
from app.models.artifacts import ArtifactLink
from app.models.deployment import Deployment, DeploymentAttempt, DeploymentEnvironment
from app.models.design import DesignRecord, DesignType
from app.models.scm import ScmLink
from app.models.testing import Defect, TestCase, TestPlan, TestRun, TestRunCase
from app.services import requirements as reqsvc
from app.services import testing as testsvc
from app.services.authz import Principal, document_visibility_clause

KINDS = {
    "documents": "Document register", "requirements": "Requirements and traceability matrix", "design": "Design register", "development": "Development report",
    "testing": "Test summary report", "defects": "Defect report", "deployment": "Deployment report", "traceability": "End-to-end traceability report",
}


class Table:
    def __init__(self, title: str, columns: list[str], rows: list[list], note: str | None = None, widths: list[float] | None = None):
        self.title, self.columns, self.rows, self.note, self.widths = title, columns, rows, note, widths


def _names(db: Session, ids) -> dict:
    ids = {i for i in ids if i}
    return {u.id: u.full_name for u in db.execute(select(User).where(User.id.in_(ids))).scalars()} if ids else {}


def _item_label(db: Session, item_id) -> str:
    it = db.get(EngineeringItem, item_id) if item_id else None
    if not it:
        return ""
    lv = db.get(HierarchyLevel, it.level_id) if it.level_id else None
    return f"{lv.name if lv else ''} {it.code}".strip()


def _d(v) -> str:
    if not v:
        return ""
    return v.strftime("%Y-%m-%d") if hasattr(v, "strftime") else str(v)[:10]


# ------------------------------------------------------------------ builders
def documents(db: Session, p: Principal, project: Project) -> list[Table]:
    q = select(Document).where(Document.project_id == project.id)
    vis = document_visibility_clause(db, p)
    if vis is not None:
        q = q.where(vis)
    docs = db.execute(q.order_by(Document.number)).scalars().all()
    types = {t.id: t for t in db.execute(select(DocumentType)).scalars()}
    owners = _names(db, {d.owner_id for d in docs})
    rows, by_status = [], defaultdict(int)
    for d in docs:
        rev = db.get(DocumentRevision, d.current_revision_id) if d.current_revision_id else None
        cycles = len(db.execute(select(WorkflowInstance.id).where(WorkflowInstance.document_id == d.id)).all())
        by_status[d.status] += 1
        rows.append([d.number, d.title, types[d.type_id].code if d.type_id in types else "", _item_label(db, d.item_id), rev.label if rev else "", d.status, cycles, owners.get(d.owner_id, ""), d.classification])
    return [Table("Summary by status", ["Status", "Documents"], [[k, v] for k, v in sorted(by_status.items())]),
            Table("Documents", ["Number", "Title", "Type", "Level / item", "Rev", "Status", "Review cycles", "Owner", "Classification"], rows)]


def requirements(db: Session, p: Principal, project: Project) -> list[Table]:
    data = reqsvc.rtm(db, project.id)
    s = data["summary"]
    reqs = {r.id: r for r in db.execute(select(Requirement).where(Requirement.project_id == project.id)).scalars()}
    summary = [["Requirements", s["total"]], ["With design", s.get("with_designs", 0)], ["With tasks", s["with_tasks"]], ["With test cases", s.get("with_tests", 0)], ["Verified (all tests passed)", s.get("verified", 0)],
               ["Baselined", s["baselined"]], ["Not traced at all", s["untraced"]], ["With open defects", s.get("open_defects", 0)]]
    by_status = defaultdict(int)
    for r in reqs.values():
        by_status[r.status] += 1
    rows = []
    for x in data["rows"]:
        r = reqs.get(uuid.UUID(x["id"]))
        rows.append([x["key"], x["title"], x["status"], x["revision"], x["priority"], _item_label(db, r.item_id) if r else "", " ".join(d["number"] for d in x["documents"]),
                     " ".join(d["key"] for d in x["designs"]), " ".join(t["key"] for t in x["tasks"]), " ".join(f"{t['key']}:{t['last_result'] or '-'}" for t in x["tests"]),
                     " ".join(f"{d['key']}:{d['status']}" for d in x["defects"]), " ".join(str(b) for b in x["baselines"])])
    return [Table("Coverage", ["Measure", "Count"], summary), Table("By status", ["Status", "Requirements"], [[k, v] for k, v in sorted(by_status.items())]),
            Table("Requirement traceability matrix", ["ID", "Title", "Status", "Rev", "Priority", "Level / item", "Documents", "Designs", "Tasks", "Tests (last result)", "Defects", "Baselines"], rows)]


def design(db: Session, p: Principal, project: Project) -> list[Table]:
    rows_ = db.execute(select(DesignRecord).where(DesignRecord.project_id == project.id).order_by(DesignRecord.key)).scalars().all()
    types = {t.id: t for t in db.execute(select(DesignType)).scalars()}
    owners = _names(db, {d.owner_id for d in rows_})
    rows = []
    for d in rows_:
        links = db.execute(select(ArtifactLink).where(ArtifactLink.from_type == "DESIGN", ArtifactLink.from_id == d.id, ArtifactLink.to_type == "REQUIREMENT")).scalars().all()
        keys = [reqsvc_key(db, x.to_id) for x in links]
        code = len(db.execute(select(ScmLink.id).where(ScmLink.artifact_type == "DESIGN", ScmLink.artifact_id == d.id)).all())
        rows.append([d.key, d.title, types[d.type_id].name if d.type_id in types else "", _item_label(db, d.item_id), d.status, d.current_version, d.baselined_version or "", " ".join(keys), code, owners.get(d.owner_id, "")])
    return [Table("Design records", ["ID", "Title", "Type", "Level / item", "Status", "Version", "Baselined", "Satisfies", "Code links", "Owner"], rows)]


def reqsvc_key(db: Session, rid) -> str:
    r = db.get(Requirement, rid)
    return r.key if r else ""


def development(db: Session, p: Principal, project: Project) -> list[Table]:
    from app.services.planning import task_visibility_clause

    q = select(WorkItem).where(WorkItem.project_id == project.id, WorkItem.kind == "DEVELOPMENT")
    vis = task_visibility_clause(db, p)
    if vis is not None:
        q = q.where(vis)
    tasks = db.execute(q.order_by(WorkItem.key)).scalars().all()
    who = _names(db, {t.assignee_id for t in tasks})
    rows, by_status = [], defaultdict(int)
    for t in tasks:
        by_status[t.status] += 1
        links = db.execute(select(ScmLink).where(ScmLink.work_item_id == t.id)).scalars().all()
        reqs = [reqsvc_key(db, x.requirement_id) for x in db.execute(select(RequirementWorkItem).where(RequirementWorkItem.work_item_id == t.id)).scalars()]
        mrs = [f"!{x.ref}:{x.state or '-'}" for x in links if x.kind == "MERGE_REQUEST"]
        rows.append([t.key, t.title, t.status, who.get(t.assignee_id, ""), f"{t.progress:.0f}%", " ".join(reqs), " ".join(x.ref for x in links if x.kind == "BRANCH"), " ".join(mrs),
                     sum(1 for x in links if x.kind == "COMMIT"), _d(t.due_date)])
    return [Table("Development tasks by status", ["Status", "Tasks"], [[k, v] for k, v in sorted(by_status.items())]),
            Table("Development tasks", ["Task", "Title", "Status", "Assignee", "Progress", "Requirements", "Branches", "Merge requests", "Commits", "Due"], rows)]


def testing(db: Session, p: Principal, project: Project) -> list[Table]:
    cases = db.execute(select(TestCase).where(TestCase.project_id == project.id).order_by(TestCase.key)).scalars().all()
    last = testsvc.last_results_for_cases(db, [c.id for c in cases])
    case_rows = []
    for c in cases:
        verifies = [reqsvc_key(db, x.to_id) for x in db.execute(select(ArtifactLink).where(ArtifactLink.from_type == "TEST_CASE", ArtifactLink.from_id == c.id, ArtifactLink.to_type == "REQUIREMENT")).scalars()]
        case_rows.append([c.key, c.title, c.test_type, c.status, c.revision, " ".join(verifies), (last.get(c.id) or {}).get("result", "not run"), c.automation_id or ""])
    run_rows, exit_rows = [], []
    plans = {pl.id: pl for pl in db.execute(select(TestPlan).where(TestPlan.project_id == project.id)).scalars()}
    for run in db.execute(select(TestRun).where(TestRun.project_id == project.id).order_by(TestRun.key)).scalars():
        e = testsvc.evaluate_exit(db, run)
        c = e["counts"]
        run_rows.append([run.key, run.title, plans[run.plan_id].key if run.plan_id in plans else "", run.build_version or "", run.environment or "", run.status, e["total"], c.get("PASSED", 0), c.get("FAILED", 0),
                         c.get("BLOCKED", 0), c.get("NOT_RUN", 0) + c.get("RETEST", 0), f"{e['pass_rate']}%", _d(run.closed_at)])
        for chk in e["checks"]:
            exit_rows.append([run.key, chk["label"], "met" if chk["ok"] else "NOT MET", chk["detail"]])
    return [Table("Test runs", ["Run", "Title", "Plan", "Build", "Environment", "Status", "Cases", "Passed", "Failed", "Blocked", "Open", "Pass rate", "Closed"], run_rows),
            Table("Exit criteria", ["Run", "Criterion", "Result", "Detail"], exit_rows),
            Table("Test cases", ["Case", "Title", "Type", "Status", "Rev", "Verifies", "Last result", "Automation id"], case_rows)]


def defects(db: Session, p: Principal, project: Project) -> list[Table]:
    rows_ = db.execute(select(Defect).where(Defect.project_id == project.id).order_by(Defect.key)).scalars().all()
    who = _names(db, {d.assignee_id for d in rows_} | {d.reporter_id for d in rows_})
    matrix = defaultdict(lambda: defaultdict(int))
    today = date.today()
    rows = []
    for d in rows_:
        matrix[d.severity][d.status] += 1
        age = (today - d.created_at.date()).days if d.created_at else ""
        rows.append([d.key, d.title, d.severity, d.priority, d.status, who.get(d.assignee_id, ""), who.get(d.reporter_id, ""), d.found_in_build or "", d.fixed_in_build or "", age])
    statuses = [s["code"] for s in testsvc.DEFECT_STATES]
    sev_rows = [[sev] + [matrix[sev][s] for s in statuses] for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW") if matrix[sev]]
    return [Table("Defects by severity and status", ["Severity", *statuses], sev_rows),
            Table("Defects", ["Defect", "Title", "Severity", "Priority", "Status", "Assignee", "Reporter", "Found in", "Fixed in", "Age (days)"], rows)]


def deployment(db: Session, p: Principal, project: Project) -> list[Table]:
    from app.services.deployment import current_on

    envs = db.execute(select(DeploymentEnvironment).where(DeploymentEnvironment.project_id == project.id).order_by(DeploymentEnvironment.sort_order)).scalars().all()
    env_rows = []
    for e in envs:
        cur = current_on(db, e.id)
        env_rows.append([e.code, e.name, "yes" if e.active else "no", (e.config_status if json.loads(e.config or "{}").get("require_config_approval", True) else "not required"), cur.version_label if cur else "", cur.key if cur else "", _d(cur.deployed_at) if cur else ""])
    by_env = {e.id: e.code for e in envs}
    rows = []
    for d in db.execute(select(Deployment).where(Deployment.project_id == project.id).order_by(Deployment.created_at)).scalars():
        attempts = db.execute(select(DeploymentAttempt).where(DeploymentAttempt.deployment_id == d.id).order_by(DeploymentAttempt.attempt_no)).scalars().all()
        run = db.get(TestRun, d.test_run_id) if d.test_run_id else None
        rows.append([d.key, by_env.get(d.environment_id, ""), d.version_label, d.git_ref or "", (d.commit_sha or "")[:12], d.status, len(attempts), " ".join(f"{a.attempt_no}:{a.status}" for a in attempts), run.key if run else "", _d(d.deployed_at),
                     "rollback" if d.rollback_of_id else ""])
    return [Table("What runs where", ["Environment", "Name", "Active", "Configuration", "Current version", "Deployment", "Since"], env_rows),
            Table("Deployments", ["Deployment", "Env", "Version", "Tag/branch", "Commit", "Status", "Attempts", "Attempt results", "Test run", "Deployed", "Note"], rows)]


def traceability(db: Session, p: Principal, project: Project) -> list[Table]:
    data = reqsvc.rtm(db, project.id)
    deps = db.execute(select(Deployment).where(Deployment.project_id == project.id, Deployment.status.in_(["DEPLOYED", "ROLLED_BACK"]))).scalars().all()
    envs = {e.id: e.code for e in db.execute(select(DeploymentEnvironment).where(DeploymentEnvironment.project_id == project.id)).scalars()}
    dep_tasks = defaultdict(set)
    dep_runs = defaultdict(set)
    for d in deps:
        for x in db.execute(select(ArtifactLink.to_id).where(ArtifactLink.from_type == "DEPLOYMENT", ArtifactLink.from_id == d.id, ArtifactLink.to_type == "TASK")).scalars():
            dep_tasks[x].add(f"{envs.get(d.environment_id, '')} {d.version_label}")
        if d.test_run_id:
            for cid in db.execute(select(TestRunCase.case_id).where(TestRunCase.run_id == d.test_run_id)).scalars():
                dep_runs[cid].add(f"{envs.get(d.environment_id, '')} {d.version_label}")
    rows = []
    for x in data["rows"]:
        released = set()
        for t in x["tasks"]:
            released |= dep_tasks.get(uuid.UUID(t["id"]), set())
        for t in x["tests"]:
            released |= dep_runs.get(uuid.UUID(t["id"]), set())
        gaps = [g for g, ok in (("design", x["designs"]), ("implementation", x["tasks"]), ("test", x["tests"])) if not ok]
        rows.append([x["key"], x["status"], " ".join(d["number"] for d in x["documents"]), " ".join(d["key"] for d in x["designs"]), " ".join(t["key"] for t in x["tasks"]),
                     " ".join(f"{c['ref']}:{c['state'] or '-'}" for c in x["code"]), " ".join(f"{t['key']}:{t['last_result'] or '-'}" for t in x["tests"]),
                     " ".join(f"{d['key']}:{d['status']}" for d in x["defects"]), ", ".join(sorted(released)), ", ".join(gaps) or "complete"])
    return [Table("Requirement → document → design → development → code → test → defect → deployment", ["Requirement", "Status", "Documents", "Designs", "Tasks", "Merge requests", "Tests (last)", "Defects", "Deployed in", "Gaps"], rows,
                  note="A requirement is complete when it has a design, an implementing task and a test case; 'Deployed in' lists environments that received a version containing its tasks or tested by a run of its test cases.")]


BUILDERS = {"documents": documents, "requirements": requirements, "design": design, "development": development, "testing": testing, "defects": defects, "deployment": deployment, "traceability": traceability}


# ------------------------------------------------------------------ rendering
def _safe(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def to_csv(tables: list[Table]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    for t in tables:
        w.writerow([t.title])
        w.writerow(t.columns)
        for r in t.rows:
            w.writerow([_safe(x) for x in r])
        w.writerow([])
    return "﻿" + buf.getvalue()


def to_pdf(title: str, project: Project, user: User, tables: list[Table]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

    ss = getSampleStyleSheet()
    cell = ss["BodyText"].clone("cell", fontSize=7, leading=8.5)
    head = ss["BodyText"].clone("head", fontSize=7, leading=8.5, fontName="Helvetica-Bold")
    buf = io.BytesIO()
    stamp = utcnow().strftime("%Y-%m-%d %H:%M UTC")

    def footer(c, d):
        c.saveState()
        c.setFont("Helvetica", 7)
        c.drawString(12 * mm, 8 * mm, f"ADA-ELM · {project.code} · {title} · generated {stamp} for {user.full_name}")
        c.drawRightString(285 * mm, 8 * mm, f"Page {d.page}")
        c.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=14 * mm, title=f"{project.code} {title}")
    esc = lambda s: str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    story = [Paragraph(f"{esc(project.code)} — {esc(title)}", ss["Title"]), Paragraph(f"{esc(project.name)}. Generated {stamp}. Contains only records the requester may see.", ss["Italic"]), Spacer(1, 6)]
    width = 273 * mm
    for t in tables:
        story.append(Paragraph(esc(t.title), ss["Heading3"]))
        if t.note:
            story.append(Paragraph(esc(t.note), ss["Italic"]))
        if not t.rows:
            story.append(Paragraph("No records.", ss["BodyText"]))
            continue
        data = [[Paragraph(esc(c), head) for c in t.columns]] + [[Paragraph(esc(v), cell) for v in r] for r in t.rows]
        n = len(t.columns)
        lt = LongTable(data, colWidths=[width / n] * n, repeatRows=1)
        lt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story += [lt, Spacer(1, 8)]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
