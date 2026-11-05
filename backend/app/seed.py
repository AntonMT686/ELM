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
    "PGD": ("PGD (label configurable)", ["project.view", "project.manage", "item.manage", "plan.manage", "task.manage", "req.edit", "req.baseline", "doc.view", "doc.download", "release.view_all", "doc.share"]),
    "TD": ("TD (label configurable)", ["project.view", "item.manage", "plan.manage", "task.manage", "req.edit", "req.baseline", "doc.view", "doc.download", "doc.share"]),
    "DIR_HEAD": ("Directorate Head", ["doc.view", "doc.download", "doc.share", "plan.manage", "task.manage", "req.edit", "project.view"]),
    "DEPT_HEAD": ("Department Head", ["doc.view", "doc.download", "doc.share", "task.manage"]),
    "PE": ("Project Engineer", ["doc.view", "doc.create", "doc.edit", "doc.download", "doc.share", "item.manage", "plan.manage", "task.manage", "req.edit", "req.baseline", "project.view"]),
    "TEAM_MEMBER": ("Team Member / Engineer", ["doc.view", "doc.create", "doc.edit", "doc.download", "req.edit"]),
    "CHECKER": ("Checked By (Checker)", ["doc.view", "doc.download"]),
    "REVIEWER": ("Reviewed By (Reviewer)", ["doc.view", "doc.download"]),
    "APPROVER": ("Approved By (Approver)", ["doc.view", "doc.download"]),
    "RELEASE_AUTH": ("Release / Configuration Authority", ["doc.view", "doc.download", "doc.release", "doc.withdraw", "req.baseline"]),
    "PROCESS_ADMIN": ("Process / Workflow Administrator", ["workflow.configure", "admin.config", "project.view"]),
    "QA_AUDITOR": ("Quality / Audit", ["audit.view", "doc.view", "doc.download", "project.view"]),
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
    ("SPEC", "Specification (System / LRU)", "ENGINEERING", "{PROJECT}-{ITEM}-SPEC-{SEQ:3}", "docx", True, "SYSTEM,SUBSYSTEM,LRU,SRU,ECFM", "#1677ff", "docx,pdf"),
    ("SRS", "Software Requirements Specification", "ENGINEERING", "{PROJECT}-{ITEM}-SRS-{SEQ:3}", "docx", True, None, "#13c2c2", "docx,pdf"),
    ("ICD", "Interface Control Document", "ENGINEERING", "{PROJECT}-{ITEM}-ICD-{SEQ:3}", "docx", True, None, "#722ed1", "docx,xlsx,pdf"),
    ("DDD", "Design Description Document", "ENGINEERING", "{PROJECT}-{ITEM}-DDD-{SEQ:3}", "docx", True, None, "#2f54eb", "docx,pdf,drawio"),
    ("ATP", "Acceptance Test Procedure", "ENGINEERING", "{PROJECT}-{ITEM}-ATP-{SEQ:3}", "docx", True, "LRU,SRU,ECFM", "#fa8c16", "docx,xlsx,pdf"),
    ("TR", "Test / Qualification Report", "ENGINEERING", "{PROJECT}-{ITEM}-TR-{SEQ:3}", "docx", True, None, "#faad14", "docx,xlsx,pdf"),
    ("DRG", "Engineering Drawing", "ENGINEERING", "{PROJECT}-{ITEM}-DRG-{SEQ:4}", None, True, None, "#595959", "pdf,png,jpg"),
    ("CR", "Engineering Change Request", "ENGINEERING", "{PROJECT}-ECR-{YEAR}-{SEQ:4}", "docx", True, None, "#f5222d", "docx,pdf"),
    ("PMP", "Programme Management Plan", "MANAGEMENT", "{PROJECT}-PMP-{SEQ:2}", "docx", True, "AIRCRAFT", "#eb2f96", "docx,pdf"),
    ("MOM", "Minutes of Meeting", "NON_ENGINEERING", "{PROJECT}-MOM-{YEAR}-{SEQ:4}", "docx", False, None, "#8c8c8c", "docx,pdf"),
    ("ADMN", "Administrative Note / Office Order", "NON_ENGINEERING", "ADA-{ORG}-{YEAR}-{SEQ:4}", "docx", False, None, "#fa8c16", "docx,pdf"),
    ("PRQ", "Procurement Request", "NON_ENGINEERING", "ADA-{ORG}-PRQ-{YEAR}-{SEQ:4}", "xlsx", False, None, "#a0d911", "xlsx,docx,pdf"),
]

