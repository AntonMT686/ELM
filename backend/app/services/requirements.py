"""Requirement rules (architecture §10): configurable lifecycle, revisions, hash-bound review, baselines, impact, RTM."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import defaultdict

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import AppError, Forbidden
from app.models import (
    Document,
    EngineeringItem,
    OrgUnit,
    Requirement,
    RequirementBaseline,
    RequirementBaselineItem,
    RequirementDocument,
    RequirementEvent,
    RequirementLink,
    RequirementReview,
    RequirementRevision,
    RequirementWorkItem,
    SystemSetting,
    User,
    WorkItem,
)
from app.services.authz import Principal
from app.services.notify import notify
from app.services.numbering import next_seq
from app.services.planning import can_view_project
from app.services.task_lifecycle import validate_lifecycle

LINK_TYPES = ("depends_on", "derived_from", "implements", "related_to", "conflicts_with")
# Links that make the "from" requirement dependent on the "to" one, so a change to "to" reaches "from".
PROPAGATING = ("depends_on", "derived_from", "implements")
CONTENT_FIELDS = ("title", "description", "acceptance_criteria", "req_type", "priority")
# The code relies on these meanings. Labels, extra states and manual moves stay configurable around them.
CORE_STATES = {"DRAFT", "UNDER_ANALYSIS", "UNDER_REVIEW", "APPROVED", "REJECTED", "BASELINED"}
LOCKED_WHILE = {"UNDER_REVIEW"}
RELEASED_STATES = {"APPROVED", "BASELINED"}
OWNER_MANAGER = ["owner", "manager"]
ACTORS = {"owner", "manager", "system"}

DEFAULT_LIFECYCLE: dict = {
    "states": [
        {"code": "DRAFT", "label": "Draft", "category": "INITIAL", "color": "gray"},
        {"code": "UNDER_ANALYSIS", "label": "Under analysis", "category": "ACTIVE", "color": "blue"},
        {"code": "UNDER_REVIEW", "label": "Under review", "category": "ACTIVE", "color": "violet"},
        {"code": "APPROVED", "label": "Approved", "category": "ACTIVE", "color": "cyan"},
        {"code": "REJECTED", "label": "Rejected", "category": "ACTIVE", "color": "red"},
        {"code": "DEFERRED", "label": "Deferred", "category": "HOLD", "color": "yellow"},
        {"code": "BASELINED", "label": "Baselined", "category": "DONE", "color": "teal"},
    ],
    "transitions": [
        {"from": "DRAFT", "to": "UNDER_ANALYSIS", "label": "Start analysis", "actors": OWNER_MANAGER},
        {"from": "DRAFT", "to": "DEFERRED", "label": "Defer", "actors": OWNER_MANAGER, "reason": True},
        {"from": "DEFERRED", "to": "DRAFT", "label": "Bring back", "actors": OWNER_MANAGER},
        {"from": "UNDER_ANALYSIS", "to": "UNDER_REVIEW", "label": "Submit for review", "actors": OWNER_MANAGER},
        {"from": "UNDER_REVIEW", "to": "UNDER_ANALYSIS", "label": "Withdraw from review", "actors": OWNER_MANAGER, "reason": True},
        {"from": "REJECTED", "to": "UNDER_ANALYSIS", "label": "Rework", "actors": OWNER_MANAGER},
        # Moves made by the system: reviewer decisions, baselining, and editing approved content.
        {"from": "UNDER_REVIEW", "to": "APPROVED", "label": "Approved by reviewers", "actors": ["system"]},
        {"from": "UNDER_REVIEW", "to": "REJECTED", "label": "Rejected by a reviewer", "actors": ["system"]},
        {"from": "APPROVED", "to": "BASELINED", "label": "Baselined", "actors": ["system"]},
        {"from": "APPROVED", "to": "UNDER_ANALYSIS", "label": "Changed after approval", "actors": ["system"]},
        {"from": "BASELINED", "to": "UNDER_ANALYSIS", "label": "Changed after baseline", "actors": ["system"]},
    ],
}
DEFAULT_MANDATORY = ["title", "description", "req_type", "priority", "acceptance_criteria", "source_id", "owner_id"]


def _setting(db: Session, key: str):
    row = db.get(SystemSetting, key)
    if not row:
        return None
    try:
        return json.loads(row.value)
    except ValueError:
        return None


def get_lifecycle(db: Session, project_id: uuid.UUID | None = None) -> dict:
    if project_id:
        own = _setting(db, f"requirement.lifecycle.{project_id}")
        if own:
            return own
    return _setting(db, "requirement.lifecycle") or DEFAULT_LIFECYCLE


def mandatory_fields(db: Session) -> list[str]:
    return _setting(db, "requirement.mandatory_fields") or DEFAULT_MANDATORY


def validate_requirement_lifecycle(lc: dict) -> list[str]:
    errors = validate_lifecycle(lc, actors=ACTORS)
    missing = CORE_STATES - {s.get("code") for s in lc.get("states") or []}
    if missing:
        errors.append(f"These states are required: {', '.join(sorted(missing))}.")
    return errors


def natural_key(key: str) -> list:
    """REQ2 before REQ10, and 6.1.2 before 6.10: IDs read as numbers, which SQL ordering cannot do portably."""
    return [(0, int(p), "") if p.isdigit() else (1, 0, p.lower()) for p in re.split(r"(\d+)", key) if p]


def content_hash(title, description, acceptance, req_type, priority) -> str:
    text = json.dumps([title or "", description or "", acceptance or "", req_type or "", priority or ""], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def hash_of(r) -> str:
    return content_hash(r.title, r.description, r.acceptance_criteria, r.req_type, r.priority)


def can_view(db: Session, p: Principal, r: Requirement) -> bool:
    if can_view_project(db, p, r.project_id) or r.owner_id == p.id:
        return True
    return db.execute(select(RequirementReview.id).where(RequirementReview.requirement_id == r.id, RequirementReview.reviewer_id == p.id)).first() is not None


def _path(db: Session, model, oid) -> str | None:
    o = db.get(model, oid) if oid else None
    return o.path if o else None


def has_scope(db: Session, p: Principal, perm: str, r: Requirement) -> bool:
    return p.has(perm, project_id=r.project_id, org_path=_path(db, OrgUnit, r.org_unit_id), item_path=_path(db, EngineeringItem, r.item_id))


def can_edit(db: Session, p: Principal, r: Requirement) -> bool:
    return r.owner_id == p.id or has_scope(db, p, "req.edit", r)


def next_key(db: Session, prefix: str) -> str:
    return f"{prefix}-{next_seq(db, 'req:' + prefix):04d}"


def add_event(db: Session, r: Requirement, kind: str, actor: uuid.UUID | None, frm=None, to=None, comment=None, at=None) -> None:
    db.add(RequirementEvent(requirement_id=r.id, actor_id=actor, kind=kind, from_value=frm, to_value=to, comment=comment, at=at or utcnow()))


def write_revision(db: Session, r: Requirement, actor: uuid.UUID | None, reason: str | None = None) -> None:
    db.add(RequirementRevision(requirement_id=r.id, revision=r.revision, title=r.title, description=r.description, acceptance_criteria=r.acceptance_criteria, req_type=r.req_type, priority=r.priority, content_sha256=r.content_sha256, change_reason=reason, created_by_id=actor))


def apply_content(db: Session, r: Requirement, changes: dict, *, actor: uuid.UUID, reason: str | None) -> bool:
    """Apply a content edit. Returns True when approved or baselined content changed: that opens a new revision and
    voids approval, while the old revision and any baseline holding it stay as they were (architecture §19.2)."""
    if r.status in LOCKED_WHILE:
        raise AppError("A requirement under review cannot be edited. Withdraw it from review first.", code="LOCKED")
    before = hash_of(r)
    for k, v in changes.items():
        setattr(r, k, v)
    after = hash_of(r)
    r.content_sha256 = after
    r.version += 1
    if before == after:
        return False
    if r.status in RELEASED_STATES:
        if not (reason or "").strip():
            raise AppError("A reason is required to change approved or baselined content.", code="REASON_REQUIRED")
        old_status = r.status
        r.revision += 1
        r.status = "UNDER_ANALYSIS"
        write_revision(db, r, actor, reason)
        add_event(db, r, "REVISION", actor, frm=old_status, to="UNDER_ANALYSIS", comment=reason)
        return True
    row = db.execute(select(RequirementRevision).where(RequirementRevision.requirement_id == r.id, RequirementRevision.revision == r.revision)).scalar_one_or_none()
    if row is None:
        write_revision(db, r, actor, reason)
    else:  # still in draft: nobody has decided on this revision, so it can change
        row.title, row.description, row.acceptance_criteria, row.req_type, row.priority, row.content_sha256 = r.title, r.description, r.acceptance_criteria, r.req_type, r.priority, after
    return False


def submit_blockers(db: Session, r: Requirement) -> list[str]:
    labels = {"title": "title", "description": "description", "req_type": "type", "priority": "priority", "acceptance_criteria": "acceptance criteria", "source_id": "source", "owner_id": "owner"}
    return [f"Missing: {labels.get(f, f)}." for f in mandatory_fields(db) if not getattr(r, f, None)]


def current_cycle(db: Session, r: Requirement) -> int:
    rows = db.execute(select(RequirementReview.cycle).where(RequirementReview.requirement_id == r.id)).scalars().all()
    return max(rows) if rows else 0


def _cancel_pending(db: Session, r: Requirement) -> None:
    for row in db.execute(select(RequirementReview).where(RequirementReview.requirement_id == r.id, RequirementReview.status == "PENDING")).scalars():
        row.status = "CANCELLED"


def submit_for_review(db: Session, r: Requirement, *, actor: uuid.UUID, reviewers: list[uuid.UUID], approvers: list[uuid.UUID]) -> None:
    blockers = submit_blockers(db, r)
    if not approvers:
        blockers.append("Choose at least one approver.")
    for uid in {*reviewers, *approvers}:
        u = db.get(User, uid)
        if not u or not u.is_active:
            blockers.append("Every reviewer and approver must be an active user.")
        if uid == r.owner_id or uid == actor:
            blockers.append("The owner or submitter of a requirement cannot review or approve it.")
    if blockers:
        raise AppError("This requirement cannot be submitted yet.", code="GATE_BLOCKED", details={"errors": sorted(set(blockers))})
    cycle = current_cycle(db, r) + 1
    r.content_sha256 = hash_of(r)
    for role, people in (("REVIEWER", reviewers), ("APPROVER", approvers)):
        for uid in dict.fromkeys(people):
            db.add(RequirementReview(requirement_id=r.id, revision=r.revision, content_sha256=r.content_sha256, cycle=cycle, reviewer_id=uid, role=role))
    db.flush()
    first = reviewers or approvers
    for uid in dict.fromkeys(first):
        notify(db, uid, "requirement.review", f"Review requested: {r.key}", r.title[:300], link=f"/requirements/{r.project_id}?open={r.id}")


def transition(db: Session, r: Requirement, to: str, *, actor: uuid.UUID, is_manager: bool, comment: str | None = None, reviewers=None, approvers=None) -> str:
    lc = get_lifecycle(db, r.project_id)
    states = {s["code"]: s for s in lc["states"]}
    if to not in states:
        raise AppError(f"{to} is not a state in this lifecycle.", code="INVALID_STATE")
    rule = next((t for t in lc["transitions"] if t["from"] == r.status and t["to"] == to), None)
    if rule is None:
        raise AppError(f"A requirement cannot move from {states.get(r.status, {}).get('label', r.status)} to {states[to]['label']}.", code="INVALID_TRANSITION", details={"allowed": sorted(t["to"] for t in lc["transitions"] if t["from"] == r.status and "system" not in t["actors"])})
    if "system" in rule["actors"]:
        raise AppError(f"“{rule.get('label')}” happens through reviewer decisions, baselining or editing, not directly.", code="INVALID_TRANSITION")
    mine = {"owner"} if r.owner_id == actor else set()
    if is_manager:
        mine.add("manager")
    if not mine & set(rule["actors"]):
        raise Forbidden(f"You are not allowed to perform “{rule.get('label') or to}” on this requirement.")
    if rule.get("reason") and not (comment or "").strip():
        raise AppError("A reason is required for this action.", code="REASON_REQUIRED")
    if to == "UNDER_REVIEW":
        submit_for_review(db, r, actor=actor, reviewers=reviewers or [], approvers=approvers or [])
    if r.status == "UNDER_REVIEW":
        _cancel_pending(db, r)
    old = r.status
    r.status = to
    r.version += 1
    add_event(db, r, "STATUS", actor, frm=old, to=to, comment=(comment or "").strip() or None)
    return old


def decide(db: Session, r: Requirement, *, user_id: uuid.UUID, decision: str, comment: str | None) -> str:
    """Record one reviewer's decision. Reviewers decide first, then approvers. Any rejection ends the cycle."""
    if r.status != "UNDER_REVIEW":
        raise AppError("This requirement is not under review.", code="INVALID_STATE")
    rows = db.execute(select(RequirementReview).where(RequirementReview.requirement_id == r.id, RequirementReview.cycle == current_cycle(db, r))).scalars().all()
    pending = [x for x in rows if x.status == "PENDING"]
    mine = [x for x in pending if x.reviewer_id == user_id]
    if not mine:
        raise Forbidden("You have no pending review on this requirement.")
    reviewers_open = [x for x in pending if x.role == "REVIEWER"]
    row = next((x for x in mine if x.role == "REVIEWER"), None) or mine[0]
    if row.role == "APPROVER" and reviewers_open:
        raise AppError("Approval opens after all reviewers have decided.", code="GATE_BLOCKED")
    if row.content_sha256 != hash_of(r) or row.revision != r.revision:
        raise AppError("The content no longer matches the revision sent for review.", code="HASH_MISMATCH")
    if decision == "REJECTED" and not (comment or "").strip():
        raise AppError("A reason is required to reject a requirement.", code="REASON_REQUIRED")
    row.status = decision
    row.comment = (comment or "").strip() or None
    row.decided_at = utcnow()
    add_event(db, r, "DECISION", user_id, to=f"{row.role}:{decision}", comment=row.comment)
    old = r.status
    if decision == "REJECTED":
        _cancel_pending(db, r)
        r.status = "REJECTED"
    else:
        remaining = [x for x in pending if x.id != row.id]
        if not remaining:
            r.status = "APPROVED"
        elif row.role == "REVIEWER" and not [x for x in remaining if x.role == "REVIEWER"]:
            for x in remaining:
                notify(db, x.reviewer_id, "requirement.review", f"Approval requested: {r.key}", r.title[:300], link=f"/requirements/{r.project_id}?open={r.id}")
    if r.status != old:
        r.version += 1
        add_event(db, r, "STATUS", user_id, frm=old, to=r.status, comment=row.comment)
        if r.owner_id and r.owner_id != user_id:
            notify(db, r.owner_id, "requirement.status", f"{r.key}: {r.status.replace('_', ' ').lower()}", row.comment or r.title[:300], link=f"/requirements/{r.project_id}?open={r.id}")
    return r.status


