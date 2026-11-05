"""Release gate + Central Release Register. Releases are immutable; corrections create new revisions."""
from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import AppError, Conflict
from app.models import (
    Document,
    DocumentRevision,
    DocumentType,
    ReleasePackage,
    ReleasePackageItem,
    ReleaseRegisterEntry,
    SignatureRecord,
    User,
    WorkflowInstance,
    WorkflowVersion,
)
from app.services import audit
from app.services.notify import notify
from app.services.numbering import next_seq
from app.services.signature import get_provider
from app.services.workflow_engine import file_hash_ok, spec_of


def release_checks(db: Session, doc: Document, rev: DocumentRevision) -> list[dict]:
    """Gate checklist shown in the UI and enforced on release."""
    checks: list[dict] = []
    checks.append({"key": "current", "label": "Revision is the document's current revision", "ok": doc.current_revision_id == rev.id})
    checks.append({"key": "approved", "label": "All review & approval stages completed", "ok": rev.status == "APPROVED"})
    checks.append({"key": "integrity", "label": "File integrity (SHA-256) verified", "ok": bool(rev.file_id) and file_hash_ok(rev)})
    inst = db.execute(select(WorkflowInstance).where(WorkflowInstance.revision_id == rev.id, WorkflowInstance.status == "COMPLETED").order_by(WorkflowInstance.created_at.desc())).scalars().first()
    checks.append({"key": "bound", "label": "Approved content hash matches reviewed content", "ok": bool(inst and inst.revision_sha256 == rev.sha256)})
    dt = db.get(DocumentType, doc.type_id)
    sig_required = dt.requires_signature
    if inst:
        spec = spec_of(db.get(WorkflowVersion, inst.version_id))
        if spec.signature_required is not None:
            sig_required = spec.signature_required
        has_sig_stage = any(s.type == "signature" for s in spec.stages)
        sig_required = sig_required and has_sig_stage
    if sig_required:
        sigs = db.execute(select(SignatureRecord).where(SignatureRecord.revision_id == rev.id)).scalars().all()
        prov = get_provider()
        valid = bool(sigs) and all(s.signed_sha256 == rev.sha256 and prov.validate(s.signature_b64, s.certificate_pem, rev.sha256).valid for s in sigs)
        checks.append({"key": "signatures", "label": f"Digital signatures valid ({len(sigs)})", "ok": valid})
    return checks


def _register(db: Session, actor: User, doc: Document, rev: DocumentRevision, package_id: uuid.UUID | None, note: str | None) -> ReleaseRegisterEntry:
    now = utcnow()
    prev = db.execute(select(ReleaseRegisterEntry).where(ReleaseRegisterEntry.document_id == doc.id, ReleaseRegisterEntry.status == "RELEASED")).scalars().all()
    sig_count = len(db.execute(select(SignatureRecord.id).where(SignatureRecord.revision_id == rev.id)).all())
    entry = ReleaseRegisterEntry(
        release_no=f"REL-{now.year}-{next_seq(db, f'release:{now.year}'):05d}", package_id=package_id, document_id=doc.id, revision_id=rev.id,
        project_id=doc.project_id, item_id=doc.item_id, owner_org_unit_id=doc.owner_org_unit_id, sha256=rev.sha256 or "",
        signature_count=sig_count, released_by_id=actor.id, released_at=now, status="RELEASED", status_reason=note,
    )
    db.add(entry)
    db.flush()
    for p in prev:
        p.status = "SUPERSEDED"
        p.superseded_by_id = entry.id
        old = db.get(DocumentRevision, p.revision_id)
        if old:
            old.status = "SUPERSEDED"
    rev.status = "RELEASED"
    rev.released_at = now
    rev.locked = True
    doc.status = "RELEASED"
    doc.released_revision_id = rev.id
    doc.version += 1
    audit.record(db, actor_id=actor.id, action="release.register", entity_type="document", entity_id=doc.id,
                 summary=f"{doc.number} rev {rev.label} released as {entry.release_no}", data={"sha256": rev.sha256, "package": str(package_id) if package_id else None, "superseded": [p.release_no for p in prev]})
    notify(db, doc.owner_id, "release.done", f"Released: {doc.number} rev {rev.label}", f"Registered as {entry.release_no}", link=f"/documents/{doc.id}", severity="success")
    return entry


