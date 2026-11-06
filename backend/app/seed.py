"""Development / demonstration seed data. Fictional people and example master data only.
Production organization, employees and roles must be imported from ADA-authorized sources (TBD by ADA).

Run:  python -m app.seed
"""
from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal, utcnow
from app.core.security import hash_password
from app.models import (
    DocumentType,
    EngineeringItem,
    HierarchyLevel,
    OrgUnit,
    ProcessDomain,
    Project,
    ProjectMember,
    ProjectOrgAssignment,
    Role,
    RoleAssignment,
    RolePermission,
    SystemSetting,
    User,
    UserOrgAssignment,
    WorkflowBinding,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowTask,
    WorkflowVersion,
    Milestone,
    Requirement,
    RequirementBaseline,
    RequirementLink,
    RequirementReview,
    RequirementSource,
    RequirementWorkItem,
    PlanActivity,
    PlanPhase,
    ProjectPlan,
    TaskChecklistItem,
    TaskDependency,
    TaskParticipant,
    WorkItem,
    WorkItemEvent,
    WorkPackage,
    WorkPackageOrg,
)
from app.services import documents as docsvc
from app.services import release as relsvc
from app.services import workflow_engine as wf
from app.services.workflow_spec import WorkflowSpec, validate_spec

ROLES = {
    "HD_OVERSIGHT": ("Head Directorate Oversight", ["release.view_all", "project.view"]),
    "PGD": ("PGD (label configurable)", ["deploy.approve", "design.edit", "design.baseline", "test.approve", "defect.manage", "scm.manage", "project.view", "project.manage", "item.manage", "plan.manage", "task.manage", "req.edit", "req.baseline", "doc.view", "doc.download", "release.view_all", "doc.share"]),
    "TD": ("TD (label configurable)", ["deploy.configure", "deploy.approve", "design.edit", "design.baseline", "test.approve", "defect.manage", "scm.manage", "project.view", "item.manage", "plan.manage", "task.manage", "req.edit", "req.baseline", "doc.view", "doc.download", "doc.share"]),
    "DIR_HEAD": ("Directorate Head", ["design.edit", "defect.manage", "doc.view", "doc.download", "doc.share", "plan.manage", "task.manage", "req.edit", "project.view"]),
    "DEPT_HEAD": ("Department Head", ["doc.view", "doc.download", "doc.share", "task.manage"]),
    "PE": ("Project Engineer", ["deploy.configure", "deploy.request", "deploy.execute", "design.edit", "design.baseline", "test.edit", "test.approve", "defect.manage", "doc.view", "doc.create", "doc.edit", "doc.download", "doc.share", "item.manage", "plan.manage", "task.manage", "req.edit", "req.baseline", "scm.manage", "project.view"]),
    "TEAM_MEMBER": ("Team Member / Engineer", ["deploy.request", "design.edit", "test.edit", "doc.view", "doc.create", "doc.edit", "doc.download", "req.edit"]),
    "CHECKER": ("Checked By (Checker)", ["doc.view", "doc.download"]),
    "REVIEWER": ("Reviewed By (Reviewer)", ["doc.view", "doc.download"]),
    "APPROVER": ("Approved By (Approver)", ["doc.view", "doc.download"]),
    "RELEASE_AUTH": ("Release / Configuration Authority", ["deploy.approve", "deploy.execute", "design.baseline", "doc.view", "doc.download", "doc.release", "doc.withdraw", "req.baseline"]),
    "PROCESS_ADMIN": ("Process / Workflow Administrator", ["workflow.configure", "admin.config", "project.view"]),
    "QA_AUDITOR": ("Quality / Audit", ["deploy.approve", "test.edit", "test.approve", "defect.manage", "audit.view", "doc.view", "doc.download", "project.view"]),
}

ENG_4STEP = {
    "stages": [
        {"key": "prepare", "name": "Prepared By", "type": "prepare", "assignee": {"kind": "initiator"}, "weight": 10, "ui": {"x": 0, "y": 0}},
        {"key": "check", "name": "Checked By", "type": "review", "assignee": {"kind": "pick", "role_code": "CHECKER", "min": 1, "max": 2}, "mode": "all", "sla_hours": 48, "sod_exclude": ["prepare"],
         "checklist": ["Template, numbering and classification are correct", "Technical content complete against scope", "Applicable / reference documents verified"], "weight": 20,
         "instructions": "Completeness and technical correctness check."},
        {"key": "review", "name": "Reviewed By", "type": "review", "assignee": {"kind": "pick", "role_code": "REVIEWER", "min": 1}, "mode": "all", "sla_hours": 72, "sod_exclude": ["prepare", "check"], "weight": 25,
         "instructions": "Independent discipline / cross-directorate review."},
        {"key": "approve", "name": "Approved By", "type": "approval", "assignee": {"kind": "pick", "role_code": "APPROVER", "min": 1, "max": 1}, "mode": "any", "sla_hours": 72, "sod_exclude": ["prepare", "check", "review"], "weight": 25,
         "instructions": "Formal approval for release eligibility."},
        {"key": "sign", "name": "Digital Signatures", "type": "signature", "signers_from": ["prepare", "check", "review", "approve"], "sla_hours": 48, "weight": 10},
    ],
    "on_complete": "approve",
}
NONENG = {
    "stages": [
        {"key": "prepare", "name": "Initiated By", "type": "prepare", "assignee": {"kind": "initiator"}, "weight": 20},
        {"key": "approve", "name": "Approved By", "type": "approval", "assignee": {"kind": "pick", "role_code": "APPROVER", "min": 1, "max": 1}, "mode": "any", "sla_hours": 48, "sod_exclude": ["prepare"], "weight": 80},
    ],
    "on_complete": "release",
    "signature_required": False,
}
HD_PROG = {
    "stages": [
        {"key": "prepare", "name": "Prepared By", "type": "prepare", "assignee": {"kind": "initiator"}, "weight": 10},
        {"key": "concurrence", "name": "Technical Concurrence (parallel)", "type": "review", "assignee": {"kind": "pick", "role_code": "REVIEWER", "min": 2}, "mode": "quorum", "quorum": 2, "sla_hours": 96, "sod_exclude": ["prepare"], "weight": 40,
         "instructions": "Each contributing directorate gives technical concurrence."},
        {"key": "approve", "name": "Programme Approval", "type": "approval", "assignee": {"kind": "role", "role_code": "PGD"}, "mode": "any", "sla_hours": 96, "sod_exclude": ["prepare", "concurrence"], "weight": 40},
        {"key": "sign", "name": "Digital Signature", "type": "signature", "signers_from": ["approve"], "weight": 10},
    ],
}


DOC_TYPES = [
    ("SPEC", "Specification (System / Unit)", "ENGINEERING", "{PROJECT}-{ITEM}-SPEC-{SEQ:3}", "docx", True, "SYSTEM,SUBSYSTEM,UNIT,MODULE,COMPONENT", "#1677ff", "docx,pdf"),
    ("SRS", "Software Requirements Specification", "ENGINEERING", "{PROJECT}-{ITEM}-SRS-{SEQ:3}", "docx", True, None, "#13c2c2", "docx,pdf"),
    ("ICD", "Interface Control Document", "ENGINEERING", "{PROJECT}-{ITEM}-ICD-{SEQ:3}", "docx", True, None, "#722ed1", "docx,xlsx,pdf"),
    ("DDD", "Design Description Document", "ENGINEERING", "{PROJECT}-{ITEM}-DDD-{SEQ:3}", "docx", True, None, "#2f54eb", "docx,pdf,drawio"),
    ("ATP", "Acceptance Test Procedure", "ENGINEERING", "{PROJECT}-{ITEM}-ATP-{SEQ:3}", "docx", True, "UNIT,MODULE,COMPONENT", "#fa8c16", "docx,xlsx,pdf"),
    ("TR", "Test / Qualification Report", "ENGINEERING", "{PROJECT}-{ITEM}-TR-{SEQ:3}", "docx", True, None, "#faad14", "docx,xlsx,pdf"),
    ("DRG", "Engineering Drawing", "ENGINEERING", "{PROJECT}-{ITEM}-DRG-{SEQ:4}", None, True, None, "#595959", "pdf,png,jpg"),
    ("CR", "Engineering Change Request", "ENGINEERING", "{PROJECT}-ECR-{YEAR}-{SEQ:4}", "docx", True, None, "#f5222d", "docx,pdf"),
    ("PMP", "Programme Management Plan", "MANAGEMENT", "{PROJECT}-PMP-{SEQ:2}", "docx", True, "PRODUCT", "#eb2f96", "docx,pdf"),
    ("MOM", "Minutes of Meeting", "NON_ENGINEERING", "{PROJECT}-MOM-{YEAR}-{SEQ:4}", "docx", False, None, "#8c8c8c", "docx,pdf"),
    ("ADMN", "Administrative Note / Office Order", "NON_ENGINEERING", "ADA-{ORG}-{YEAR}-{SEQ:4}", "docx", False, None, "#fa8c16", "docx,pdf"),
    ("PRQ", "Procurement Request", "NON_ENGINEERING", "ADA-{ORG}-PRQ-{YEAR}-{SEQ:4}", "xlsx", False, None, "#a0d911", "xlsx,docx,pdf"),
]