DOMAINS = [("HARDWARE", "Hardware / Engineering", True, "#2f54eb"), ("SOFTWARE", "Software (SDLC)", True, "#13c2c2"), ("SYSTEMS", "Systems Engineering", True, "#722ed1"),
           ("ADMIN", "Administration", False, "#fa8c16"), ("QUALITY", "Quality & Configuration", False, "#52c41a")]


# Shared phase template. A project that defines its own phases uses those instead, so non-software work is not forced onto SDLC labels.
PHASES = [("PLANNING", "Planning"), ("REQUIREMENTS", "Requirements"), ("DESIGN", "Design"), ("DEVELOPMENT", "Development"), ("TESTING", "Testing"), ("DEPLOYMENT", "Deployment / Release"), ("MAINTENANCE", "Maintenance")]


def _seed_phases(db) -> None:
    for i, (code, name) in enumerate(PHASES):
        db.add(PlanPhase(code=code, name=name, sort_order=i, weight=1.0))


def _seed_demo_plan(db, amca, orgs, people, items) -> None:
    """Fictional AMCA plan with engineering phases, built from the same models the API uses."""
    fcs, aws = orgs
    pgd, pe, priya, sanjay, dir_aws = people
    fcc, mcu = items
    today = date.today()
    phases = {code: PlanPhase(project_id=amca.id, code=code, name=name, sort_order=i, weight=w) for i, (code, name, w) in enumerate([("PRELIM", "Preliminary Design", 2.0), ("DETAIL", "Detailed Design", 3.0), ("QUAL", "Qualification", 3.0), ("PROD", "Production Readiness", 2.0)])}
    db.add_all(phases.values())
    db.flush()
    plan = ProjectPlan(project_id=amca.id, name="AMCA Avionics and Flight Control Plan", version_label="1.0", status="ACTIVE", owner_id=pgd.id, created_by_id=pgd.id, description="Demo plan (fictional).")
    db.add(plan)
    db.flush()
    pdr = Milestone(project_id=amca.id, plan_id=plan.id, code="PDR", name="Preliminary Design Review", status="ACHIEVED", start_date=today - timedelta(days=120), due_date=today - timedelta(days=40), achieved_date=today - timedelta(days=42), owner_id=pgd.id)
    cdr = Milestone(project_id=amca.id, plan_id=plan.id, code="CDR", name="Critical Design Review", status="IN_PROGRESS", start_date=today - timedelta(days=30), due_date=today + timedelta(days=12), owner_id=pgd.id)
    qtr = Milestone(project_id=amca.id, plan_id=plan.id, code="QTR", name="Qualification Test Readiness", status="PLANNED", due_date=today + timedelta(days=75), owner_id=dir_aws.id)
    db.add_all([pdr, cdr, qtr])
    wp_fcs = WorkPackage(plan_id=plan.id, project_id=amca.id, code="WP-FCS", name="Flight Control Computer", lead_org_unit_id=fcs.id, item_id=fcc.id, owner_id=pe.id, start_date=today - timedelta(days=120), end_date=today + timedelta(days=60))
    wp_aws = WorkPackage(plan_id=plan.id, project_id=amca.id, code="WP-AWS", name="Mission Computer", lead_org_unit_id=aws.id, item_id=mcu.id, owner_id=dir_aws.id, start_date=today - timedelta(days=30), end_date=today + timedelta(days=90))
    db.add_all([wp_fcs, wp_aws])
    db.flush()
    db.add(WorkPackageOrg(work_package_id=wp_fcs.id, org_unit_id=aws.id))
    act_prelim = PlanActivity(plan_id=plan.id, project_id=amca.id, work_package_id=wp_fcs.id, phase_id=phases["PRELIM"].id, title="FCC preliminary design", owner_id=pe.id, start_date=today - timedelta(days=120), end_date=today - timedelta(days=45), estimated_hours=200, status="COMPLETED", sort_order=0)
    act_design = PlanActivity(plan_id=plan.id, project_id=amca.id, work_package_id=wp_fcs.id, phase_id=phases["DETAIL"].id, title="FCC detailed design", owner_id=pe.id, start_date=today - timedelta(days=30), end_date=today + timedelta(days=10), estimated_hours=240, status="IN_PROGRESS", sort_order=1)
    act_qual = PlanActivity(plan_id=plan.id, project_id=amca.id, work_package_id=wp_fcs.id, phase_id=phases["QUAL"].id, title="FCC qualification preparation", owner_id=pe.id, start_date=today + timedelta(days=12), end_date=today + timedelta(days=60), estimated_hours=160, sort_order=2)
    act_mc = PlanActivity(plan_id=plan.id, project_id=amca.id, work_package_id=wp_aws.id, phase_id=phases["DETAIL"].id, title="Mission computer thermal design", owner_id=sanjay.id, start_date=today - timedelta(days=20), end_date=today + timedelta(days=15), estimated_hours=120, status="IN_PROGRESS", sort_order=3)
    db.add_all([act_prelim, act_design, act_qual, act_mc])
    db.flush()

    def task(n, title, act, who, org, start, due, hours, status="OPEN", reported=0.0):
        pct = {"COMPLETED": 100.0, "OPEN": 0.0}.get(status, reported)
        w = WorkItem(key=f"AMCA-{n}", title=title, status=status, project_id=amca.id, plan_id=plan.id, work_package_id=act.work_package_id, activity_id=act.id, item_id=fcc.id if org is fcs else mcu.id, org_unit_id=org.id, assignee_id=who.id, reporter_id=pe.id,
                     start_date=today + timedelta(days=start), due_date=today + timedelta(days=due), estimated_hours=hours, reported_progress=reported, progress=pct, actual_start=(today + timedelta(days=start)) if status != "OPEN" else None)
        if status == "COMPLETED":
            w.actual_end = today + timedelta(days=due)
            w.completed_at = utcnow()
        db.add(w)
        db.flush()
        db.add(WorkItemEvent(work_item_id=w.id, actor_id=pe.id, kind="CREATED", to_value="OPEN"))
        return w

    t1 = task(10, "FCC preliminary design report", act_prelim, priya, fcs, -110, -50, 200, "COMPLETED")
    t2 = task(11, "FCC control-law partitioning", act_design, priya, fcs, -28, -6, 80, "COMPLETED")
    t3 = task(12, "FCC hardware architecture description", act_design, pe, fcs, -5, 5, 100, "IN_PROGRESS", 60.0)
    t4 = task(13, "FCC interface data exchange with mission computer", act_design, priya, fcs, -2, 9, 60, "IN_PROGRESS", 25.0)
    t5 = task(14, "Mission computer thermal analysis", act_mc, sanjay, aws, -18, -3, 70, "IN_PROGRESS", 70.0)
    t6 = task(15, "Mission computer cooling concept review", act_mc, sanjay, aws, 0, 14, 50)
    t7 = task(16, "FCC qualification test plan", act_qual, pe, fcs, 13, 40, 90)
    db.add_all([TaskDependency(successor_id=t2.id, predecessor_id=t1.id, dep_type="FS", created_by_id=pe.id), TaskDependency(successor_id=t3.id, predecessor_id=t2.id, dep_type="FS", created_by_id=pe.id),
                TaskDependency(successor_id=t4.id, predecessor_id=t5.id, dep_type="SS", lag_days=2, created_by_id=pe.id), TaskDependency(successor_id=t6.id, predecessor_id=t5.id, dep_type="FS", created_by_id=dir_aws.id),
                TaskDependency(successor_id=t7.id, predecessor_id=t3.id, dep_type="FS", lag_days=3, created_by_id=pe.id)])
    db.add_all([TaskChecklistItem(work_item_id=t3.id, text="Reviewed against the FCC specification", sort_order=0), TaskChecklistItem(work_item_id=t3.id, text="Interface list agreed with AWS", sort_order=1)])
    db.add(TaskParticipant(work_item_id=t3.id, user_id=priya.id, role="REVIEWER"))
    t3.milestone_id = cdr.id
    db.flush()