def seal_items(items: list[RequirementBaselineItem]) -> str:
    text = json.dumps(sorted([i.key, i.revision, i.content_sha256] for i in items), separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def baseline_item(baseline_id: uuid.UUID, r: Requirement) -> RequirementBaselineItem:
    return RequirementBaselineItem(baseline_id=baseline_id, requirement_id=r.id, key=r.key, revision=r.revision, title=r.title, description=r.description, acceptance_criteria=r.acceptance_criteria, req_type=r.req_type, priority=r.priority, content_sha256=r.content_sha256)


def compare_items(old: list[RequirementBaselineItem], new: list[dict]) -> dict:
    """Baseline against another baseline or the live set. Compared by requirement key: added, changed, removed."""
    a = {i.key: i for i in old}
    b = {x["key"]: x for x in new}
    changed = [{"key": k, "from_revision": a[k].revision, "to_revision": b[k]["revision"], "title": b[k]["title"], "old_title": a[k].title} for k in sorted(a.keys() & b.keys()) if a[k].content_sha256 != b[k]["content_sha256"]]
    return {"added": [{"key": k, "title": b[k]["title"], "revision": b[k]["revision"]} for k in sorted(b.keys() - a.keys())], "removed": [{"key": k, "title": a[k].title, "revision": a[k].revision} for k in sorted(a.keys() - b.keys())], "changed": changed, "unchanged": len(a.keys() & b.keys()) - len(changed)}


def impact(db: Session, r: Requirement, p: Principal) -> dict:
    """What a change to this requirement reaches. It reports and never alters anything (architecture §19.3)."""
    seen = {r.id}
    frontier = [r.id]
    reached: list[tuple[uuid.UUID, str]] = []
    while frontier:
        cur = frontier.pop()
        kids = db.execute(select(Requirement.id).where(Requirement.parent_id == cur)).scalars().all()
        deps = db.execute(select(RequirementLink.from_id, RequirementLink.link_type).where(RequirementLink.to_id == cur, RequirementLink.link_type.in_(PROPAGATING))).all()
        for rid, why in [(k, "child") for k in kids] + [(a, b) for a, b in deps]:
            if rid not in seen:
                seen.add(rid)
                reached.append((rid, why))
                frontier.append(rid)
    reqs = []
    hidden = 0
    visible_ids = [r.id]
    for rid, why in reached:
        x = db.get(Requirement, rid)
        if can_view(db, p, x):
            visible_ids.append(rid)
            reqs.append({"id": str(x.id), "key": x.key, "title": x.title, "status": x.status, "because": why, "owner_id": str(x.owner_id) if x.owner_id else None})
        else:
            hidden += 1
    sideways = db.execute(select(RequirementLink).where(or_(RequirementLink.from_id == r.id, RequirementLink.to_id == r.id), RequirementLink.link_type.in_(["related_to", "conflicts_with"]))).scalars().all()
    related = []
    for link in sideways:
        x = db.get(Requirement, link.to_id if link.from_id == r.id else link.from_id)
        if x and can_view(db, p, x):
            related.append({"id": str(x.id), "key": x.key, "title": x.title, "status": x.status, "because": link.link_type})
    tasks = db.execute(select(WorkItem).join(RequirementWorkItem, RequirementWorkItem.work_item_id == WorkItem.id).where(RequirementWorkItem.requirement_id.in_(visible_ids))).scalars().all()
    docs = db.execute(select(Document).join(RequirementDocument, RequirementDocument.document_id == Document.id).where(RequirementDocument.requirement_id.in_(visible_ids))).scalars().all()
    base = db.execute(select(RequirementBaseline).join(RequirementBaselineItem, RequirementBaselineItem.baseline_id == RequirementBaseline.id).where(RequirementBaselineItem.requirement_id.in_(visible_ids)).distinct()).scalars().all()
    return {
        "requirements": reqs, "related": related, "hidden_requirements": hidden,
        "tasks": [{"id": str(t.id), "key": t.key, "title": t.title, "status": t.status} for t in tasks],
        "documents": [{"id": str(d.id), "number": d.number, "title": d.title, "status": d.status} for d in docs],
        "baselines": [{"id": str(b.id), "seq": b.seq, "label": b.label} for b in base],
    }


def rtm(db: Session, project_id: uuid.UUID) -> dict:
    """Requirement Traceability Matrix: tasks, documents, designs (§11), code / merge requests (§12), tests and defects (§13)."""
    reqs = sorted(db.execute(select(Requirement).where(Requirement.project_id == project_id)).scalars().all(), key=lambda r: (r.sort_order, natural_key(r.key)))
    ids = [r.id for r in reqs]
    tasks: dict = defaultdict(list)
    docs: dict = defaultdict(list)
    ups: dict = defaultdict(list)
    downs: dict = defaultdict(list)
    keys = {r.id: r.key for r in reqs}
    in_base: dict = defaultdict(list)
    if ids:
        for rid, t in db.execute(select(RequirementWorkItem.requirement_id, WorkItem).join(WorkItem, WorkItem.id == RequirementWorkItem.work_item_id).where(RequirementWorkItem.requirement_id.in_(ids))).all():
            tasks[rid].append({"id": str(t.id), "key": t.key, "status": t.status, "progress": t.progress})
        for rid, d in db.execute(select(RequirementDocument.requirement_id, Document).join(Document, Document.id == RequirementDocument.document_id).where(RequirementDocument.requirement_id.in_(ids))).all():
            docs[rid].append({"id": str(d.id), "number": d.number, "status": d.status})
        for link in db.execute(select(RequirementLink).where(RequirementLink.from_id.in_(ids))).scalars():
            ups[link.from_id].append({"key": keys.get(link.to_id, "(other project)"), "type": link.link_type})
            if link.to_id in keys:
                downs[link.to_id].append({"key": keys[link.from_id], "type": link.link_type})
        for rid, seq in db.execute(select(RequirementBaselineItem.requirement_id, RequirementBaseline.seq).join(RequirementBaseline, RequirementBaseline.id == RequirementBaselineItem.baseline_id).where(RequirementBaselineItem.requirement_id.in_(ids))).all():
            in_base[rid].append(seq)
    designs, tests, defects, code = _rtm_engineering(db, ids, [t["id"] for v in tasks.values() for t in v])
    rows = [{"id": str(r.id), "key": r.key, "title": r.title, "status": r.status, "revision": r.revision, "priority": r.priority, "req_type": r.req_type, "tasks": tasks[r.id], "documents": docs[r.id],
             "traces_to": ups[r.id], "traced_by": downs[r.id], "baselines": sorted(in_base[r.id]), "designs": designs.get(r.id, []), "tests": tests.get(r.id, []), "defects": defects.get(r.id, []),
             "code": [c for t in tasks[r.id] for c in code.get(t["id"], [])]} for r in reqs]
    total = len(rows)
    with_tasks = sum(1 for x in rows if x["tasks"])
    with_docs = sum(1 for x in rows if x["documents"])
    verified = sum(1 for x in rows if x["tests"] and all(t["last_result"] == "PASSED" for t in x["tests"]))
    return {"rows": rows, "summary": {"total": total, "with_tasks": with_tasks, "with_documents": with_docs, "with_designs": sum(1 for x in rows if x["designs"]), "with_tests": sum(1 for x in rows if x["tests"]),
                                      "verified": verified, "open_defects": sum(1 for x in rows if any(d["status"] in ("OPEN", "IN_PROGRESS", "FIXED") for d in x["defects"])),
                                      "untraced": sum(1 for x in rows if not x["tasks"] and not x["documents"] and not x["traces_to"] and not x["traced_by"] and not x["designs"] and not x["tests"]), "baselined": sum(1 for x in rows if x["baselines"])}}


def _rtm_engineering(db: Session, req_ids: list, task_ids: list):
    """Design (§11), test and defect (§13) and code (§12) columns of the RTM, from the shared artefact links."""
    from app.models.artifacts import ArtifactLink
    from app.models.design import DesignRecord
    from app.models.scm import ScmLink
    from app.models.testing import Defect, TestCase
    from app.services.testing import last_results_for_cases

    designs: dict = defaultdict(list)
    tests: dict = defaultdict(list)
    defects: dict = defaultdict(list)
    code: dict = defaultdict(list)
    if not req_ids:
        return designs, tests, defects, code
    links = db.execute(select(ArtifactLink).where(ArtifactLink.to_type == "REQUIREMENT", ArtifactLink.to_id.in_(req_ids))).scalars().all()
    d_ids = {x.from_id for x in links if x.from_type == "DESIGN"}
    c_ids = {x.from_id for x in links if x.from_type == "TEST_CASE"}
    f_ids = {x.from_id for x in links if x.from_type == "DEFECT"}
    dmap = {d.id: d for d in db.execute(select(DesignRecord).where(DesignRecord.id.in_(d_ids))).scalars()} if d_ids else {}
    cmap = {c.id: c for c in db.execute(select(TestCase).where(TestCase.id.in_(c_ids))).scalars()} if c_ids else {}
    last = last_results_for_cases(db, list(cmap))
    found = db.execute(select(ArtifactLink.from_id, ArtifactLink.to_id).where(ArtifactLink.from_type == "DEFECT", ArtifactLink.to_type == "TEST_CASE", ArtifactLink.to_id.in_(list(cmap) or [uuid.uuid4()]))).all()
    by_case: dict = defaultdict(set)
    for def_id, case_id in found:
        by_case[case_id].add(def_id)
        f_ids.add(def_id)
    fmap = {f.id: f for f in db.execute(select(Defect).where(Defect.id.in_(f_ids))).scalars()} if f_ids else {}
    for x in links:
        if x.from_type == "DESIGN" and x.from_id in dmap:
            d = dmap[x.from_id]
            designs[x.to_id].append({"id": str(d.id), "key": d.key, "status": d.status, "link_type": x.link_type, "section": x.section})
        elif x.from_type == "TEST_CASE" and x.from_id in cmap:
            c = cmap[x.from_id]
            tests[x.to_id].append({"id": str(c.id), "key": c.key, "status": c.status, "last_result": (last.get(c.id) or {}).get("result")})
            for def_id in by_case.get(c.id, ()):
                f = fmap[def_id]
                if not any(e["id"] == str(f.id) for e in defects[x.to_id]):
                    defects[x.to_id].append({"id": str(f.id), "key": f.key, "status": f.status, "severity": f.severity})
        elif x.from_type == "DEFECT" and x.from_id in fmap:
            f = fmap[x.from_id]
            if not any(e["id"] == str(f.id) for e in defects[x.to_id]):
                defects[x.to_id].append({"id": str(f.id), "key": f.key, "status": f.status, "severity": f.severity})
    if task_ids:
        for link in db.execute(select(ScmLink).where(ScmLink.work_item_id.in_([uuid.UUID(t) for t in task_ids]), ScmLink.kind == "MERGE_REQUEST")).scalars():
            code[str(link.work_item_id)].append({"ref": f"!{link.ref}", "state": link.state, "url": link.url})
    return designs, tests, defects, code