DOMAINS = [("HARDWARE", "Hardware / Engineering", True, "#2f54eb"), ("SOFTWARE", "Software (SDLC)", True, "#13c2c2"), ("SYSTEMS", "Systems Engineering", True, "#722ed1"),
           ("ADMIN", "Administration", False, "#fa8c16"), ("QUALITY", "Quality & Configuration", False, "#52c41a")]


# Shared phase template. A project that defines its own phases uses those instead, so non-software work is not forced onto SDLC labels.
PHASES = [("PLANNING", "Planning"), ("REQUIREMENTS", "Requirements"), ("DESIGN", "Design"), ("DEVELOPMENT", "Development"), ("TESTING", "Testing"), ("DEPLOYMENT", "Deployment / Release"), ("MAINTENANCE", "Maintenance")]


# Design artefact types (architecture §11.2). Examples only: ADA supplies the real list and approval rules.
DESIGN_TYPES = [
    ("ARCH", "Architecture diagram", "SOFTWARE", "drawio,svg,png,jpg,pdf", True, [{"key": "rationale", "label": "Design rationale", "type": "textarea"}, {"key": "level", "label": "Level", "type": "select", "options": ["Context", "Container", "Component"]}]),
    ("WORKFLOW", "Workflow / process diagram", "SOFTWARE", "drawio,svg,png,jpg,pdf", True, []),
    ("SEQUENCE", "Sequence diagram", "SOFTWARE", "drawio,svg,png,jpg,pdf", True, []),
    ("CLASS", "Class diagram", "SOFTWARE", "drawio,svg,png,jpg,pdf", True, []),
    ("ER", "Entity-relationship model", "SOFTWARE", "drawio,svg,png,jpg,pdf", True, []),
    ("INTERFACE", "Interface record", "SYSTEMS", "drawio,svg,png,pdf,xlsx,docx", True, [{"key": "interface_id", "label": "Interface ID", "type": "text", "required": True}, {"key": "protocol", "label": "Protocol / medium", "type": "text"}]),
    ("DRAWING", "Engineering drawing", "ENGINEERING", "pdf,png,jpg,svg", False, [{"key": "sheet", "label": "Sheet", "type": "text"}]),
    ("CALC", "Calculation / analysis", "ENGINEERING", "pdf,xlsx,docx", False, [{"key": "method", "label": "Method", "type": "textarea"}]),
    ("MODEL", "Engineering model (external tool)", "ENGINEERING", "zip,pdf,png", False, [{"key": "tool", "label": "Tool and version", "type": "text"}]),
    ("EVIDENCE", "Design evidence", "OTHER", "pdf,png,jpg,docx,xlsx,zip", False, []),
]


def _seed_design_types(db) -> dict:
    from app.models import DesignType

    out = {}
    for code, name, cat, ext, editor, fields in DESIGN_TYPES:
        out[code] = DesignType(code=code, name=name, category=cat, allowed_extensions=ext, diagram_editor=editor, fields=json.dumps(fields))
        db.add(out[code])
    db.flush()
    return out


DEMO_DIAGRAM = (
    '<mxfile host="ADA-ELM"><diagram name="Processing architecture" id="d1"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    '<mxCell id="a" value="Channel A" style="rounded=1;" vertex="1" parent="1"><mxGeometry x="40" y="40" width="120" height="50" as="geometry"/></mxCell>'
    '<mxCell id="b" value="Channel B" style="rounded=1;" vertex="1" parent="1"><mxGeometry x="40" y="120" width="120" height="50" as="geometry"/></mxCell>'
    '<mxCell id="c" value="Channel C" style="rounded=1;" vertex="1" parent="1"><mxGeometry x="40" y="200" width="120" height="50" as="geometry"/></mxCell>'
    '<mxCell id="v" value="Voter / health monitor" style="shape=hexagon;" vertex="1" parent="1"><mxGeometry x="260" y="110" width="160" height="70" as="geometry"/></mxCell>'
    '</root></mxGraphModel></diagram></mxfile>'
)
DEMO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="460" height="280" viewBox="0 0 460 280"><g font-family="sans-serif" font-size="13">'
    '<rect x="40" y="40" width="120" height="50" rx="8" fill="#e7f0ff" stroke="#3b6fd8"/><text x="100" y="70" text-anchor="middle">Channel A</text>'
    '<rect x="40" y="120" width="120" height="50" rx="8" fill="#e7f0ff" stroke="#3b6fd8"/><text x="100" y="150" text-anchor="middle">Channel B</text>'
    '<rect x="40" y="200" width="120" height="50" rx="8" fill="#e7f0ff" stroke="#3b6fd8"/><text x="100" y="230" text-anchor="middle">Channel C</text>'
    '<polygon points="280,110 400,110 420,145 400,180 280,180 260,145" fill="#eefbf4" stroke="#2f9e6e"/><text x="340" y="150" text-anchor="middle">Voter / monitor</text>'
    '<path d="M160 65 L260 135 M160 145 L260 145 M160 225 L260 155" stroke="#555" fill="none"/></g></svg>'
)