def _seed_demo_requirements(db, amca, pe, priya, reviewer, approver, fcc, task_key) -> None:
    """Fictional requirements taken through the same rules the API applies."""
    from app.services import requirements as rq

    src = RequirementSource(project_id=amca.id, name="FCC System Requirements Specification", key_prefix="AMCA-FCC", created_by_id=pe.id)
    db.add(src)
    db.flush()

    def req(n, title, status, acceptance, parent=None, priority="HIGH"):
        desc = f"{title}. Demo requirement (fictional)."
        r = Requirement(project_id=amca.id, source_id=src.id, parent_id=parent.id if parent else None, key=f"AMCA-FCC-{n:04d}", title=title, description=desc, acceptance_criteria=acceptance, req_type="FUNCTIONAL", priority=priority, status=status, owner_id=pe.id, item_id=fcc.id,
                        content_sha256=rq.content_hash(title, desc, acceptance, "FUNCTIONAL", priority))
        db.add(r)
        db.flush()
        rq.write_revision(db, r, pe.id, "Created")
        rq.add_event(db, r, "CREATED", pe.id, to=status)
        return r

    r1 = req(1, "The FCC shall provide triplex redundant control channels", "BASELINED", "Fault injection shows continued control after one channel fails.")
    r2 = req(2, "The FCC shall detect a failed channel within 50 ms", "APPROVED", "Timing test shows detection within 50 ms in every failure mode.", parent=r1)
    r3 = req(3, "The FCC shall report channel status to the mission computer", "UNDER_REVIEW", "Interface test shows status messages at the specified rate.", parent=r1, priority="MEDIUM")
    r4 = req(4, "The FCC shall log all channel failures for maintenance", "UNDER_ANALYSIS", "", priority="LOW")
    req(5, "The FCC shall support in-flight software reload", "DRAFT", "", priority="LOW")
    db.add_all([RequirementLink(from_id=r3.id, to_id=r2.id, link_type="depends_on", created_by_id=pe.id), RequirementLink(from_id=r4.id, to_id=r2.id, link_type="derived_from", created_by_id=pe.id)])
    for r in (r1, r2):
        db.add(RequirementReview(requirement_id=r.id, revision=1, content_sha256=r.content_sha256, cycle=1, reviewer_id=approver.id, role="APPROVER", status="APPROVED", decided_at=utcnow()))
    db.add(RequirementReview(requirement_id=r3.id, revision=1, content_sha256=r3.content_sha256, cycle=1, reviewer_id=reviewer.id, role="REVIEWER"))
    db.add(RequirementReview(requirement_id=r3.id, revision=1, content_sha256=r3.content_sha256, cycle=1, reviewer_id=approver.id, role="APPROVER"))
    base = RequirementBaseline(project_id=amca.id, seq=1, label="FCC requirements at PDR", reason="Agreed at the preliminary design review (demo).", sha256="", created_by_id=pe.id)
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
        fcs = _org(db, "FCS", "Flight Control Systems Directorate", "DIRECTORATE", ada)
        aws = _org(db, "AWS", "Avionics & Weapon Systems Directorate", "DIRECTORATE", ada)
        stru = _org(db, "STR", "Structures & Materials Directorate", "DIRECTORATE", ada)
        ict = _org(db, "ICT", "Information & Communication Technology Directorate", "DIRECTORATE", ada)
        qa = _org(db, "QA", "Quality Assurance & Configuration Mgmt", "DIRECTORATE", ada)
        adm = _org(db, "ADMIN", "Administration Directorate", "DIRECTORATE", ada)
        fcs_cl = _org(db, "FCS-CL", "Control Law Department", "DEPARTMENT", fcs)
        fcs_act = _org(db, "FCS-ACT", "Actuation & Hydraulics Department", "DEPARTMENT", fcs)
        aws_mc = _org(db, "AWS-MC", "Mission Computer Department", "DEPARTMENT", aws)
        aws_ds = _org(db, "AWS-DS", "Display Systems Department", "DEPARTMENT", aws)
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
        td = user("td.menon", "Kavita Menon", "Technical Director", fcs, "E1002")
        dir_aws = user("dir.iyer", "Rajesh Iyer", "Director, AWS", aws, "E1003")
        cm = user("cm.sharma", "Neha Sharma", "Configuration Manager", qa, "E1004")
        pe = user("pe.kumar", "Vikram Kumar", "Project Engineer", fcs_cl, "E2001")
        priya = user("eng.priya", "Priya Nair", "Scientist 'D'", fcs_cl, "E2002")
        das = user("chk.das", "Anil Das", "Scientist 'E'", fcs_act, "E2003")
        joshi = user("rev.joshi", "Meera Joshi", "Scientist 'F'", fcs, "E2004")
        sanjay = user("eng.sanjay", "Sanjay Patil", "Scientist 'C'", aws_mc, "E2005")
        fatima = user("chk.fatima", "Fatima Sheikh", "Scientist 'E'", aws_ds, "E2006")
        rohit = user("qa.verma", "Rohit Verma", "QA Manager", qa, "E2007")
        deepa = user("proc.krishnan", "Deepa Krishnan", "Process Owner", qa, "E2008")
        suresh = user("adm.babu", "Suresh Babu", "Administrative Officer", adm_proc, "E3001")
        lakshmi = user("adm.head", "Lakshmi Rao", "Head, Administration", adm, "E3002")
        rakesh = user("sw.rakesh", "Rakesh Gupta", "Software Lead", ict_se, "E2009")

        def grant(u, role, scope_type="GLOBAL", scope=None):
            db.add(RoleAssignment(user_id=u.id, role_id=roles[role].id, scope_type=scope_type, scope_id=scope.id if scope is not None else None, granted_by_id=admin.id))

        db.flush()
        # ---- projects & breakdown
        amca = Project(code="AMCA", name="Advanced Medium Combat Aircraft", programme="AMCA Programme", status="ACTIVE", lead_org_unit_id=hd.id, color="#1677ff", classification="RESTRICTED", start_date=date(2024, 4, 1), end_date=date(2034, 3, 31))
        mk1 = Project(code="MK1", name="Mk1 Upgrade Programme", programme="LCA Programme", status="ACTIVE", lead_org_unit_id=hd.id, color="#fa541c", classification="RESTRICTED", start_date=date(2023, 1, 1))
        db.add_all([amca, mk1])
        db.flush()
        lv = {}
        for i, (c, n, color, icon) in enumerate([("AIRCRAFT", "Aircraft", "#1677ff", "aircraft"), ("SYSTEM", "System", "#722ed1", "system"), ("SUBSYSTEM", "Subsystem", "#13c2c2", "subsystem"), ("LRU", "LRU", "#fa8c16", "lru"), ("SRU", "SRU / Module", "#8c8c8c", "module")], 1):
            lv[c] = HierarchyLevel(project_id=amca.id, level_no=i, code=c, name=n, color=color, icon=icon)
            db.add(lv[c])
        lv2 = {}
        for i, (c, n, color, icon) in enumerate([("AIRCRAFT", "Aircraft", "#1677ff", "aircraft"), ("LRU", "LRU", "#fa8c16", "lru"), ("ECFM", "ECFM", "#eb2f96", "module")], 1):
            lv2[c] = HierarchyLevel(project_id=mk1.id, level_no=i, code=c, name=n, color=color, icon=icon)
            db.add(lv2[c])
        for o, part in [(hd, "LEAD"), (fcs, "CONTRIBUTOR"), (aws, "CONTRIBUTOR"), (stru, "CONTRIBUTOR"), (qa, "OVERSIGHT")]:
            db.add(ProjectOrgAssignment(project_id=amca.id, org_unit_id=o.id, participation=part))
        db.flush()

        ac = _item(db, amca, lv, None, "AIRCRAFT", "AMCA-AC", "AMCA Air Vehicle", hd, domain=dom["SYSTEMS"], phase="DETAILED_DESIGN")
        fcs_sys = _item(db, amca, lv, ac, "SYSTEM", "FCS", "Flight Control System", fcs, domain=dom["HARDWARE"])
        fbw = _item(db, amca, lv, fcs_sys, "SUBSYSTEM", "FCS-FBW", "Fly-by-Wire Subsystem", fcs_cl, domain=dom["HARDWARE"])
        fcc = _item(db, amca, lv, fbw, "LRU", "FCS-FCC", "Digital Flight Control Computer", fcs_cl, "AMCA-FCC-1000", dom["HARDWARE"])
        _item(db, amca, lv, fcc, "SRU", "FCS-FCC-PSU", "FCC Power Supply Module", fcs_cl, "AMCA-FCC-1010", dom["HARDWARE"])
        _item(db, amca, lv, fcc, "SRU", "FCS-FCC-OFP", "FCC Operational Flight Program", ict_se, "AMCA-FCC-SW01", dom["SOFTWARE"])
        act = _item(db, amca, lv, fbw, "LRU", "FCS-IAP", "Integrated Actuator Package", fcs_act, "AMCA-IAP-2000", dom["HARDWARE"])
        air = _item(db, amca, lv, fcs_sys, "SUBSYSTEM", "FCS-ADS", "Air Data Subsystem", fcs, domain=dom["HARDWARE"])
        adc = _item(db, amca, lv, air, "LRU", "FCS-ADC", "Air Data Computer", fcs, "AMCA-ADC-3000", dom["HARDWARE"])
        avs = _item(db, amca, lv, ac, "SYSTEM", "AVS", "Avionics System", aws, domain=dom["HARDWARE"])
        mcs = _item(db, amca, lv, avs, "SUBSYSTEM", "AVS-MCS", "Mission Computing Subsystem", aws_mc, domain=dom["HARDWARE"])
        mcu = _item(db, amca, lv, mcs, "LRU", "AVS-MCU", "Mission Computer Unit", aws_mc, "AMCA-MCU-4000", dom["HARDWARE"])
        dsp = _item(db, amca, lv, avs, "SUBSYSTEM", "AVS-CDS", "Cockpit Display Subsystem", aws_ds, domain=dom["HARDWARE"])
        lad = _item(db, amca, lv, dsp, "LRU", "AVS-LAD", "Large Area Display", aws_ds, "AMCA-LAD-5000", dom["HARDWARE"])
        st = _item(db, amca, lv, ac, "SYSTEM", "STR", "Airframe Structure", stru, domain=dom["HARDWARE"], phase="CONCEPT")
        _item(db, amca, lv, st, "SUBSYSTEM", "STR-WING", "Wing Subsystem", stru, domain=dom["HARDWARE"], phase="CONCEPT")
        _item(db, amca, lv, ac, "SYSTEM", "PRP", "Propulsion System", hd, domain=dom["HARDWARE"], phase="CONCEPT")
        mk_ac = _item(db, mk1, lv2, None, "AIRCRAFT", "MK1-AC", "Mk1 Air Vehicle", hd, domain=dom["SYSTEMS"])
        rdr = _item(db, mk1, lv2, mk_ac, "LRU", "MK1-RDR", "Multi-mode Radar LRU", aws, "MK1-RDR-100", dom["HARDWARE"])
        _item(db, mk1, lv2, rdr, "ECFM", "MK1-RDR-ECFM01", "Radar Signal Processor ECFM", aws_mc, "MK1-RDR-101", dom["HARDWARE"])
        fcc.technical_owner_id = pe.id

        # ---- role assignments (scoped)
        grant(pgd, "PGD"); grant(pgd, "HD_OVERSIGHT"); grant(pgd, "APPROVER", "PROJECT", amca)
        grant(td, "TD", "PROJECT", amca); grant(td, "APPROVER", "ORG_UNIT", fcs); grant(td, "REVIEWER", "PROJECT", amca)
        grant(dir_aws, "DIR_HEAD", "ORG_UNIT", aws); grant(dir_aws, "APPROVER", "ORG_UNIT", aws); grant(dir_aws, "REVIEWER", "PROJECT", amca)
        grant(cm, "RELEASE_AUTH"); grant(cm, "HD_OVERSIGHT")
        grant(pe, "PE", "PROJECT", amca); grant(pe, "TEAM_MEMBER", "ORG_UNIT", fcs)
        grant(priya, "TEAM_MEMBER", "ORG_UNIT", fcs)
        grant(das, "CHECKER", "ORG_UNIT", fcs); grant(das, "TEAM_MEMBER", "ORG_UNIT", fcs_act)
        grant(joshi, "REVIEWER", "PROJECT", amca); grant(joshi, "DEPT_HEAD", "ORG_UNIT", fcs)
        grant(sanjay, "TEAM_MEMBER", "ORG_UNIT", aws)
        grant(fatima, "CHECKER", "ORG_UNIT", aws); grant(fatima, "CHECKER", "ORG_UNIT", fcs)
        grant(rohit, "QA_AUDITOR")
        grant(deepa, "PROCESS_ADMIN")
        grant(suresh, "TEAM_MEMBER", "ORG_UNIT", adm)
        grant(lakshmi, "APPROVER", "ORG_UNIT", adm); grant(lakshmi, "DIR_HEAD", "ORG_UNIT", adm)
        grant(rakesh, "TEAM_MEMBER", "ORG_UNIT", ict); grant(rakesh, "REVIEWER", "PROJECT", amca)
        for u in (pgd, td, dir_aws, pe, priya, das, joshi, sanjay, fatima, rakesh, cm):
            db.add(ProjectMember(project_id=amca.id, user_id=u.id))
        db.flush()

        # ---- document types
        dts = {}
        for code, name, cat, pattern, tmpl, sig, levels, color, ext in DOC_TYPES:
            dts[code] = DocumentType(code=code, name=name, category=cat, numbering_pattern=pattern, default_template=tmpl, requires_signature=sig, applicable_levels=levels, color=color, allowed_extensions=ext)
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
        def new(u, t, title, item=None, project=amca, org=None, cls="RESTRICTED"):
            return docsvc.create_document(db, u, type_id=dts[t].id, title=title, project_id=project.id if project else None, item_id=item.id if item else None, owner_org_unit_id=org.id if org else None,
                                          domain_id=None, classification=cls, description=None, keywords=None, content=None, from_template=True)

        def pending(user):
            return db.execute(select(WorkflowTask).where(WorkflowTask.assignee_id == user.id, WorkflowTask.status == "PENDING").order_by(WorkflowTask.created_at.desc())).scalars().first()

        def cur(doc):
            from app.models import DocumentRevision

            return db.get(DocumentRevision, doc.current_revision_id)

        ok = {c: True for c in ENG_4STEP["stages"][1]["checklist"]}
        # 1) FCC Specification — fully released
        d1 = new(pe, "SPEC", "Digital Flight Control Computer — Equipment Specification", fcc)
        db.flush()
        wf.start(db, pe, d1, cur(d1), {"check": [str(das.id)], "review": [str(joshi.id)], "approve": [str(td.id)]}, "Initial issue for release")
        wf.decide(db, das, pending(das).id, "approve", "Checked. Minor editorial remarks addressed.", ok)
        wf.decide(db, joshi, pending(joshi).id, "approve", "Reviewed — concur.")
        wf.decide(db, td, pending(td).id, "approve", "Approved for release.")
        for u in (pe, das, joshi, td):
            wf.sign(db, u, pending(u).id, s.demo_password)
        relsvc.release_revision(db, cm, d1, cur(d1), "Initial release")
        # 2) FCC ICD — waiting at Checker
        d2 = new(priya, "ICD", "FCC to Actuator Package Interface Control Document", fcc)
        db.flush()
        wf.start(db, priya, d2, cur(d2), {"check": [str(das.id)], "review": [str(joshi.id), str(rakesh.id)], "approve": [str(td.id)]})
        # 3) FCC SRS — changes requested
        d3 = new(priya, "SRS", "FCC Operational Flight Program — Software Requirements", fcc)
        db.flush()
        wf.start(db, priya, d3, cur(d3), {"check": [str(fatima.id)], "review": [str(rakesh.id)], "approve": [str(td.id)]})
        wf.decide(db, fatima, pending(fatima).id, "request_changes", "Section 3.2 timing requirements lack tolerance values; please add derived requirement IDs.")
        # 4) MCU spec — approved, awaiting release
        d4 = new(sanjay, "SPEC", "Mission Computer Unit — Equipment Specification", mcu)
        db.flush()
        wf.start(db, sanjay, d4, cur(d4), {"check": [str(fatima.id)], "review": [str(joshi.id)], "approve": [str(dir_aws.id)]})
        wf.decide(db, fatima, pending(fatima).id, "approve", "OK", ok)
        wf.decide(db, joshi, pending(joshi).id, "approve", "OK")
        wf.decide(db, dir_aws, pending(dir_aws).id, "approve", "Approved")
        for u in (sanjay, fatima, joshi, dir_aws):
            wf.sign(db, u, pending(u).id, s.demo_password)
        # 5) Draft docs
        new(pe, "DDD", "Flight Control Computer — Hardware Design Description", fcc)
        new(das, "ATP", "Integrated Actuator Package — Acceptance Test Procedure", act)
        new(pe, "SPEC", "Air Data Computer — Equipment Specification", adc)
        d6 = new(sanjay, "ICD", "Large Area Display — Video Interface ICD", lad)
        db.flush()
        wf.start(db, sanjay, d6, cur(d6), {"check": [str(fatima.id)], "review": [str(joshi.id)], "approve": [str(dir_aws.id)]})
        wf.decide(db, fatima, pending(fatima).id, "approve", "Checked", ok)
        # 6) Programme-level document (Head Directorate) in parallel concurrence
        d7 = new(pe, "PMP", "AMCA Programme Management Plan — Phase 2", ac, org=hd)
        db.flush()
        wf.start(db, pe, d7, cur(d7), {"concurrence": [str(joshi.id), str(dir_aws.id), str(rakesh.id)]})
        # 7) Non-engineering: office order released via auto-release
        d8 = new(suresh, "ADMN", "Office Order — Constitution of AMCA Design Review Board", None, project=None, org=adm, cls="UNCLASSIFIED")
        db.flush()
        wf.start(db, suresh, d8, cur(d8), {"approve": [str(lakshmi.id)]})
        wf.decide(db, lakshmi, pending(lakshmi).id, "approve", "Approved.")
        d9 = new(suresh, "PRQ", "Procurement Request — Environmental Test Chamber", None, project=amca, org=adm_proc, cls="UNCLASSIFIED")
        db.flush()
        wf.start(db, suresh, d9, cur(d9), {"approve": [str(lakshmi.id)]})
        new(pe, "MOM", "Minutes — FCS Preliminary Design Review", fcs_sys)

        # ---- work items (engineering + non-engineering)
        today = date.today()
        for i, (title, kind, status, prio, item, who, due, org) in enumerate([
            ("Close PDR action items for FCC", "ACTION", "IN_PROGRESS", "HIGH", fcc, pe, today + timedelta(days=5), fcs),
            ("Update FCC ICD after actuator re-allocation", "TASK", "OPEN", "MEDIUM", fcc, priya, today + timedelta(days=12), fcs_cl),
            ("Thermal analysis — Mission Computer Unit", "TASK", "ON_HOLD", "HIGH", mcu, sanjay, today - timedelta(days=2), aws_mc),
            ("CDR readiness review — Avionics", "MILESTONE", "OPEN", "CRITICAL", avs, dir_aws, today + timedelta(days=30), aws),
            ("Raise ECR for air-data probe relocation", "CHANGE_REQUEST", "OPEN", "MEDIUM", adc, pe, today + timedelta(days=9), fcs),
            ("Arrange Design Review Board meeting hall & logistics", "TASK", "IN_PROGRESS", "LOW", None, suresh, today + timedelta(days=3), adm),
            ("Vendor quotation comparison — environmental chamber", "TASK", "OPEN", "MEDIUM", None, suresh, today + timedelta(days=7), adm_proc),
        ], 1):
            db.add(WorkItem(key=f"{'AMCA' if item else 'TSK'}-{i}", title=title, kind=kind, status=status, priority=prio, project_id=amca.id if item else None, item_id=item.id if item else None,
                            assignee_id=who.id, reporter_id=pgd.id if item else lakshmi.id, due_date=due, org_unit_id=org.id, progress=40 if status == "IN_PROGRESS" else 0, reported_progress=40 if status == "IN_PROGRESS" else 0))
        from app.models import NumberSequence

        db.flush()
        _seed_phases(db)
        _seed_demo_plan(db, amca, (fcs, aws), (pgd, pe, priya, sanjay, dir_aws), (fcc, mcu))
        db.add(NumberSequence(key="wi:AMCA", next_value=20))
        _seed_demo_requirements(db, amca, pe, priya, joshi, td, fcc, "AMCA-12")
        db.add(NumberSequence(key="req:AMCA-FCC", next_value=6))
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
            dts[code] = DocumentType(code=code, name=name, category=cat, numbering_pattern=pattern, default_template=tmpl, requires_signature=sig, applicable_levels=levels, color=color, allowed_extensions=ext)
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
    from app.core.db import Base, engine
    import app.models  # noqa: F401

    Base.metadata.create_all(engine)
    run()
    print("Seed complete.")
