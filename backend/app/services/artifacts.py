"""Shared rules for reviewed engineering artefacts (design records, test cases, test plans).

Review (same principles as documents and requirements, architecture §8 and scenario D):
* every decision is bound to the artefact revision and its SHA-256; a newer revision makes old decisions stale;
* reviewers decide before approvers; at least one approver is required;
* the owner and the submitter cannot review or approve their own artefact (separation of duties);
* one "request changes" ends the cycle; a resubmission starts a new cycle with fresh decisions.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import AppError, Conflict, Forbidden
from app.models import Document, Requirement, User, WorkItem
from app.models.artifacts import ArtifactEvent, ArtifactLink, ArtifactReview
from app.services.notify import notify
from app.services.serial import iso, user_brief

LINK_TARGETS = {"REQUIREMENT", "DOCUMENT", "TASK", "DESIGN", "TEST_CASE", "DEFECT"}


def add_event(db: Session, a_type: str, a_id: uuid.UUID, kind: str, actor: uuid.UUID | None, frm=None, to=None, comment=None) -> None:
    db.add(ArtifactEvent(artifact_type=a_type, artifact_id=a_id, kind=kind, actor_id=actor, from_value=(str(frm)[:120] if frm is not None else None), to_value=(str(to)[:120] if to is not None else None), comment=comment))


def history(db: Session, a_type: str, a_id: uuid.UUID) -> list[dict]:
    rows = db.execute(select(ArtifactEvent).where(ArtifactEvent.artifact_type == a_type, ArtifactEvent.artifact_id == a_id).order_by(ArtifactEvent.at)).scalars().all()
    users = _users(db, {r.actor_id for r in rows})
    return [{"id": str(e.id), "at": iso(e.at), "kind": e.kind, "from": e.from_value, "to": e.to_value, "comment": e.comment, "actor": user_brief(users.get(e.actor_id))} for e in rows]


def _users(db: Session, ids) -> dict:
    ids = {i for i in ids if i}
    return {u.id: u for u in db.execute(select(User).where(User.id.in_(ids))).scalars()} if ids else {}


# ------------------------------------------------------------------ reviews
def current_cycle(db: Session, a_type: str, a_id: uuid.UUID) -> int:
    return db.execute(select(func.max(ArtifactReview.cycle)).where(ArtifactReview.artifact_type == a_type, ArtifactReview.artifact_id == a_id)).scalar() or 0


def submit(db: Session, *, a_type: str, a_id: uuid.UUID, revision: int, sha: str, submitter_id: uuid.UUID, reviewers: list[uuid.UUID], approvers: list[uuid.UUID],
           excluded: set[uuid.UUID], title: str, link: str) -> int:
    reviewers, approvers = list(dict.fromkeys(reviewers)), list(dict.fromkeys(approvers))
    if not approvers:
        raise AppError("Choose at least one approver.", code="APPROVER_REQUIRED")
    if set(reviewers) & set(approvers):
        raise AppError("The same person cannot be both reviewer and approver in one cycle.", code="SOD_VIOLATION")
    clash = (set(reviewers) | set(approvers)) & ({i for i in excluded if i} | {submitter_id})
    if clash:
        raise Forbidden("The owner or the submitter cannot review or approve this.", code="SOD_VIOLATION")
    people = _users(db, set(reviewers) | set(approvers))
    for uid in set(reviewers) | set(approvers):
        if uid not in people or not people[uid].is_active:
            raise AppError("A chosen reviewer or approver does not exist or is not active.")
    for old in db.execute(select(ArtifactReview).where(ArtifactReview.artifact_type == a_type, ArtifactReview.artifact_id == a_id, ArtifactReview.status == "PENDING")).scalars():
        old.status = "SUPERSEDED"
    cycle = current_cycle(db, a_type, a_id) + 1
    for role, ids in (("REVIEWER", reviewers), ("APPROVER", approvers)):
        for uid in ids:
            db.add(ArtifactReview(artifact_type=a_type, artifact_id=a_id, revision=revision, content_sha256=sha, cycle=cycle, reviewer_id=uid, role=role, submitted_by_id=submitter_id))
    first = reviewers or approvers
    for uid in first:
        notify(db, uid, "review.assigned", f"Review requested: {title}", "Your decision is needed.", link=link)
    db.flush()
    return cycle


def withdraw(db: Session, a_type: str, a_id: uuid.UUID) -> int:
    n = 0
    for r in db.execute(select(ArtifactReview).where(ArtifactReview.artifact_type == a_type, ArtifactReview.artifact_id == a_id, ArtifactReview.status == "PENDING")).scalars():
        r.status = "SUPERSEDED"
        n += 1
    return n


def decide(db: Session, *, review: ArtifactReview, user_id: uuid.UUID, decision: str, comment: str | None, revision: int, sha: str, title: str, link: str, owner_id: uuid.UUID | None) -> str:
    """Returns the cycle outcome: PENDING, APPROVED or CHANGES_REQUESTED."""
    if review.reviewer_id != user_id:
        raise Forbidden("This review is assigned to someone else.")
    if review.status != "PENDING":
        raise Conflict("This review has already been decided or was withdrawn.")
    if review.revision != revision or review.content_sha256 != sha:
        raise Conflict("The content changed after this review was requested. Ask for it to be resubmitted.", code="STALE_REVIEW")
    if decision not in ("approve", "request_changes"):
        raise AppError("Decision must be approve or request_changes.")
    if decision == "request_changes" and not (comment or "").strip():
        raise AppError("Say what has to change.", code="REASON_REQUIRED")
    cycle_rows = list(db.execute(select(ArtifactReview).where(ArtifactReview.artifact_type == review.artifact_type, ArtifactReview.artifact_id == review.artifact_id, ArtifactReview.cycle == review.cycle)).scalars())
    if review.role == "APPROVER" and any(r.role == "REVIEWER" and r.status == "PENDING" for r in cycle_rows):
        raise AppError("Reviewers decide first; this approval opens when every reviewer has approved.", code="NOT_YET")
    review.status = "APPROVED" if decision == "approve" else "CHANGES_REQUESTED"
    review.comment = (comment or "").strip() or None
    review.decided_at = utcnow()
    if decision == "request_changes":
        for r in cycle_rows:
            if r.status == "PENDING":
                r.status = "SUPERSEDED"
        if owner_id:
            notify(db, owner_id, "review.changes", f"Changes requested: {title}", review.comment, link=link, severity="warning")
        return "CHANGES_REQUESTED"
    if all(r.status == "APPROVED" for r in cycle_rows if r.status != "SUPERSEDED"):
        if owner_id:
            notify(db, owner_id, "review.approved", f"Approved: {title}", None, link=link)
        return "APPROVED"
    if review.role == "REVIEWER" and not any(r.role == "REVIEWER" and r.status == "PENDING" for r in cycle_rows):
        for r in cycle_rows:
            if r.role == "APPROVER" and r.status == "PENDING":
                notify(db, r.reviewer_id, "review.assigned", f"Approval requested: {title}", "Reviewers have approved.", link=link)
    return "PENDING"


def reviews(db: Session, a_type: str, a_id: uuid.UUID, me: uuid.UUID | None = None) -> list[dict]:
    rows = db.execute(select(ArtifactReview).where(ArtifactReview.artifact_type == a_type, ArtifactReview.artifact_id == a_id).order_by(ArtifactReview.cycle.desc(), ArtifactReview.role.desc(), ArtifactReview.created_at)).scalars().all()
    users = _users(db, {r.reviewer_id for r in rows})
    return [{"id": str(r.id), "cycle": r.cycle, "revision": r.revision, "sha256": r.content_sha256, "role": r.role, "status": r.status, "comment": r.comment, "decided_at": iso(r.decided_at),
             "reviewer": user_brief(users.get(r.reviewer_id)), "mine": r.reviewer_id == me and r.status == "PENDING"} for r in rows]


def is_reviewer(db: Session, a_type: str, a_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return db.execute(select(ArtifactReview.id).where(ArtifactReview.artifact_type == a_type, ArtifactReview.artifact_id == a_id, ArtifactReview.reviewer_id == user_id)).first() is not None


# ------------------------------------------------------------------ links
def target_summary(db: Session, to_type: str, to_id: uuid.UUID) -> dict | None:
    from app.models.design import DesignRecord
    from app.models.testing import Defect, TestCase

    model = {"REQUIREMENT": Requirement, "DOCUMENT": Document, "TASK": WorkItem, "DESIGN": DesignRecord, "TEST_CASE": TestCase, "DEFECT": Defect}.get(to_type)
    o = db.get(model, to_id) if model else None
    if not o:
        return None
    key = getattr(o, "key", None) or getattr(o, "number", None)
    return {"id": str(o.id), "type": to_type, "key": key, "title": o.title, "status": o.status, "project_id": str(getattr(o, "project_id", None) or "") or None}


def add_link(db: Session, *, from_type: str, from_id: uuid.UUID, to_type: str, to_id: uuid.UUID, link_type: str, section: str | None, actor: uuid.UUID) -> ArtifactLink:
    if to_type not in LINK_TARGETS:
        raise AppError(f"Cannot link to {to_type}.")
    if (from_type, from_id) == (to_type, to_id):
        raise AppError("An artefact cannot be linked to itself.")
    if not target_summary(db, to_type, to_id):
        raise AppError("The linked record does not exist.")
    if db.execute(select(ArtifactLink.id).where(ArtifactLink.from_type == from_type, ArtifactLink.from_id == from_id, ArtifactLink.to_type == to_type, ArtifactLink.to_id == to_id, ArtifactLink.link_type == link_type)).first():
        raise AppError("That link exists already.", code="DUPLICATE")
    link = ArtifactLink(from_type=from_type, from_id=from_id, to_type=to_type, to_id=to_id, link_type=link_type, section=section, created_by_id=actor)
    db.add(link)
    db.flush()
    return link


def links(db: Session, a_type: str, a_id: uuid.UUID, can_see=None) -> list[dict]:
    """Both directions. `can_see(type, summary)` filters out records the viewer may not open."""
    rows = db.execute(select(ArtifactLink).where(or_((ArtifactLink.from_type == a_type) & (ArtifactLink.from_id == a_id), (ArtifactLink.to_type == a_type) & (ArtifactLink.to_id == a_id)))).scalars().all()
    out = []
    for x in rows:
        outgoing = x.from_type == a_type and x.from_id == a_id
        o_type, o_id = (x.to_type, x.to_id) if outgoing else (x.from_type, x.from_id)
        s = target_summary(db, o_type, o_id)
        if not s or (can_see and not can_see(o_type, o_id)):
            continue
        out.append({"id": str(x.id), "link_type": x.link_type, "direction": "out" if outgoing else "in", "section": x.section, "target": s, "created_at": iso(x.created_at)})
    return out


def linked_ids(db: Session, from_type: str, to_type: str, to_ids: list[uuid.UUID], link_types: tuple[str, ...] | None = None) -> dict[uuid.UUID, list[uuid.UUID]]:
    """to_id -> [from_id] for links from `from_type` artefacts to the given targets (e.g. test cases verifying requirements)."""
    if not to_ids:
        return {}
    q = select(ArtifactLink.to_id, ArtifactLink.from_id).where(ArtifactLink.from_type == from_type, ArtifactLink.to_type == to_type, ArtifactLink.to_id.in_(to_ids))
    if link_types:
        q = q.where(ArtifactLink.link_type.in_(link_types))
    out: dict[uuid.UUID, list[uuid.UUID]] = {}
    for to_id, from_id in db.execute(q).all():
        out.setdefault(to_id, []).append(from_id)
    return out