def _seed_demo_design_and_tests(db, alpha, pe, priya, joshi, td, rohit, cpu, dtypes) -> None:
    """A design record with a diagram version, approved test cases verifying requirements, an active plan, a run with a
    failure analysed as an application defect. Built with the same rules the API uses."""
    import hashlib

    from app.models import ArtifactLink, Defect, DesignRecord, DesignVersion, NumberSequence, TestCase, TestPlan, TestRun, TestRunCase, TestSuite, TestSuiteCase
    from app.services import artifacts as art
    from app.services import storage
    from app.services import testing as ts

    req1 = db.execute(select(Requirement).where(Requirement.key == "ALPHA-CPU-0001")).scalar_one()
    req2 = db.execute(select(Requirement).where(Requirement.key == "ALPHA-CPU-0002")).scalar_one()
    d = DesignRecord(project_id=alpha.id, item_id=cpu.id, type_id=dtypes["ARCH"].id, key="ALPHA-DES-0001", title="CPU processing architecture", description="Three processing channels with a voter and health monitor (demo, fictional).",
                     attributes=json.dumps({"rationale": "Triple redundancy so that one channel failure is tolerated.", "level": "Component"}), status="IN_PROGRESS", owner_id=pe.id, created_by_id=pe.id, current_version=1)
    db.add(d)
    db.flush()
    src = storage.put_bytes(db, DEMO_DIAGRAM.encode(), "ALPHA-DES-0001-v1.drawio", pe.id)
    prev = storage.put_bytes(db, DEMO_SVG.encode(), "ALPHA-DES-0001-v1.svg", pe.id)
    db.add(DesignVersion(design_id=d.id, version_no=1, kind="DIAGRAM", source_file_id=src.id, preview_file_id=prev.id, content_sha256=hashlib.sha256(DEMO_DIAGRAM.encode()).hexdigest(), note="First draft", created_at=utcnow(), created_by_id=pe.id))
    art.add_event(db, "DESIGN", d.id, "CREATED", pe.id, to="DRAFT")
    art.add_event(db, "DESIGN", d.id, "VERSION", pe.id, None, 1, "First draft")
    db.add(ArtifactLink(from_type="DESIGN", from_id=d.id, to_type="REQUIREMENT", to_id=req1.id, link_type="satisfies", section="3.1 Redundancy", created_by_id=pe.id))

    def case(n, title, req, status, steps):
        c = TestCase(project_id=alpha.id, item_id=cpu.id, key=f"ALPHA-TC-{n:04d}", title=title, objective=f"Verify {req.key}.", test_type="SYSTEM", steps=json.dumps(steps), expected_result=steps[-1]["expected"],
                     status=status, owner_id=priya.id, created_by_id=priya.id, content_sha256="")
        db.add(c)
        db.flush()
        ts.write_case_revision(db, c, priya.id, "Created")
        art.add_event(db, "TEST_CASE", c.id, "CREATED", priya.id, to="DRAFT")
        db.add(ArtifactLink(from_type="TEST_CASE", from_id=c.id, to_type="REQUIREMENT", to_id=req.id, link_type="verifies", created_by_id=priya.id))
        if status == "APPROVED":
            from app.models import ArtifactReview

            db.add(ArtifactReview(artifact_type="TEST_CASE", artifact_id=c.id, revision=1, content_sha256=c.content_sha256, cycle=1, reviewer_id=joshi.id, role="APPROVER", status="APPROVED", decided_at=utcnow(), submitted_by_id=priya.id))
            art.add_event(db, "TEST_CASE", c.id, "STATUS", joshi.id, "UNDER_REVIEW", "APPROVED")
        return c

    c1 = case(1, "Operation continues after a single channel fault", req1, "APPROVED", [{"action": "Power up the unit with all three channels healthy", "expected": "All channels report healthy"},
                                                                                        {"action": "Inject a fault into channel B", "expected": "Channel B is isolated within 50 ms and output continues"}])
    c2 = case(2, "Failed channel is detected within 50 ms", req2, "APPROVED", [{"action": "Inject a fault into channel A and time detection", "expected": "Detection time is at most 50 ms"}])
    case(3, "Channel status reported to the main processor", db.execute(select(Requirement).where(Requirement.key == "ALPHA-CPU-0003")).scalar_one(), "DRAFT",
         [{"action": "Monitor the status messages on the interface", "expected": "Status messages arrive at the specified rate"}])
    plan = TestPlan(project_id=alpha.id, key="ALPHA-TP-0001", title="CPU system qualification", scope="Redundancy and fault detection of the CPU (demo).", build_version="1.4.0", environments="Integration rig",
                    entry_criteria=json.dumps(["Build 1.4.0 installed on the rig", "Rig calibration valid"]), exit_criteria=json.dumps({**ts.DEFAULT_EXIT, "manual": ["Test rig log archived"]}), status="ACTIVE", owner_id=priya.id, created_by_id=priya.id, content_sha256="")
    _, plan.content_sha256 = ts.canon(ts.plan_content(plan), ts.PLAN_FIELDS)
    db.add(plan)
    db.flush()
    suite = TestSuite(plan_id=plan.id, name="Redundancy")
    db.add(suite)
    db.flush()
    db.add_all([TestSuiteCase(suite_id=suite.id, case_id=c1.id, sort_order=0), TestSuiteCase(suite_id=suite.id, case_id=c2.id, sort_order=1)])
    art.add_event(db, "TEST_PLAN", plan.id, "STATUS", td.id, "APPROVED", "ACTIVE")
    run = TestRun(plan_id=plan.id, project_id=alpha.id, key="ALPHA-RUN-0001", title="Qualification run 1", build_version="1.4.0", environment="Integration rig", executor_id=priya.id, created_by_id=priya.id)
    db.add(run)
    db.flush()
    rc1, rc2 = TestRunCase(run_id=run.id, case_id=c1.id, case_revision=1, assignee_id=priya.id, sort_order=0), TestRunCase(run_id=run.id, case_id=c2.id, case_revision=1, assignee_id=priya.id, sort_order=1)
    db.add_all([rc1, rc2])
    db.flush()
    ts.record_execution(db, rc1, run, result="PASSED", tester_id=priya.id, actual="Output continued; channel B isolated in 31 ms.", cause=None, defect=None)
    defect = Defect(project_id=alpha.id, item_id=cpu.id, key="ALPHA-DEF-0001", title="Channel A fault detected after 72 ms", description="Detection exceeds the 50 ms limit when channel A fails first.", severity="HIGH", priority="HIGH",
                    assignee_id=pe.id, reporter_id=priya.id, found_in_build="1.4.0")
    db.add(defect)
    db.flush()
    art.add_event(db, "DEFECT", defect.id, "CREATED", priya.id, to="OPEN")
    db.add(ArtifactLink(from_type="DEFECT", from_id=defect.id, to_type="TEST_CASE", to_id=c2.id, link_type="found_by", created_by_id=priya.id))
    ts.record_execution(db, rc2, run, result="FAILED", tester_id=priya.id, actual="Detection took 72 ms.", cause="application_defect", defect=defect)
    db.add_all([NumberSequence(key="des:ALPHA", next_value=2), NumberSequence(key="tc:ALPHA", next_value=4), NumberSequence(key="tp:ALPHA", next_value=2), NumberSequence(key="run:ALPHA", next_value=2), NumberSequence(key="def:ALPHA", next_value=2)])
    db.flush()


def _seed_demo_deployments(db, alpha, pe, td, cm) -> None:
    """Three environments with different rules and a short deployment history (architecture §14, fictional)."""
    from datetime import timedelta as td_

    from app.models import ArtifactReview, Deployment, DeploymentAttempt, DeploymentEnvironment, NumberSequence, TestRun
    from app.services import artifacts as art
    from app.services import deployment as dep

    def env(code, name, order, cfg, approved):
        e = DeploymentEnvironment(project_id=alpha.id, code=code, name=name, sort_order=order, config="", config_sha256="")
        dep.set_config(e, dep.validate_config(db, alpha.id, cfg), pe.id)
        if approved:
            e.config_status, e.config_approved_sha256, e.config_approved_by_id, e.config_approved_at = "APPROVED", e.config_sha256, td.id, utcnow()
        db.add(e)
        db.flush()
        return e

    integ = env("INT", "Integration rig", 0, {"requires_approval": False, "require_config_approval": False, "require_test_run": False, "blocking_defect_severities": []}, False)
    uat = env("UAT", "User acceptance", 1, {"approvals_required": 1, "checklist": ["Release notes reviewed", "Rollback plan agreed"], "blocking_defect_severities": ["CRITICAL"]}, True)
    env("PROD", "Operational", 2, {"approvals_required": 2, "blocking_defect_severities": ["HIGH", "CRITICAL"], "required_document_types": ["SRS"], "require_commit": True,
                                    "change_window": {"days": [0, 1, 2, 3, 4], "start": "10:00", "end": "17:00"}, "checklist": ["Release notes reviewed", "Rollback plan agreed", "Operations informed"]}, False)

    def deployment(n, version, e, status, days_ago=None, notes=None, run=None):
        d = Deployment(project_id=alpha.id, environment_id=e.id, key=f"ALPHA-DEP-{n:04d}", title=f"{version} to {e.code}", version_label=version, release_notes=notes, test_run_id=run.id if run else None,
                       checklist="{}", status="PLANNED", requested_by_id=pe.id, content_sha256="")
        d.content_sha256 = dep.content_hash(d)
        db.add(d)
        db.flush()
        art.add_event(db, "DEPLOYMENT", d.id, "CREATED", pe.id, to="PLANNED")
        if days_ago is not None:
            at = utcnow() - td_(days=days_ago)
            db.add(DeploymentAttempt(deployment_id=d.id, attempt_no=1, adapter="manual", status="SUCCEEDED", queued_at=at, started_at=at, finished_at=at + td_(minutes=25), triggered_by_id=pe.id,
                                     worker="demo", target=f"{e.code} {version}", gate_snapshot="[]", log=f"Installed {version} on the {e.name} (demo).", health=json.dumps({"ok": True, "skipped": True})))
            d.deployed_at = at + td_(minutes=25)
        for st in status:
            dep.set_status(db, d, st, pe.id)
        return d

    deployment(1, "1.3.0", integ, ["APPROVED", "DEPLOYING", "DEPLOYED"], days_ago=12, notes="Channel monitor first build (demo).")
    deployment(2, "1.4.0", integ, ["APPROVED", "DEPLOYING", "DEPLOYED"], days_ago=2, notes="Faster fault detection (demo).")
    run = db.execute(select(TestRun).where(TestRun.key == "ALPHA-RUN-0001")).scalar_one()
    d3 = deployment(3, "1.4.0", uat, ["AWAITING_APPROVAL"], notes="Faster fault detection (demo). Waiting for qualification run 1 to close.", run=run)
    db.add(ArtifactReview(artifact_type="DEPLOYMENT", artifact_id=d3.id, revision=1, content_sha256=d3.content_sha256, cycle=1, reviewer_id=cm.id, role="APPROVER", submitted_by_id=pe.id))
    db.add(NumberSequence(key="dep:ALPHA", next_value=4))
    db.flush()