def release_revision(db: Session, actor: User, doc: Document, rev: DocumentRevision, note: str | None = None, enforce_authority: bool = True) -> ReleaseRegisterEntry:
    failed = [c for c in release_checks(db, doc, rev) if not c["ok"]]
    if failed:
        raise AppError("Release gate not satisfied: " + "; ".join(c["label"] for c in failed), code="RELEASE_GATE", details={"failed": failed})
    return _register(db, actor, doc, rev, None, note)


def release_package(db: Session, actor: User, pkg: ReleasePackage) -> ReleasePackage:
    if pkg.status != "DRAFT":
        raise Conflict("Package is already released.")
    items = db.execute(select(ReleasePackageItem).where(ReleasePackageItem.package_id == pkg.id)).scalars().all()
    if not items:
        raise AppError("Add at least one approved document to the package.")
    manifest = {"package": pkg.code, "title": pkg.title, "released_at": utcnow().isoformat(), "released_by": actor.username, "items": []}
    for it in items:
        doc, rev = db.get(Document, it.document_id), db.get(DocumentRevision, it.revision_id)
        failed = [c for c in release_checks(db, doc, rev) if not c["ok"]]
        if failed:
            raise AppError(f"{doc.number}: " + "; ".join(c["label"] for c in failed), code="RELEASE_GATE")
    for it in items:
        doc, rev = db.get(Document, it.document_id), db.get(DocumentRevision, it.revision_id)
        _register(db, actor, doc, rev, pkg.id, pkg.release_note)
        sigs = db.execute(select(SignatureRecord).where(SignatureRecord.revision_id == rev.id)).scalars().all()
        manifest["items"].append({"document": doc.number, "title": doc.title, "revision": rev.label, "revision_id": str(rev.id), "sha256": rev.sha256,
                                  "signatures": [{"serial": s.certificate_serial, "role": s.signer_role, "at": s.signed_at.isoformat()} for s in sigs]})
    pkg.manifest_json = json.dumps(manifest, sort_keys=True)
    pkg.manifest_sha256 = hashlib.sha256(pkg.manifest_json.encode()).hexdigest()
    pkg.status = "RELEASED"
    pkg.released_by_id = actor.id
    pkg.released_at = utcnow()
    audit.record(db, actor_id=actor.id, action="release.package", entity_type="release_package", entity_id=pkg.id, summary=f"Release package {pkg.code} released ({len(items)} documents)", data={"manifest_sha256": pkg.manifest_sha256})
    return pkg


def withdraw_entry(db: Session, actor: User, entry: ReleaseRegisterEntry, reason: str) -> ReleaseRegisterEntry:
    if entry.status != "RELEASED":
        raise Conflict("Only a current release can be withdrawn.")
    if not reason or len(reason.strip()) < 5:
        raise AppError("A withdrawal reason is mandatory.", code="COMMENT_REQUIRED")
    entry.status = "WITHDRAWN"
    entry.status_reason = reason
    rev = db.get(DocumentRevision, entry.revision_id)
    doc = db.get(Document, entry.document_id)
    rev.status = "WITHDRAWN"
    if doc.released_revision_id == rev.id:
        doc.status = "WITHDRAWN" if doc.current_revision_id == rev.id else doc.status
        doc.released_revision_id = None
    doc.version += 1
    audit.record(db, actor_id=actor.id, action="release.withdraw", entity_type="document", entity_id=doc.id, summary=f"{entry.release_no} withdrawn: {reason}")
    return entry
