"""Preparer-defined review checklist for controlled documents.

* The preparer (author) writes the checklist for the revision: each item says what must be true, optionally where to
  look (guidance) and which stages use it (empty = every review and approval stage).
* Reviewers and approvers answer every item that applies to their stage with OK, NOT_OK or NA. NOT_OK and NA need a
  remark. Approval is possible only when every applicable item is answered and none is NOT_OK; a NOT_OK answer
  therefore leads to "request changes", and the author sees exactly which items failed and why.
* The checklist is frozen while the revision is in review. A new revision starts with a copy the author can change.
* Answers are stored per workflow task and never edited, so each cycle keeps its own record. The fixed checklist a
  process owner configures on a workflow stage still applies in addition.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.models import DocumentChecklistItem, DocumentChecklistResult, DocumentRevision, User
from app.services.serial import iso, user_brief

RESULTS = ("OK", "NOT_OK", "NA")
EDITABLE = ("DRAFT", "CHANGES_REQUESTED", "REJECTED")


def items(db: Session, revision_id: uuid.UUID) -> list[DocumentChecklistItem]:
    return list(db.execute(select(DocumentChecklistItem).where(DocumentChecklistItem.revision_id == revision_id).order_by(DocumentChecklistItem.sort_order, DocumentChecklistItem.created_at)).scalars())


def stages_of(item: DocumentChecklistItem) -> list[str]:
    return [x.strip() for x in (item.stages or "").split(",") if x.strip()]


def applicable(all_items: list[DocumentChecklistItem], stage_key: str) -> list[DocumentChecklistItem]:
    return [i for i in all_items if not stages_of(i) or stage_key in stages_of(i)]


def item_dict(i: DocumentChecklistItem) -> dict:
    return {"id": str(i.id), "text": i.text, "guidance": i.guidance, "stages": stages_of(i), "sort_order": i.sort_order}


def replace_items(db: Session, rev: DocumentRevision, rows: list[dict], actor_id: uuid.UUID, stage_keys: set[str]) -> list[DocumentChecklistItem]:
    if rev.locked or rev.status not in EDITABLE:
        raise Conflict(f"The checklist of revision {rev.label} is frozen while it is {rev.status.lower().replace('_', ' ')}.", code="LOCKED")
    seen = set()
    for n, r in enumerate(rows, 1):
        text = (r.get("text") or "").strip()
        if not text:
            raise AppError(f"Checklist item {n} has no text.")
        if text.lower() in seen:
            raise AppError(f"Checklist item {n} repeats an earlier item.")
        seen.add(text.lower())
        bad = set(r.get("stages") or []) - stage_keys
        if bad:
            raise AppError(f"Checklist item {n} names unknown stage(s): {', '.join(sorted(bad))}.")
    answered = db.execute(select(DocumentChecklistResult.id).join(DocumentChecklistItem, DocumentChecklistItem.id == DocumentChecklistResult.item_id)
                          .where(DocumentChecklistItem.revision_id == rev.id)).first()
    old = items(db, rev.id)
    if answered:
        # items already answered in an earlier cycle are kept for that record; only unanswered ones are replaced
        keep = {i.id for i in old if db.execute(select(DocumentChecklistResult.id).where(DocumentChecklistResult.item_id == i.id)).first()}
        by_text = {i.text.lower(): i for i in old if i.id in keep}
        out = []
        for n, r in enumerate(rows):
            i = by_text.pop(r["text"].strip().lower(), None)
            if i is None:
                i = DocumentChecklistItem(revision_id=rev.id, created_by_id=actor_id, text=r["text"].strip())
                db.add(i)
            i.sort_order, i.guidance, i.stages = n, (r.get("guidance") or "").strip() or None, ",".join(r.get("stages") or []) or None
            out.append(i)
        for i in old:
            if i.id not in keep:
                db.delete(i)
        for i in by_text.values():
            i.sort_order = 1000 + i.sort_order  # kept for history, moved to the end and no longer asked
            i.stages = "__retired__"
        db.flush()
        return out
    for i in old:
        db.delete(i)
    out = []
    for n, r in enumerate(rows):
        i = DocumentChecklistItem(revision_id=rev.id, sort_order=n, text=r["text"].strip(), guidance=(r.get("guidance") or "").strip() or None,
                                  stages=",".join(r.get("stages") or []) or None, created_by_id=actor_id)
        db.add(i)
        out.append(i)
    db.flush()
    return out


def copy_forward(db: Session, from_rev: DocumentRevision, to_rev: DocumentRevision, actor_id: uuid.UUID) -> int:
    n = 0
    for i in items(db, from_rev.id):
        if i.stages == "__retired__":
            continue
        db.add(DocumentChecklistItem(revision_id=to_rev.id, sort_order=i.sort_order, text=i.text, guidance=i.guidance, stages=i.stages, created_by_id=actor_id))
        n += 1
    return n


def active(all_items: list[DocumentChecklistItem]) -> list[DocumentChecklistItem]:
    return [i for i in all_items if i.stages != "__retired__"]


def validate_and_record(db: Session, *, rev_id: uuid.UUID, stage_key: str, stage_type: str, task_id: uuid.UUID, user_id: uuid.UUID, decision: str, answers: dict | None) -> list[str]:
    """Checks the answers for this stage and stores them. Returns the texts of NOT_OK items (for the author)."""
    if stage_type not in ("review", "approval"):
        return []
    todo = applicable(active(items(db, rev_id)), stage_key)
    if not todo:
        return []
    answers = answers or {}
    errors, failed = [], []
    for i in todo:
        a = answers.get(str(i.id))
        if not a or a.get("result") not in RESULTS:
            if decision == "approve":
                errors.append(f"Answer: {i.text}")
            continue
        if a["result"] in ("NOT_OK", "NA") and not (a.get("remark") or "").strip():
            errors.append(f"Give a remark for {'not OK' if a['result'] == 'NOT_OK' else 'not applicable'}: {i.text}")
        if a["result"] == "NOT_OK":
            failed.append(i.text)
    if decision == "approve" and failed:
        errors.append("Items marked not OK cannot be approved; request changes instead: " + "; ".join(failed))
    if errors:
        raise AppError("The preparer's checklist is not complete.", code="CHECKLIST", details={"errors": errors})
    for i in todo:
        a = answers.get(str(i.id))
        if a and a.get("result") in RESULTS:
            db.add(DocumentChecklistResult(task_id=task_id, item_id=i.id, result=a["result"], remark=(a.get("remark") or "").strip() or None, by_id=user_id))
    return failed


def results_for_tasks(db: Session, task_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
    if not task_ids:
        return {}
    rows = db.execute(select(DocumentChecklistResult, DocumentChecklistItem).join(DocumentChecklistItem, DocumentChecklistItem.id == DocumentChecklistResult.item_id)
                      .where(DocumentChecklistResult.task_id.in_(task_ids)).order_by(DocumentChecklistItem.sort_order)).all()
    users = {u.id: u for u in db.execute(select(User).where(User.id.in_({r.by_id for r, _ in rows} | {uuid.uuid4()}))).scalars()}
    out: dict[uuid.UUID, list[dict]] = {}
    for r, i in rows:
        out.setdefault(r.task_id, []).append({"item_id": str(i.id), "text": i.text, "result": r.result, "remark": r.remark, "at": iso(r.at), "by": user_brief(users.get(r.by_id))})
    return out