# Example of a preparer's review checklist on demo documents (each document's author writes their own).
DEMO_CHECKLIST = [
    {"text": "Scope, applicability and the configuration item are stated", "guidance": "Section 1", "stages": []},
    {"text": "Every requirement is uniquely tagged and testable", "guidance": "Tags follow the source's tag format", "stages": []},
    {"text": "Interfaces and referenced documents are listed with their revisions", "guidance": "Sections 2 and 6", "stages": []},
    {"text": "Open issues and TBDs are recorded with owners", "guidance": "Annex A", "stages": []},
]


def _seed_phases(db) -> None:
    for i, (code, name) in enumerate(PHASES):
        db.add(PlanPhase(code=code, name=name, sort_order=i, weight=1.0))


def _seed_demo_plan(db, alpha, orgs, people, items) -> None:
    """Fictional Product Alpha plan with engineering phases, built from the same models the API uses."""
    ctl, elx = orgs
    pgd, pe, priya, sanjay, dir_elx = people
    cpu, mpu = items
    today = date.today()
    phases = {code: PlanPhase(project_id=alpha.id, code=code, name=name, sort_order=i, weight=w) for i, (code, name, w) in enumerate([("PRELIM", "Preliminary Design", 2.0), ("DETAIL", "Detailed Design", 3.0), ("QUAL", "Qualification", 3.0), ("PROD", "Production Readiness", 2.0)])}
    db.add_all(phases.values())
    db.flush()
    plan = ProjectPlan(project_id=alpha.id, name="Product Alpha Development Plan", version_label="1.0", status="ACTIVE", owner_id=pgd.id, created_by_id=pgd.id, description="Demo plan (fictional).")
    db.add(plan)
    db.flush()
    pdr = Milestone(project_id=alpha.id, plan_id=plan.id, code="PDR", name="Preliminary Design Review", status="ACHIEVED", start_date=today - timedelta(days=120), due_date=today - timedelta(days=40), achieved_date=today - timedelta(days=42), owner_id=pgd.id)
    cdr = Milestone(project_id=alpha.id, plan_id=plan.id, code="CDR", name="Critical Design Review", status="IN_PROGRESS", start_date=today - timedelta(days=30), due_date=today + timedelta(days=12), owner_id=pgd.id)
    qtr = Milestone(project_id=alpha.id, plan_id=plan.id, code="QTR", name="Qualification Test Readiness", status="PLANNED", due_date=today + timedelta(days=75), owner_id=dir_elx.id)
    db.add_all([pdr, cdr, qtr])
    wp_ctl = WorkPackage(plan_id=plan.id, project_id=alpha.id, code="WP-CTL", name="Central Processing Unit", lead_org_unit_id=ctl.id, item_id=cpu.id, owner_id=pe.id, start_date=today - timedelta(days=120), end_date=today + timedelta(days=60))
    wp_elx = WorkPackage(plan_id=plan.id, project_id=alpha.id, code="WP-ELX", name="Main Processor", lead_org_unit_id=elx.id, item_id=mpu.id, owner_id=dir_elx.id, start_date=today - timedelta(days=30), end_date=today + timedelta(days=90))
    db.add_all([wp_ctl, wp_elx])
    db.flush()
    db.add(WorkPackageOrg(work_package_id=wp_ctl.id, org_unit_id=elx.id))
    act_prelim = PlanActivity(plan_id=plan.id, project_id=alpha.id, work_package_id=wp_ctl.id, phase_id=phases["PRELIM"].id, title="CPU preliminary design", owner_id=pe.id, start_date=today - timedelta(days=120), end_date=today - timedelta(days=45), estimated_hours=200, status="COMPLETED", sort_order=0)
    act_design = PlanActivity(plan_id=plan.id, project_id=alpha.id, work_package_id=wp_ctl.id, phase_id=phases["DETAIL"].id, title="CPU detailed design", owner_id=pe.id, start_date=today - timedelta(days=30), end_date=today + timedelta(days=10), estimated_hours=240, status="IN_PROGRESS", sort_order=1)
    act_qual = PlanActivity(plan_id=plan.id, project_id=alpha.id, work_package_id=wp_ctl.id, phase_id=phases["QUAL"].id, title="CPU qualification preparation", owner_id=pe.id, start_date=today + timedelta(days=12), end_date=today + timedelta(days=60), estimated_hours=160, sort_order=2)
    act_mp = PlanActivity(plan_id=plan.id, project_id=alpha.id, work_package_id=wp_elx.id, phase_id=phases["DETAIL"].id, title="Main processor thermal design", owner_id=sanjay.id, start_date=today - timedelta(days=20), end_date=today + timedelta(days=15), estimated_hours=120, status="IN_PROGRESS", sort_order=3)
    db.add_all([act_prelim, act_design, act_qual, act_mp])
    db.flush()

    def task(n, title, act, who, org, start, due, hours, status="OPEN", reported=0.0):
        pct = {"COMPLETED": 100.0, "OPEN": 0.0}.get(status, reported)
        w = WorkItem(key=f"ALPHA-{n}", title=title, status=status, project_id=alpha.id, plan_id=plan.id, work_package_id=act.work_package_id, activity_id=act.id, item_id=cpu.id if org is ctl else mpu.id, org_unit_id=org.id, assignee_id=who.id, reporter_id=pe.id,
                     start_date=today + timedelta(days=start), due_date=today + timedelta(days=due), estimated_hours=hours, reported_progress=reported, progress=pct, actual_start=(today + timedelta(days=start)) if status != "OPEN" else None)
        if status == "COMPLETED":
            w.actual_end = today + timedelta(days=due)
            w.completed_at = utcnow()
        db.add(w)
        db.flush()
        db.add(WorkItemEvent(work_item_id=w.id, actor_id=pe.id, kind="CREATED", to_value="OPEN"))
        return w

    t1 = task(10, "CPU preliminary design report", act_prelim, priya, ctl, -110, -50, 200, "COMPLETED")
    t2 = task(11, "CPU processing-function partitioning", act_design, priya, ctl, -28, -6, 80, "COMPLETED")
    t3 = task(12, "CPU hardware architecture description", act_design, pe, ctl, -5, 5, 100, "IN_PROGRESS", 60.0)
    t4 = task(13, "CPU interface data exchange with main processor", act_design, priya, ctl, -2, 9, 60, "IN_PROGRESS", 25.0)
    t5 = task(14, "Main processor thermal analysis", act_mp, sanjay, elx, -18, -3, 70, "IN_PROGRESS", 70.0)
    t6 = task(15, "Main processor cooling concept review", act_mp, sanjay, elx, 0, 14, 50)
    t7 = task(16, "CPU qualification test plan", act_qual, pe, ctl, 13, 40, 90)
    t8 = task(17, "CPU embedded software: channel health monitor", act_design, priya, ctl, -3, 12, 40, "IN_PROGRESS", 30.0)
    t8.kind = "DEVELOPMENT"  # follows the software development lifecycle (architecture §12.1); GitLab links appear once a repository is registered
    db.add_all([TaskDependency(successor_id=t2.id, predecessor_id=t1.id, dep_type="FS", created_by_id=pe.id), TaskDependency(successor_id=t3.id, predecessor_id=t2.id, dep_type="FS", created_by_id=pe.id),
                TaskDependency(successor_id=t4.id, predecessor_id=t5.id, dep_type="SS", lag_days=2, created_by_id=pe.id), TaskDependency(successor_id=t6.id, predecessor_id=t5.id, dep_type="FS", created_by_id=dir_elx.id),
                TaskDependency(successor_id=t7.id, predecessor_id=t3.id, dep_type="FS", lag_days=3, created_by_id=pe.id)])
    db.add_all([TaskChecklistItem(work_item_id=t3.id, text="Reviewed against the CPU specification", sort_order=0), TaskChecklistItem(work_item_id=t3.id, text="Interface list agreed with ELX", sort_order=1)])
    db.add(TaskParticipant(work_item_id=t3.id, user_id=priya.id, role="REVIEWER"))
    t3.milestone_id = cdr.id
    db.flush()


