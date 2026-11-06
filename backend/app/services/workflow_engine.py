"""Workflow engine: resolve → start → decide / sign → advance → complete. Every transition is server-validated."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.db import aware, utcnow
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.core.security import verify_password
from app.models import (
    Delegation,
    Document,
    DocumentRevision,
    DocumentType,
    EngineeringItem,
    HierarchyLevel,
    OrgUnit,
    ProcessDomain,
    Role,
    RoleAssignment,
    SignatureRecord,
    User,
    WorkflowBinding,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowStageRun,
    WorkflowTask,
    WorkflowVersion,
)
from app.services import audit, storage
from app.services.notify import notify
from app.services.signature import get_provider
from app.services.workflow_spec import Stage, WorkflowSpec

OPEN_REVISION_STATES = ("DRAFT", "CHANGES_REQUESTED", "REJECTED")


# ------------------------------------------------------------------ helpers

def spec_of(version: WorkflowVersion) -> WorkflowSpec:
    return WorkflowSpec.model_validate_json(version.spec)


def _facts(db: Session, doc: Document) -> dict[str, str | None]:
    dt = db.get(DocumentType, doc.type_id)
    dom = db.get(ProcessDomain, doc.domain_id) if doc.domain_id else None
    level = None
    if doc.item_id:
        it = db.get(EngineeringItem, doc.item_id)
        lv = db.get(HierarchyLevel, it.level_id) if it else None
        level = lv.code if lv else None
    return {"classification": doc.classification, "doc_type": dt.code if dt else None, "domain": dom.code if dom else None, "level": level, "category": dt.category if dt else None}


def _doc_paths(db: Session, doc: Document) -> tuple[str | None, str | None]:
    item_path = db.get(EngineeringItem, doc.item_id).path if doc.item_id else None
    org_path = db.get(OrgUnit, doc.owner_org_unit_id).path if doc.owner_org_unit_id else None
    return item_path, org_path


def users_with_role(db: Session, role_code: str, doc: Document) -> list[uuid.UUID]:
    """Active users holding `role_code` in a scope that covers the document."""
    role = db.execute(select(Role).where(Role.code == role_code, Role.active.is_(True))).scalar_one_or_none()
    if not role:
        return []
    now = utcnow()
    item_path, org_path = _doc_paths(db, doc)
    rows = db.execute(
        select(RoleAssignment).join(User, User.id == RoleAssignment.user_id).where(
            RoleAssignment.role_id == role.id,
            User.is_active.is_(True),
            or_(RoleAssignment.valid_from.is_(None), RoleAssignment.valid_from <= now),
            or_(RoleAssignment.valid_to.is_(None), RoleAssignment.valid_to >= now),
        )
    ).scalars().all()
    out: list[uuid.UUID] = []
    for r in rows:
        sid = f"/{r.scope_id}/"
        ok = (
            r.scope_type == "GLOBAL"
            or (r.scope_type == "PROJECT" and doc.project_id == r.scope_id)
            or (r.scope_type == "ORG_UNIT" and org_path and sid in org_path)
            or (r.scope_type == "ENG_ITEM" and item_path and sid in item_path)
        )
        if ok and r.user_id not in out:
            out.append(r.user_id)
    return out


def resolve_version(db: Session, doc: Document) -> WorkflowVersion:
    facts = _facts(db, doc)
    _, org_path = _doc_paths(db, doc)
    org_chain = {uuid.UUID(x) for x in (org_path or "").strip("/").split("/") if x}
    best: list[tuple[int, int, WorkflowBinding]] = []
    for b in db.execute(select(WorkflowBinding).where(WorkflowBinding.active.is_(True))).scalars():
        score = 0
        ok = True
        for attr, val in (("document_type_id", doc.type_id), ("domain_id", doc.domain_id), ("project_id", doc.project_id)):
            bv = getattr(b, attr)
            if bv is not None:
                if bv != val:
                    ok = False
                score += 1
        if b.org_unit_id is not None:
            ok = ok and b.org_unit_id in org_chain
            score += 1
        if b.level_code is not None:
            ok = ok and b.level_code == facts["level"]
            score += 1
        if ok:
            best.append((score, b.priority, b))
    if not best:
        raise AppError("No workflow is configured for this document type/scope. Ask a process administrator to bind one.", code="NO_WORKFLOW")
    best.sort(key=lambda t: (t[0], t[1]), reverse=True)
    if len(best) > 1 and best[0][:2] == best[1][:2] and best[0][2].definition_id != best[1][2].definition_id:
        raise AppError("Ambiguous workflow bindings match this document. Process administrator must resolve the conflict.", code="AMBIGUOUS_WORKFLOW")
    def_id = best[0][2].definition_id
    v = db.execute(
        select(WorkflowVersion).where(WorkflowVersion.definition_id == def_id, WorkflowVersion.status == "PUBLISHED").order_by(WorkflowVersion.version_no.desc())
    ).scalars().first()
    if not v:
        d = db.get(WorkflowDefinition, def_id)
        raise AppError(f"Workflow '{d.name if d else def_id}' has no published version.", code="NO_PUBLISHED_WORKFLOW")
    return v


def file_hash_ok(rev: DocumentRevision) -> bool:
    if not rev.file:
        return False
    data = storage.read_bytes(rev.file)
    return hashlib.sha256(data).hexdigest() == rev.sha256


def _actors(db: Session, inst: WorkflowInstance, stage_keys: list[str]) -> set[uuid.UUID]:
    out: set[uuid.UUID] = set()
    if not stage_keys:
        return out
    for t in db.execute(select(WorkflowTask).where(WorkflowTask.instance_id == inst.id, WorkflowTask.stage_key.in_(stage_keys))).scalars():
        if t.status in ("APPROVED", "SIGNED"):
            out.add(t.acted_by_id or t.assignee_id)
            out.add(t.assignee_id)
    return out


def _can_act_for(db: Session, user_id: uuid.UUID, assignee_id: uuid.UUID) -> bool:
    if user_id == assignee_id:
        return True
    now = utcnow()
    return db.execute(
        select(Delegation.id).where(
            Delegation.from_user_id == assignee_id, Delegation.to_user_id == user_id, Delegation.active.is_(True),
            Delegation.valid_from <= now, Delegation.valid_to >= now,
        )
    ).first() is not None


# ------------------------------------------------------------------ planning (used by UI before submit)

def plan_for_document(db: Session, doc: Document) -> dict:
    """Describe the workflow that *will* run: stages, who must be picked, suggested candidates."""
    v = resolve_version(db, doc)
    spec = spec_of(v)
    facts = _facts(db, doc)
    stages = []
    for s in spec.stages:
        skipped = bool(s.skip_if and s.skip_if.matches(facts))
        cands: list[uuid.UUID] = []
        if s.assignee.kind in ("pick", "role") and s.assignee.role_code:
            cands = users_with_role(db, s.assignee.role_code, doc)
        elif s.assignee.kind == "users":
            cands = [uuid.UUID(u) for u in s.assignee.user_ids]
        users = db.execute(select(User).where(User.id.in_(cands))).scalars().all() if cands else []
        stages.append(
            {
                **s.model_dump(),
                "skipped": skipped,
                "candidates": [{"id": str(u.id), "full_name": u.full_name, "designation": u.designation} for u in users],
            }
        )
    d = db.get(WorkflowDefinition, v.definition_id)
    return {"version_id": str(v.id), "definition": {"code": d.code, "name": d.name}, "version_no": v.version_no, "on_complete": spec.on_complete, "stages": stages}


# ------------------------------------------------------------------ start / submit

def start(db: Session, actor: User, doc: Document, rev: DocumentRevision, picks: dict[str, list[str]], comment: str | None = None) -> WorkflowInstance:
    if rev.document_id != doc.id or doc.current_revision_id != rev.id:
        raise Conflict("Only the current revision can be submitted.")
    if rev.status not in OPEN_REVISION_STATES:
        raise Conflict(f"Revision {rev.label} is {rev.status} and cannot be submitted.")
    if not rev.file_id or not rev.sha256:
        raise AppError("Attach or author the document content before submitting.", code="NO_CONTENT")
    if not file_hash_ok(rev):
        raise AppError("Stored file failed integrity verification.", code="INTEGRITY")
    active = db.execute(select(WorkflowInstance.id).where(WorkflowInstance.document_id == doc.id, WorkflowInstance.status == "ACTIVE")).first()
    if active:
        raise Conflict("This document already has an active workflow.")
    v = resolve_version(db, doc)
    spec = spec_of(v)
    facts = _facts(db, doc)
    dt = db.get(DocumentType, doc.type_id)
    if dt and dt.require_review_checklist and any(s.type in ("review", "approval") for s in spec.stages):
        from app.services import doc_checklist

        if not doc_checklist.active(doc_checklist.items(db, rev.id)):
            raise AppError("Prepare the review checklist for this revision first, so reviewers and approvers can check against it.", code="CHECKLIST_REQUIRED")

    planned: dict[str, list[str]] = {}
    for s in spec.stages[1:]:
        if s.skip_if and s.skip_if.matches(facts):
            continue
        if s.type == "signature":
            continue
        if s.assignee.kind == "pick":
            ids = [str(uuid.UUID(x)) for x in picks.get(s.key, [])]
            if len(ids) < s.assignee.min:
                raise AppError(f"Select at least {s.assignee.min} person(s) for '{s.name}'.", code="PICK_REQUIRED", details={"stage": s.key})
            if s.assignee.max and len(ids) > s.assignee.max:
                raise AppError(f"Select at most {s.assignee.max} person(s) for '{s.name}'.", code="PICK_TOO_MANY", details={"stage": s.key})
            if s.assignee.role_code:
                eligible = {str(u) for u in users_with_role(db, s.assignee.role_code, doc)}
                bad = [i for i in ids if i not in eligible]
                if bad:
                    raise AppError(f"Some selected people do not hold the required role for '{s.name}'.", code="PICK_INELIGIBLE", details={"stage": s.key})
        elif s.assignee.kind == "role":
            ids = [str(u) for u in users_with_role(db, s.assignee.role_code or "", doc)]
            if not ids:
                raise AppError(f"No active user holds the role required for '{s.name}' in this scope.", code="NO_ELIGIBLE_USER", details={"stage": s.key})
        elif s.assignee.kind == "users":
            ids = list(s.assignee.user_ids)
        else:
            ids = [str(actor.id)]
        for uid in ids:
            u = db.get(User, uuid.UUID(uid))
            if not u or not u.is_active:
                raise AppError("A selected person is inactive.", code="INACTIVE_USER", details={"stage": s.key})
        # SoD: initiator cannot sit on stages that exclude the prepare stage.
        if spec.stages[0].key in s.sod_exclude and str(actor.id) in ids:
            raise Forbidden(f"Separation of duties: you prepared this revision and cannot also act as '{s.name}'.")
        planned[s.key] = ids

    cycle = (db.execute(select(WorkflowInstance).where(WorkflowInstance.revision_id == rev.id)).scalars().all().__len__()) + 1
    inst = WorkflowInstance(
        version_id=v.id, document_id=doc.id, revision_id=rev.id, iteration=rev.iteration, revision_sha256=rev.sha256,
        cycle_no=cycle, status="ACTIVE", initiator_id=actor.id, planned_assignees=json.dumps(planned),
    )
    db.add(inst)
    db.flush()
    prep = spec.stages[0]
    run = WorkflowStageRun(instance_id=inst.id, stage_key=prep.key, stage_name=prep.name, stage_type=prep.type, seq=0, status="DONE", started_at=utcnow(), ended_at=utcnow())
    db.add(run)
    db.flush()
    db.add(WorkflowTask(
        instance_id=inst.id, stage_run_id=run.id, stage_key=prep.key, assignee_id=actor.id, status="APPROVED",
        decision_comment=comment, acted_by_id=actor.id, acted_at=utcnow(), revision_id=rev.id, revision_sha256=rev.sha256,
    ))
    rev.status = "IN_REVIEW"
    rev.locked = True
    doc.status = "IN_REVIEW"
    doc.version += 1
    audit.record(db, actor_id=actor.id, action="workflow.submit", entity_type="document", entity_id=doc.id,
                 summary=f"{doc.number} rev {rev.label}.{rev.iteration} submitted to '{v.definition.name}' v{v.version_no}",
                 data={"revision": str(rev.id), "sha256": rev.sha256, "cycle": cycle, "planned": planned})
    _advance(db, inst, spec, doc, rev, from_index=0)
    return inst


# ------------------------------------------------------------------ advance / stage activation

def _activate(db: Session, inst: WorkflowInstance, spec: WorkflowSpec, idx: int, doc: Document, rev: DocumentRevision) -> bool:
    """Returns True if a stage was activated (False if skipped)."""
    s: Stage = spec.stages[idx]
    if s.skip_if and s.skip_if.matches(_facts(db, doc)):
        db.add(WorkflowStageRun(instance_id=inst.id, stage_key=s.key, stage_name=s.name, stage_type=s.type, seq=idx, status="SKIPPED", started_at=utcnow(), ended_at=utcnow()))
        return False
    if s.type == "signature":
        signature_required = spec.signature_required
        if signature_required is None:
            signature_required = bool(db.get(DocumentType, doc.type_id).requires_signature)
        if not signature_required:
            db.add(WorkflowStageRun(instance_id=inst.id, stage_key=s.key, stage_name=s.name, stage_type=s.type, seq=idx, status="SKIPPED", started_at=utcnow(), ended_at=utcnow()))
            return False
        ids: list[uuid.UUID] = []
        for t in db.execute(select(WorkflowTask).where(WorkflowTask.instance_id == inst.id, WorkflowTask.stage_key.in_(s.signers_from), WorkflowTask.status == "APPROVED").order_by(WorkflowTask.acted_at)).scalars():
            if t.assignee_id not in ids:
                ids.append(t.assignee_id)
    else:
        planned = json.loads(inst.planned_assignees or "{}")
        ids = [uuid.UUID(x) for x in planned.get(s.key, [])]
    if not ids:
        raise AppError(f"Stage '{s.name}' has nobody to act on it.", code="NO_ASSIGNEE")
    due = utcnow() + timedelta(hours=s.sla_hours) if s.sla_hours else None
    run = WorkflowStageRun(instance_id=inst.id, stage_key=s.key, stage_name=s.name, stage_type=s.type, seq=idx, status="ACTIVE", started_at=utcnow(), due_at=due)
    db.add(run)
    db.flush()
    inst.current_stage_key = s.key
    verb = {"signature": "Signature requested", "approval": "Approval requested", "acknowledge": "Acknowledgement requested"}.get(s.type, "Review requested")
    for uid in ids:
        db.add(WorkflowTask(instance_id=inst.id, stage_run_id=run.id, stage_key=s.key, assignee_id=uid, status="PENDING", revision_id=rev.id, revision_sha256=rev.sha256, due_at=due))
        notify(db, uid, "workflow.task", f"{verb}: {doc.number}", f"{s.name} · {doc.title} (rev {rev.label})", link=f"/inbox?doc={doc.id}", severity="warning" if s.type == "signature" else "info", dedupe_key=f"task:{inst.id}:{s.key}:{uid}")
    return True


def _advance(db: Session, inst: WorkflowInstance, spec: WorkflowSpec, doc: Document, rev: DocumentRevision, from_index: int) -> None:
    for idx in range(from_index + 1, len(spec.stages)):
        if _activate(db, inst, spec, idx, doc, rev):
            return
    _complete(db, inst, spec, doc, rev)


def _complete(db: Session, inst: WorkflowInstance, spec: WorkflowSpec, doc: Document, rev: DocumentRevision) -> None:
    inst.status = "COMPLETED"
    inst.current_stage_key = None
    inst.completed_at = utcnow()
    rev.status = "APPROVED"
    rev.approved_at = utcnow()
    doc.status = "APPROVED"
    doc.version += 1
    audit.record(db, actor_id=None, action="workflow.complete", entity_type="document", entity_id=doc.id, summary=f"{doc.number} rev {rev.label} approved — ready for release", data={"instance": str(inst.id), "sha256": rev.sha256})
    notify(db, inst.initiator_id, "workflow.approved", f"Approved: {doc.number}", f"Revision {rev.label} completed all review stages and is ready for release.", link=f"/documents/{doc.id}", severity="success")
    if spec.on_complete == "release":
        from app.services.release import release_revision

        last = db.execute(select(WorkflowTask).where(WorkflowTask.instance_id == inst.id, WorkflowTask.status.in_(["APPROVED", "SIGNED"])).order_by(WorkflowTask.acted_at.desc())).scalars().first()
        actor = db.get(User, last.acted_by_id or last.assignee_id) if last else db.get(User, inst.initiator_id)
        release_revision(db, actor, doc, rev, note="Auto-released by workflow", enforce_authority=False)


def _load(db: Session, task_id: uuid.UUID):
    task = db.get(WorkflowTask, task_id)
    if not task:
        raise NotFound("Task not found.")
    inst = db.get(WorkflowInstance, task.instance_id)
    doc = db.get(Document, inst.document_id)
    rev = db.get(DocumentRevision, inst.revision_id)
    spec = spec_of(db.get(WorkflowVersion, inst.version_id))
    return task, inst, doc, rev, spec


def _guard(db: Session, user: User, task: WorkflowTask, inst: WorkflowInstance, rev: DocumentRevision, spec: WorkflowSpec) -> Stage:
    if task.status != "PENDING":
        raise Conflict("This task has already been completed.")
    if inst.status != "ACTIVE" or inst.current_stage_key != task.stage_key:
        raise Conflict("This workflow is no longer waiting on this stage.")
    if not _can_act_for(db, user.id, task.assignee_id):
        raise Forbidden("This task is assigned to someone else.")
    if not user.is_active:
        raise Forbidden("Inactive users cannot act on workflow tasks.")
    if task.revision_sha256 != rev.sha256 or inst.revision_sha256 != rev.sha256 or not file_hash_ok(rev):
        raise Conflict("The document content changed after this review started. The review must be restarted.")
    stage = next(s for s in spec.stages if s.key == task.stage_key)
    excluded = _actors(db, inst, stage.sod_exclude)
    if user.id in excluded or task.assignee_id in excluded:
        raise Forbidden(f"Separation of duties: you already acted on an earlier stage and cannot act as '{stage.name}'.")
    return stage


def decide(db: Session, user: User, task_id: uuid.UUID, decision: str, comment: str | None, checklist: dict[str, bool] | None = None, item_results: dict | None = None) -> WorkflowInstance:
    task, inst, doc, rev, spec = _load(db, task_id)
    stage = _guard(db, user, task, inst, rev, spec)
    if stage.type == "signature":
        raise AppError("Use the Sign action for signature stages.", code="USE_SIGN")
    if decision not in ("approve", "request_changes", "reject"):
        raise AppError("Unknown decision.")
    if decision == "reject" and not stage.allow_reject:
        raise AppError("Rejection is not allowed at this stage; request changes instead.")
    if decision != "approve" and not (comment and comment.strip()):
        raise AppError("Please give a reason so the author knows what to change.", code="COMMENT_REQUIRED")
    if decision == "approve" and stage.checklist:
        missing = [c for c in stage.checklist if not (checklist or {}).get(c)]
        if missing:
            raise AppError("Complete all checklist items before approving.", code="CHECKLIST", details={"missing": missing})
    from app.services import doc_checklist

    failed = doc_checklist.validate_and_record(db, rev_id=rev.id, stage_key=stage.key, stage_type=stage.type, task_id=task.id, user_id=user.id, decision=decision, answers=item_results)
    if failed and decision != "approve":
        comment = f"{comment}\n\nChecklist items not OK: " + "; ".join(failed)
    now = utcnow()
    task.status = {"approve": "APPROVED", "request_changes": "CHANGES_REQUESTED", "reject": "REJECTED"}[decision]
    task.decision_comment = comment
    task.checklist_result = json.dumps(checklist) if checklist else None
    task.acted_by_id = user.id
    task.acted_at = now
    on_behalf = task.assignee_id if user.id != task.assignee_id else None
    audit.record(db, actor_id=user.id, on_behalf_of_id=on_behalf, action=f"workflow.{decision}", entity_type="document", entity_id=doc.id,
                 summary=f"{stage.name}: {decision.replace('_', ' ')} on {doc.number} rev {rev.label}", data={"task": str(task.id), "sha256": rev.sha256, "comment": comment})
    run = db.get(WorkflowStageRun, task.stage_run_id)
    siblings = db.execute(select(WorkflowTask).where(WorkflowTask.stage_run_id == run.id)).scalars().all()

    if decision in ("request_changes", "reject"):
        for t in siblings:
            if t.status == "PENDING":
                t.status = "CANCELLED"
        run.status = "RETURNED" if decision == "request_changes" else "REJECTED"
        run.ended_at = now
        inst.status = "CHANGES_REQUESTED" if decision == "request_changes" else "REJECTED"
        inst.current_stage_key = None
        inst.completed_at = now
        rev.status = "CHANGES_REQUESTED" if decision == "request_changes" else "REJECTED"
        rev.locked = False
        doc.status = rev.status
        doc.version += 1
        notify(db, inst.initiator_id, "workflow.returned", f"{'Changes requested' if decision == 'request_changes' else 'Rejected'}: {doc.number}", f"{user.full_name} ({stage.name}): {comment}", link=f"/documents/{doc.id}", severity="error")
        return inst

    approvals = sum(1 for t in siblings if t.status == "APPROVED")
    pending = [t for t in siblings if t.status == "PENDING"]
    done = (stage.mode == "any" and approvals >= 1) or (stage.mode == "all" and not pending) or (stage.mode == "quorum" and approvals >= (stage.quorum or 1))
    if done:
        for t in pending:
            t.status = "CANCELLED"
        run.status = "DONE"
        run.ended_at = now
        idx = next(i for i, s in enumerate(spec.stages) if s.key == stage.key)
        _advance(db, inst, spec, doc, rev, idx)
    return inst


def sign(db: Session, user: User, task_id: uuid.UUID, password: str, comment: str | None = None) -> SignatureRecord:
    task, inst, doc, rev, spec = _load(db, task_id)
    stage = _guard(db, user, task, inst, rev, spec)
    if stage.type != "signature":
        raise AppError("This task is not a signature task.")
    if user.id != task.assignee_id:
        raise Forbidden("Signatures cannot be delegated; the signatory must sign personally.")
    if not verify_password(password, user.password_hash):
        audit.record(db, actor_id=user.id, action="signature.auth_failed", entity_type="document", entity_id=doc.id, summary="Signature re-authentication failed", outcome="FAILURE")
        raise Forbidden("Re-authentication failed. Signature not applied.")
    # sign as the role(s) the signer played earlier in this workflow
    roles = [
        s.name for s in spec.stages
        if s.key in stage.signers_from and db.execute(select(WorkflowTask.id).where(WorkflowTask.instance_id == inst.id, WorkflowTask.stage_key == s.key, WorkflowTask.assignee_id == user.id, WorkflowTask.status == "APPROVED")).first()
    ]
    res = get_provider().sign(rev.sha256, user.username, user.full_name)
    rec = SignatureRecord(
        revision_id=rev.id, task_id=task.id, signer_id=user.id, signer_role=", ".join(roles) or stage.name, provider=res.provider,
        algorithm=res.algorithm, signed_sha256=rev.sha256, signature_b64=res.signature_b64, certificate_pem=res.certificate_pem,
        certificate_subject=res.certificate_subject, certificate_serial=res.certificate_serial, signed_at=res.signed_at,
        status="VALID", is_cryptographic=res.is_cryptographic,
    )
    db.add(rec)
    now = utcnow()
    task.status = "SIGNED"
    task.acted_by_id = user.id
    task.acted_at = now
    task.decision_comment = comment
    audit.record(db, actor_id=user.id, action="signature.sign", entity_type="document", entity_id=doc.id,
                 summary=f"Digitally signed {doc.number} rev {rev.label} as {rec.signer_role}", data={"sha256": rev.sha256, "provider": res.provider, "serial": res.certificate_serial})
    run = db.get(WorkflowStageRun, task.stage_run_id)
    pending = db.execute(select(WorkflowTask).where(WorkflowTask.stage_run_id == run.id, WorkflowTask.status == "PENDING")).scalars().all()
    if not pending:
        run.status = "DONE"
        run.ended_at = now
        idx = next(i for i, s in enumerate(spec.stages) if s.key == stage.key)
        _advance(db, inst, spec, doc, rev, idx)
    return rec


def withdraw(db: Session, user: User, inst_id: uuid.UUID, reason: str) -> WorkflowInstance:
    inst = db.get(WorkflowInstance, inst_id)
    if not inst or inst.status != "ACTIVE":
        raise Conflict("Workflow is not active.")
    if inst.initiator_id != user.id:
        raise Forbidden("Only the initiator can withdraw a submission.")
    if not reason:
        raise AppError("A reason is required.", code="COMMENT_REQUIRED")
    doc = db.get(Document, inst.document_id)
    rev = db.get(DocumentRevision, inst.revision_id)
    for t in db.execute(select(WorkflowTask).where(WorkflowTask.instance_id == inst.id, WorkflowTask.status == "PENDING")).scalars():
        t.status = "CANCELLED"
    for r in db.execute(select(WorkflowStageRun).where(WorkflowStageRun.instance_id == inst.id, WorkflowStageRun.status == "ACTIVE")).scalars():
        r.status = "CANCELLED"
        r.ended_at = utcnow()
    inst.status = "CANCELLED"
    inst.current_stage_key = None
    inst.completed_at = utcnow()
    rev.status = "DRAFT"
    rev.locked = False
    doc.status = "DRAFT"
    doc.version += 1
    audit.record(db, actor_id=user.id, action="workflow.withdraw", entity_type="document", entity_id=doc.id, summary=f"Submission of {doc.number} withdrawn: {reason}")
    return inst


def reassign(db: Session, user: User, task_id: uuid.UUID, new_user_id: uuid.UUID, reason: str) -> WorkflowTask:
    task, inst, doc, rev, spec = _load(db, task_id)
    if task.status != "PENDING":
        raise Conflict("Only pending tasks can be reassigned.")
    if user.id not in (inst.initiator_id, task.assignee_id):
        raise Forbidden("Only the initiator or current assignee can reassign.")
    nu = db.get(User, new_user_id)
    if not nu or not nu.is_active:
        raise AppError("Target user is not active.")
    stage = next(s for s in spec.stages if s.key == task.stage_key)
    if nu.id in _actors(db, inst, stage.sod_exclude) or (spec.stages[0].key in stage.sod_exclude and nu.id == inst.initiator_id):
        raise Forbidden("Separation of duties prevents assigning this person.")
    if stage.assignee.role_code and nu.id not in users_with_role(db, stage.assignee.role_code, doc):
        raise AppError("Target user does not hold the role required for this stage.")
    task.status = "REASSIGNED"
    task.decision_comment = reason
    task.acted_by_id = user.id
    task.acted_at = utcnow()
    nt = WorkflowTask(instance_id=inst.id, stage_run_id=task.stage_run_id, stage_key=task.stage_key, assignee_id=nu.id, status="PENDING", revision_id=rev.id, revision_sha256=rev.sha256, due_at=task.due_at)
    db.add(nt)
    notify(db, nu.id, "workflow.task", f"Task reassigned to you: {doc.number}", reason, link=f"/inbox?doc={doc.id}")
    audit.record(db, actor_id=user.id, action="workflow.reassign", entity_type="document", entity_id=doc.id, summary=f"{stage.name} task reassigned to {nu.full_name}: {reason}")
    return nt


def overdue_sweep(db: Session) -> int:
    """SLA reminders/escalations — called periodically by the worker."""
    now = utcnow()
    n = 0
    for t in db.execute(select(WorkflowTask).where(WorkflowTask.status == "PENDING", WorkflowTask.due_at.is_not(None))).scalars():
        due = aware(t.due_at)
        if due and due < now and (t.reminded_at is None or aware(t.reminded_at) < now - timedelta(hours=24)):
            inst = db.get(WorkflowInstance, t.instance_id)
            doc = db.get(Document, inst.document_id)
            notify(db, t.assignee_id, "workflow.overdue", f"Overdue: {doc.number}", f"Your {t.stage_key} task is overdue.", link=f"/inbox?doc={doc.id}", severity="error", dedupe_key=f"overdue:{t.id}:{now.date()}")
            notify(db, inst.initiator_id, "workflow.overdue", f"Review overdue: {doc.number}", f"Stage '{t.stage_key}' is past its due date.", link=f"/documents/{doc.id}", severity="warning", dedupe_key=f"overdue-init:{t.id}:{now.date()}")
            t.reminded_at = now
            n += 1
    return n