def _seed_demo_requirements(db, alpha, pe, priya, reviewer, approver, cpu, task_key) -> None:
    """Fictional requirements taken through the same rules the API applies."""
    from app.services import requirements as rq

    src = RequirementSource(project_id=alpha.id, name="CPU System Requirements Specification", key_prefix="ALPHA-CPU", created_by_id=pe.id)
    db.add(src)
    db.flush()

    def req(n, title, status, acceptance, parent=None, priority="HIGH"):
        desc = f"{title}. Demo requirement (fictional)."
        r = Requirement(project_id=alpha.id, source_id=src.id, parent_id=parent.id if parent else None, key=f"ALPHA-CPU-{n:04d}", title=title, description=desc, acceptance_criteria=acceptance, req_type="FUNCTIONAL", priority=priority, status=status, owner_id=pe.id, item_id=cpu.id,
                        content_sha256=rq.content_hash(title, desc, acceptance, "FUNCTIONAL", priority))
        db.add(r)
        db.flush()
        rq.write_revision(db, r, pe.id, "Created")
        rq.add_event(db, r, "CREATED", pe.id, to=status)
        return r

    r1 = req(1, "The CPU shall provide triple redundant processing channels", "BASELINED", "Fault injection shows continued operation after one channel fails.")
    r2 = req(2, "The CPU shall detect a failed channel within 50 ms", "APPROVED", "Timing test shows detection within 50 ms in every failure mode.", parent=r1)
    r3 = req(3, "The CPU shall report channel status to the main processor", "UNDER_REVIEW", "Interface test shows status messages at the specified rate.", parent=r1, priority="MEDIUM")
    r4 = req(4, "The CPU shall log all channel failures for maintenance", "UNDER_ANALYSIS", "", priority="LOW")
    req(5, "The CPU shall support software reload in service", "DRAFT", "", priority="LOW")
    db.add_all([RequirementLink(from_id=r3.id, to_id=r2.id, link_type="depends_on", created_by_id=pe.id), RequirementLink(from_id=r4.id, to_id=r2.id, link_type="derived_from", created_by_id=pe.id)])
    for r in (r1, r2):
        db.add(RequirementReview(requirement_id=r.id, revision=1, content_sha256=r.content_sha256, cycle=1, reviewer_id=approver.id, role="APPROVER", status="APPROVED", decided_at=utcnow()))
    db.add(RequirementReview(requirement_id=r3.id, revision=1, content_sha256=r3.content_sha256, cycle=1, reviewer_id=reviewer.id, role="REVIEWER"))
    db.add(RequirementReview(requirement_id=r3.id, revision=1, content_sha256=r3.content_sha256, cycle=1, reviewer_id=approver.id, role="APPROVER"))
    base = RequirementBaseline(project_id=alpha.id, seq=1, label="CPU requirements at PDR", reason="Agreed at the preliminary design review (demo).", sha256="", created_by_id=pe.id)
    db.add(base)
    db.flush()
    item = rq.baseline_item(base.id, r1)
    db.add(item)
    base.sha256 = rq.seal_items([item])
    task = db.execute(select(WorkItem).where(WorkItem.key == task_key)).scalar_one()
    db.add(RequirementWorkItem(requirement_id=r1.id, work_item_id=task.id, link_type="implements", created_by_id=pe.id))
    db.flush()


def _org(db, code, name, typ, parent=None, oversight=False):
    o = OrgUnit(id=uuid.uuid4(), code=code, name=name, unit_type=typ, parent_id=parent.id if parent else None, is_oversight=oversight)
    o.path = (parent.path if parent else "/") + f"{o.id}/"
    db.add(o)
    return o


def _item(db, project, levels, parent, level_code, code, name, org=None, pn=None, domain=None, phase="PRELIMINARY_DESIGN"):
    it = EngineeringItem(id=uuid.uuid4(), project_id=project.id, parent_id=parent.id if parent else None, level_id=levels[level_code].id, code=code, name=name,
                         part_number=pn, lead_org_unit_id=org.id if org else None, domain_id=domain.id if domain else None, lifecycle_phase=phase)
    it.path = (parent.path if parent else "/") + f"{it.id}/"
    db.add(it)
    db.flush()
    return it


def _wf(db, code, name, desc, spec, owner):
    s = WorkflowSpec.model_validate(spec)
    errs = validate_spec(s)
    assert not errs, errs
    text = s.model_dump_json()
    import hashlib

    d = WorkflowDefinition(code=code, name=name, description=desc, draft_spec=text, owner_id=owner.id)
    db.add(d)
    db.flush()
    db.add(WorkflowVersion(definition_id=d.id, version_no=1, spec=text, spec_sha256=hashlib.sha256(text.encode()).hexdigest(), status="PUBLISHED", published_by_id=owner.id, published_at=utcnow()))
    return d


def seed() -> None:
    s = get_settings()
    db = SessionLocal()
    try:
        if db.execute(select(User.id)).first():
            return
        pw = hash_password(s.demo_password)

        # ---- organization (example names from the requirement; editable master data)
        ada = _org(db, "ADA", "Aeronautical Development Agency", "ORGANIZATION")
        hd = _org(db, "PD", "Programme Directorate (Head Directorate)", "HEAD_DIRECTORATE", ada, oversight=True)
        ctl = _org(db, "CTL", "Control Systems Directorate", "DIRECTORATE", ada)
        elx = _org(db, "ELX", "Electronics Systems Directorate", "DIRECTORATE", ada)
        mec = _org(db, "MEC", "Mechanical & Materials Directorate", "DIRECTORATE", ada)
        ict = _org(db, "ICT", "Information & Communication Technology Directorate", "DIRECTORATE", ada)
        qa = _org(db, "QA", "Quality Assurance & Configuration Mgmt", "DIRECTORATE", ada)
        adm = _org(db, "ADMIN", "Administration Directorate", "DIRECTORATE", ada)
        ctl_cd = _org(db, "CTL-CD", "Control Design Department", "DEPARTMENT", ctl)
        ctl_mi = _org(db, "CTL-MI", "Mechanical Integration Department", "DEPARTMENT", ctl)
        elx_pu = _org(db, "ELX-PU", "Processing Units Department", "DEPARTMENT", elx)
        elx_du = _org(db, "ELX-DU", "Display Units Department", "DEPARTMENT", elx)
        ict_se = _org(db, "ICT-SE", "Software Engineering Department", "DEPARTMENT", ict)
        adm_proc = _org(db, "ADM-PROC", "Procurement Division", "DIVISION", adm)
        _org(db, "ADM-HR", "Human Resources Division", "DIVISION", adm)
        db.flush()

        # ---- domains
        dom = {}
        for code, name, eng, color in [("HARDWARE", "Hardware / Engineering", True, "#2f54eb"), ("SOFTWARE", "Software (SDLC)", True, "#13c2c2"), ("SYSTEMS", "Systems Engineering", True, "#722ed1"),
                                       ("ADMIN", "Administration", False, "#fa8c16"), ("QUALITY", "Quality & Configuration", False, "#52c41a")]:
            dom[code] = ProcessDomain(code=code, name=name, is_engineering=eng, color=color)
            db.add(dom[code])

        # ---- roles
        roles = {}
        for code, (name, perms) in ROLES.items():
            r = Role(code=code, name=name, is_system=True)
            db.add(r)
            db.flush()
            for p in perms:
                db.add(RolePermission(role_id=r.id, permission=p))
            roles[code] = r

        # ---- users (fictional)
        def user(un, name, desig, org, emp, admin=False):
            u = User(username=un, full_name=name, designation=desig, primary_org_unit_id=org.id, employee_no=emp, email=f"{un}@ada.local", password_hash=pw, is_system_admin=admin)
            db.add(u)
            db.flush()
            db.add(UserOrgAssignment(user_id=u.id, org_unit_id=org.id, position="HEAD" if "Director" in (desig or "") or "Head" in (desig or "") else "MEMBER"))
            return u

        admin = user("admin", "System Administrator", "Platform Administrator", ict, "E0001", admin=True)
        pgd = user("pgd.rao", "Dr. Arjun Rao", "Programme Director", hd, "E1001")
        td = user("td.menon", "Kavita Menon", "Technical Director", ctl, "E1002")
        dir_elx = user("dir.iyer", "Rajesh Iyer", "Director, ELX", elx, "E1003")
        cm = user("cm.sharma", "Neha Sharma", "Configuration Manager", qa, "E1004")
        pe = user("pe.kumar", "Vikram Kumar", "Project Engineer", ctl_cd, "E2001")
        priya = user("eng.priya", "Priya Nair", "Scientist 'D'", ctl_cd, "E2002")
        das = user("chk.das", "Anil Das", "Scientist 'E'", ctl_mi, "E2003")
        joshi = user("rev.joshi", "Meera Joshi", "Scientist 'F'", ctl, "E2004")
        sanjay = user("eng.sanjay", "Sanjay Patil", "Scientist 'C'", elx_pu, "E2005")
        fatima = user("chk.fatima", "Fatima Sheikh", "Scientist 'E'", elx_du, "E2006")
        rohit = user("qa.verma", "Rohit Verma", "QA Manager", qa, "E2007")
        deepa = user("proc.krishnan", "Deepa Krishnan", "Process Owner", qa, "E2008")
        suresh = user("adm.babu", "Suresh Babu", "Administrative Officer", adm_proc, "E3001")
        lakshmi = user("adm.head", "Lakshmi Rao", "Head, Administration", adm, "E3002")
        rakesh = user("sw.rakesh", "Rakesh Gupta", "Software Lead", ict_se, "E2009")

        def grant(u, role, scope_type="GLOBAL", scope=None):
            db.add(RoleAssignment(user_id=u.id, role_id=roles[role].id, scope_type=scope_type, scope_id=scope.id if scope is not None else None, granted_by_id=admin.id))

        db.flush()
        # ---- projects & breakdown
        alpha = Project(code="ALPHA", name="Product Alpha Development", programme="Alpha Programme", status="ACTIVE", lead_org_unit_id=hd.id, color="#1677ff", classification="RESTRICTED", start_date=date(2024, 4, 1), end_date=date(2034, 3, 31))
        beta = Project(code="BETA", name="Product Beta Upgrade", programme="Beta Programme", status="ACTIVE", lead_org_unit_id=hd.id, color="#fa541c", classification="RESTRICTED", start_date=date(2023, 1, 1))
        db.add_all([alpha, beta])
        db.flush()
        lv = {}
        for i, (c, n, color, icon) in enumerate([("PRODUCT", "Product", "#1677ff", "product"), ("SYSTEM", "System", "#722ed1", "system"), ("SUBSYSTEM", "Subsystem", "#13c2c2", "subsystem"), ("UNIT", "Unit / Assembly", "#fa8c16", "unit"), ("MODULE", "Module", "#8c8c8c", "module")], 1):
            lv[c] = HierarchyLevel(project_id=alpha.id, level_no=i, code=c, name=n, color=color, icon=icon)
            db.add(lv[c])
        lv2 = {}
        for i, (c, n, color, icon) in enumerate([("PRODUCT", "Product", "#1677ff", "product"), ("UNIT", "Unit / Assembly", "#fa8c16", "unit"), ("COMPONENT", "Component", "#eb2f96", "module")], 1):
            lv2[c] = HierarchyLevel(project_id=beta.id, level_no=i, code=c, name=n, color=color, icon=icon)
            db.add(lv2[c])
        for o, part in [(hd, "LEAD"), (ctl, "CONTRIBUTOR"), (elx, "CONTRIBUTOR"), (mec, "CONTRIBUTOR"), (qa, "OVERSIGHT")]:
            db.add(ProjectOrgAssignment(project_id=alpha.id, org_unit_id=o.id, participation=part))
        db.flush()

        prd = _item(db, alpha, lv, None, "PRODUCT", "ALPHA-PRD", "Alpha Product", hd, domain=dom["SYSTEMS"], phase="DETAILED_DESIGN")
        ctl_sys = _item(db, alpha, lv, prd, "SYSTEM", "CTL", "Control System", ctl, domain=dom["HARDWARE"])
        prc = _item(db, alpha, lv, ctl_sys, "SUBSYSTEM", "CTL-PRC", "Processing Subsystem", ctl_cd, domain=dom["HARDWARE"])
        cpu = _item(db, alpha, lv, prc, "UNIT", "CTL-CPU", "Central Processing Unit", ctl_cd, "ALPHA-CPU-1000", dom["HARDWARE"])
        _item(db, alpha, lv, cpu, "MODULE", "CTL-CPU-PSM", "CPU Power Supply Module", ctl_cd, "ALPHA-CPU-1010", dom["HARDWARE"])
        _item(db, alpha, lv, cpu, "MODULE", "CTL-CPU-SW", "CPU Embedded Software", ict_se, "ALPHA-CPU-SW01", dom["SOFTWARE"])
        act = _item(db, alpha, lv, prc, "UNIT", "CTL-DRV", "Drive Unit", ctl_mi, "ALPHA-DRV-2000", dom["HARDWARE"])
        sns = _item(db, alpha, lv, ctl_sys, "SUBSYSTEM", "CTL-SNS", "Sensing Subsystem", ctl, domain=dom["HARDWARE"])
        spu = _item(db, alpha, lv, sns, "UNIT", "CTL-SPU", "Sensor Processing Unit", ctl, "ALPHA-SPU-3000", dom["HARDWARE"])
        esys = _item(db, alpha, lv, prd, "SYSTEM", "ELX", "Electronics System", elx, domain=dom["HARDWARE"])
        mcs = _item(db, alpha, lv, esys, "SUBSYSTEM", "ELX-CMP", "Computing Subsystem", elx_pu, domain=dom["HARDWARE"])
        mpu = _item(db, alpha, lv, mcs, "UNIT", "ELX-MPU", "Main Processor Unit", elx_pu, "ALPHA-MPU-4000", dom["HARDWARE"])
        dsp = _item(db, alpha, lv, esys, "SUBSYSTEM", "ELX-DSP", "Display Subsystem", elx_du, domain=dom["HARDWARE"])
        dpu = _item(db, alpha, lv, dsp, "UNIT", "ELX-DPU", "Display Panel Unit", elx_du, "ALPHA-DPU-5000", dom["HARDWARE"])
        st = _item(db, alpha, lv, prd, "SYSTEM", "MEC", "Mechanical Structure", mec, domain=dom["HARDWARE"], phase="CONCEPT")
        _item(db, alpha, lv, st, "SUBSYSTEM", "MEC-ENC", "Enclosure Subsystem", mec, domain=dom["HARDWARE"], phase="CONCEPT")
        _item(db, alpha, lv, prd, "SYSTEM", "PWR", "Power System", hd, domain=dom["HARDWARE"], phase="CONCEPT")
        beta_prd = _item(db, beta, lv2, None, "PRODUCT", "BETA-PRD", "Beta Product", hd, domain=dom["SYSTEMS"])
        snu = _item(db, beta, lv2, beta_prd, "UNIT", "BETA-SNU", "Sensor Unit", elx, "BETA-SNU-100", dom["HARDWARE"])
        _item(db, beta, lv2, snu, "COMPONENT", "BETA-SNU-C01", "Signal Processor Component", elx_pu, "BETA-SNU-101", dom["HARDWARE"])
        cpu.technical_owner_id = pe.id

        # ---- role assignments (scoped)
        grant(pgd, "PGD"); grant(pgd, "HD_OVERSIGHT"); grant(pgd, "APPROVER", "PROJECT", alpha)
        grant(td, "TD", "PROJECT", alpha); grant(td, "APPROVER", "ORG_UNIT", ctl); grant(td, "REVIEWER", "PROJECT", alpha)
        grant(dir_elx, "DIR_HEAD", "ORG_UNIT", elx); grant(dir_elx, "APPROVER", "ORG_UNIT", elx); grant(dir_elx, "REVIEWER", "PROJECT", alpha)
        grant(cm, "RELEASE_AUTH"); grant(cm, "HD_OVERSIGHT")
        grant(pe, "PE", "PROJECT", alpha); grant(pe, "TEAM_MEMBER", "ORG_UNIT", ctl)
        grant(priya, "TEAM_MEMBER", "ORG_UNIT", ctl)
        grant(das, "CHECKER", "ORG_UNIT", ctl); grant(das, "TEAM_MEMBER", "ORG_UNIT", ctl_mi)
        grant(joshi, "REVIEWER", "PROJECT", alpha); grant(joshi, "DEPT_HEAD", "ORG_UNIT", ctl)
        grant(sanjay, "TEAM_MEMBER", "ORG_UNIT", elx)
        grant(fatima, "CHECKER", "ORG_UNIT", elx); grant(fatima, "CHECKER", "ORG_UNIT", ctl)
        grant(rohit, "QA_AUDITOR")
        grant(deepa, "PROCESS_ADMIN")
        grant(suresh, "TEAM_MEMBER", "ORG_UNIT", adm)
        grant(lakshmi, "APPROVER", "ORG_UNIT", adm); grant(lakshmi, "DIR_HEAD", "ORG_UNIT", adm)
        grant(rakesh, "TEAM_MEMBER", "ORG_UNIT", ict); grant(rakesh, "REVIEWER", "PROJECT", alpha)
        for u in (pgd, td, dir_elx, pe, priya, das, joshi, sanjay, fatima, rakesh, cm):
            db.add(ProjectMember(project_id=alpha.id, user_id=u.id))
        db.flush()

        # ---- document types
        dts = {}
        for code, name, cat, pattern, tmpl, sig, levels, color, ext in DOC_TYPES:
            dts[code] = DocumentType(code=code, name=name, category=cat, numbering_pattern=pattern, default_template=tmpl, requires_signature=sig, require_review_checklist=cat == "ENGINEERING", applicable_levels=levels, color=color, allowed_extensions=ext)
            db.add(dts[code])
        db.flush()

        # ---- workflows + bindings
        w_eng = _wf(db, "ENG-4STEP", "Engineering Document Review", "Prepared → Checked → Reviewed → Approved → Digitally signed. Default for controlled engineering documents.", ENG_4STEP, deepa)
        w_adm = _wf(db, "ADMIN-APPROVAL", "Administrative Approval", "Lightweight single-approval flow for non-engineering documents; auto-registers on approval.", NONENG, deepa)
        w_hd = _wf(db, "HD-PROGRAMME", "Programme-level Document (Parallel Concurrence)", "Parallel technical concurrence from directorates (quorum 2), programme approval and signature.", HD_PROG, deepa)
        db.flush()
        db.add(WorkflowBinding(definition_id=w_eng.id, priority=0))  # catch-all default
        for c in ("MOM", "ADMN", "PRQ"):
            db.add(WorkflowBinding(definition_id=w_adm.id, document_type_id=dts[c].id))
        db.add(WorkflowBinding(definition_id=w_hd.id, document_type_id=dts["PMP"].id))
        db.add(SystemSetting(key="progress.weights", value=json.dumps({"DRAFT": 10, "IN_REVIEW": 40, "CHANGES_REQUESTED": 25, "REJECTED": 10, "APPROVED": 85, "RELEASED": 100}), description="Document status → progress % used in roll-ups"))
        db.flush()

        # ---- demo documents driven through the real workflow engine
        from app.models import DocumentRevision as _Rev
        from app.services import doc_checklist as dchk

        def new(u, t, title, item=None, project=alpha, org=None, cls="RESTRICTED"):
            d = docsvc.create_document(db, u, type_id=dts[t].id, title=title, project_id=project.id if project else None, item_id=item.id if item else None, owner_org_unit_id=org.id if org else None,
                                       domain_id=None, classification=cls, description=None, keywords=None, content=None, from_template=True)
            if dts[t].require_review_checklist:  # the preparer's review checklist (reviewers and approvers answer it)
                db.flush()
                dchk.replace_items(db, db.get(_Rev, d.current_revision_id), DEMO_CHECKLIST, u.id, set())
            return d

        def decide(u, decision, comment, fixed=None):
            t = pending(u)
            inst = db.get(WorkflowInstance, t.instance_id)
            todo = dchk.applicable(dchk.active(dchk.items(db, inst.revision_id)), t.stage_key)
            answers = {str(i.id): {"result": "OK"} for i in todo}
            if decision != "approve" and todo:
                answers[str(todo[0].id)] = {"result": "NOT_OK", "remark": comment}
            return wf.decide(db, u, t.id, decision, comment, fixed, answers)

        def pending(user):
            return db.execute(select(WorkflowTask).where(WorkflowTask.assignee_id == user.id, WorkflowTask.status == "PENDING").order_by(WorkflowTask.created_at.desc())).scalars().first()

        def cur(doc):
            from app.models import DocumentRevision

            return db.get(DocumentRevision, doc.current_revision_id)

        ok = {c: True for c in ENG_4STEP["stages"][1]["checklist"]}
        # 1) CPU Specification — fully released
        d1 = new(pe, "SPEC", "Central Processing Unit — Equipment Specification", cpu)
        db.flush()
        wf.start(db, pe, d1, cur(d1), {"check": [str(das.id)], "review": [str(joshi.id)], "approve": [str(td.id)]}, "Initial issue for release")
        decide(das, "approve", "Checked. Minor editorial remarks addressed.", ok)
        decide(joshi, "approve", "Reviewed — concur.")
        decide(td, "approve", "Approved for release.")
        for u in (pe, das, joshi, td):
            wf.sign(db, u, pending(u).id, s.demo_password)
        relsvc.release_revision(db, cm, d1, cur(d1), "Initial release")
        # 2) CPU ICD — waiting at Checker
        d2 = new(priya, "ICD", "CPU to Drive Unit Interface Control Document", cpu)
        db.flush()
        wf.start(db, priya, d2, cur(d2), {"check": [str(das.id)], "review": [str(joshi.id), str(rakesh.id)], "approve": [str(td.id)]})
        # 3) CPU SRS — changes requested
        d3 = new(priya, "SRS", "CPU Embedded Software — Software Requirements", cpu)
        db.flush()
        wf.start(db, priya, d3, cur(d3), {"check": [str(fatima.id)], "review": [str(rakesh.id)], "approve": [str(td.id)]})
        decide(fatima, "request_changes", "Section 3.2 timing requirements lack tolerance values; please add derived requirement IDs.")
        # 4) MPU spec — approved, awaiting release
        d4 = new(sanjay, "SPEC", "Main Processor Unit — Equipment Specification", mpu)
        db.flush()
        wf.start(db, sanjay, d4, cur(d4), {"check": [str(fatima.id)], "review": [str(joshi.id)], "approve": [str(dir_elx.id)]})
        decide(fatima, "approve", "OK", ok)
        decide(joshi, "approve", "OK")
        decide(dir_elx, "approve", "Approved")
        for u in (sanjay, fatima, joshi, dir_elx):
            wf.sign(db, u, pending(u).id, s.demo_password)
        # 5) Draft docs
        new(pe, "DDD", "Central Processing Unit — Hardware Design Description", cpu)
        new(das, "ATP", "Drive Unit — Acceptance Test Procedure", act)
        new(pe, "SPEC", "Sensor Processing Unit — Equipment Specification", spu)
        d6 = new(sanjay, "ICD", "Display Panel Unit — Video Interface ICD", dpu)
        db.flush()
        wf.start(db, sanjay, d6, cur(d6), {"check": [str(fatima.id)], "review": [str(joshi.id)], "approve": [str(dir_elx.id)]})
        decide(fatima, "approve", "Checked", ok)
        # 6) Programme-level document (Head Directorate) in parallel concurrence
        d7 = new(pe, "PMP", "Product Alpha Programme Management Plan — Phase 2", prd, org=hd)
        db.flush()
        wf.start(db, pe, d7, cur(d7), {"concurrence": [str(joshi.id), str(dir_elx.id), str(rakesh.id)]})
        # 7) Non-engineering: office order released via auto-release
        d8 = new(suresh, "ADMN", "Office Order — Constitution of Product Alpha Design Review Board", None, project=None, org=adm, cls="UNCLASSIFIED")
        db.flush()
        wf.start(db, suresh, d8, cur(d8), {"approve": [str(lakshmi.id)]})
        decide(lakshmi, "approve", "Approved.")
        d9 = new(suresh, "PRQ", "Procurement Request — Environmental Test Chamber", None, project=alpha, org=adm_proc, cls="UNCLASSIFIED")
        db.flush()
        wf.start(db, suresh, d9, cur(d9), {"approve": [str(lakshmi.id)]})
        new(pe, "MOM", "Minutes — Control System Preliminary Design Review", ctl_sys)

        # ---- work items (engineering + non-engineering)
        today = date.today()
        for i, (title, kind, status, prio, item, who, due, org) in enumerate([
            ("Close PDR action items for CPU", "ACTION", "IN_PROGRESS", "HIGH", cpu, pe, today + timedelta(days=5), ctl),
            ("Update CPU ICD after drive re-allocation", "TASK", "OPEN", "MEDIUM", cpu, priya, today + timedelta(days=12), ctl_cd),
            ("Thermal analysis — Main Processor Unit", "TASK", "ON_HOLD", "HIGH", mpu, sanjay, today - timedelta(days=2), elx_pu),
            ("CDR readiness review — Electronics", "MILESTONE", "OPEN", "CRITICAL", esys, dir_elx, today + timedelta(days=30), elx),
            ("Raise ECR for sensor relocation", "CHANGE_REQUEST", "OPEN", "MEDIUM", spu, pe, today + timedelta(days=9), ctl),
            ("Arrange Design Review Board meeting hall & logistics", "TASK", "IN_PROGRESS", "LOW", None, suresh, today + timedelta(days=3), adm),
            ("Vendor quotation comparison — environmental chamber", "TASK", "OPEN", "MEDIUM", None, suresh, today + timedelta(days=7), adm_proc),
        ], 1):
            db.add(WorkItem(key=f"{'ALPHA' if item else 'TSK'}-{i}", title=title, kind=kind, status=status, priority=prio, project_id=alpha.id if item else None, item_id=item.id if item else None,
                            assignee_id=who.id, reporter_id=pgd.id if item else lakshmi.id, due_date=due, org_unit_id=org.id, progress=40 if status == "IN_PROGRESS" else 0, reported_progress=40 if status == "IN_PROGRESS" else 0))
        from app.models import NumberSequence

        db.flush()
        _seed_phases(db)
        _seed_demo_plan(db, alpha, (ctl, elx), (pgd, pe, priya, sanjay, dir_elx), (cpu, mpu))
        db.add(NumberSequence(key="wi:ALPHA", next_value=20))
        _seed_demo_requirements(db, alpha, pe, priya, joshi, td, cpu, "ALPHA-12")
        _seed_demo_design_and_tests(db, alpha, pe, priya, joshi, td, rohit, cpu, _seed_design_types(db))
        _seed_demo_deployments(db, alpha, pe, td, cm)
        db.add(NumberSequence(key="req:ALPHA-CPU", next_value=6))
        db.add(NumberSequence(key="wi:TSK", next_value=10))
        db.commit()
    finally:
        db.close()


def seed_minimal() -> None:
    """Production bootstrap (ELM_SEED_DEMO_DATA=false): reference configuration + one platform administrator.
    No demo people/projects. Admin password comes from ELM_ADMIN_PASSWORD (set by the installer)."""
    import os

    s = get_settings()
    db = SessionLocal()
    try:
        if db.execute(select(User.id)).first():
            return
        pw = os.environ.get("ELM_ADMIN_PASSWORD") or s.demo_password
        ada = _org(db, "ADA", "Aeronautical Development Agency", "ORGANIZATION")
        db.flush()
        admin = User(username="admin", full_name="System Administrator", designation="Platform Administrator", primary_org_unit_id=ada.id, password_hash=hash_password(pw), is_system_admin=True)
        db.add(admin)
        db.flush()
        db.add(UserOrgAssignment(user_id=admin.id, org_unit_id=ada.id))
        for code, name, eng, color in DOMAINS:
            db.add(ProcessDomain(code=code, name=name, is_engineering=eng, color=color))
        for code, (name, perms) in ROLES.items():
            r = Role(code=code, name=name, is_system=True)
            db.add(r)
            db.flush()
            for p in perms:
                db.add(RolePermission(role_id=r.id, permission=p))
            if code in ("PROCESS_ADMIN",):
                db.add(RoleAssignment(user_id=admin.id, role_id=r.id, scope_type="GLOBAL"))
        dts = {}
        for code, name, cat, pattern, tmpl, sig, levels, color, ext in DOC_TYPES:
            dts[code] = DocumentType(code=code, name=name, category=cat, numbering_pattern=pattern, default_template=tmpl, requires_signature=sig, require_review_checklist=cat == "ENGINEERING", applicable_levels=levels, color=color, allowed_extensions=ext)
            db.add(dts[code])
        db.flush()
        w_eng = _wf(db, "ENG-4STEP", "Engineering Document Review", "Prepared → Checked → Reviewed → Approved → Digitally signed.", ENG_4STEP, admin)
        w_adm = _wf(db, "ADMIN-APPROVAL", "Administrative Approval", "Single approval for non-engineering documents; auto-registers on approval.", NONENG, admin)
        w_hd = _wf(db, "HD-PROGRAMME", "Programme-level Document (Parallel Concurrence)", "Parallel technical concurrence, programme approval and signature.", HD_PROG, admin)
        db.flush()
        db.add(WorkflowBinding(definition_id=w_eng.id, priority=0))
        for c in ("MOM", "ADMN", "PRQ"):
            db.add(WorkflowBinding(definition_id=w_adm.id, document_type_id=dts[c].id))
        db.add(WorkflowBinding(definition_id=w_hd.id, document_type_id=dts["PMP"].id))
        db.add(SystemSetting(key="progress.weights", value=json.dumps({"DRAFT": 10, "IN_REVIEW": 40, "CHANGES_REQUESTED": 25, "REJECTED": 10, "APPROVED": 85, "RELEASED": 100}), description="Document status → progress % used in roll-ups"))
        _seed_design_types(db)
        _seed_phases(db)
        db.commit()
    finally:
        db.close()


def run() -> None:
    if get_settings().seed_demo_data:
        seed()
    else:
        seed_minimal()


if __name__ == "__main__":
    from app.dbsetup import upgrade_schema

    upgrade_schema()
    run()
    print("Seed complete.")
