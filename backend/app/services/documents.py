"""Document register use-cases: create, upload iteration, revise, template stamping, relations."""
from __future__ import annotations

import io
import uuid
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import AppError, Conflict
from app.models import (
    Document,
    DocumentRevision,
    DocumentType,
    EngineeringItem,
    OrgUnit,
    Project,
    RevisionIteration,
    User,
)
from app.services import audit, storage
from app.services.numbering import render_number, revision_label

TEMPLATES = Path(__file__).resolve().parent.parent / "assets" / "templates"


def stamp_template(kind: str, values: dict[str, str]) -> bytes:
    """Fill {{PLACEHOLDER}} tokens in an OOXML template (document, headers, footers, slides, sheets)."""
    src = (TEMPLATES / f"blank.{kind}").read_bytes()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(src)) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.endswith(".xml"):
                text = data.decode("utf-8")
                for k, v in values.items():
                    text = text.replace("{{" + k + "}}", escape(v or ""))
                data = text.encode("utf-8")
            zout.writestr(item, data)
    return out.getvalue()


def _tokens(db: Session, dt: DocumentType, project: Project | None, item: EngineeringItem | None, org: OrgUnit | None) -> dict[str, str]:
    return {"PROJECT": project.code if project else "GEN", "ITEM": item.code if item else "", "TYPE": dt.code, "ORG": org.code if org else "", "YEAR": str(utcnow().year)}


def create_document(
    db: Session,
    user: User,
    *,
    type_id: uuid.UUID,
    title: str,
    project_id: uuid.UUID | None,
    item_id: uuid.UUID | None,
    owner_org_unit_id: uuid.UUID | None,
    domain_id: uuid.UUID | None,
    classification: str,
    description: str | None,
    keywords: str | None,
    content: tuple[str, bytes] | None,
    from_template: bool,
    parent_id: uuid.UUID | None = None,
) -> Document:
    dt = db.get(DocumentType, type_id)
    if not dt or not dt.active:
        raise AppError("Unknown document type.")
    project = db.get(Project, project_id) if project_id else None
    item = db.get(EngineeringItem, item_id) if item_id else None
    if item and project and item.project_id != project.id:
        raise AppError("The engineering item does not belong to the selected project.")
    if item and not project:
        project = db.get(Project, item.project_id)
    if dt.applicable_levels and item:
        lvl = item.level.code
        if lvl not in [x.strip() for x in dt.applicable_levels.split(",")]:
            raise AppError(f"{dt.name} is not applicable at {item.level.name} level.", code="LEVEL_NOT_APPLICABLE")
    org = db.get(OrgUnit, owner_org_unit_id) if owner_org_unit_id else (item and item.lead_org_unit_id and db.get(OrgUnit, item.lead_org_unit_id)) or user.primary_org_unit
    number = render_number(db, dt.numbering_pattern, _tokens(db, dt, project, item, org))
    doc = Document(
        number=number, title=title.strip(), description=description, type_id=dt.id, project_id=project.id if project else None,
        item_id=item.id if item else None, domain_id=domain_id or (item.domain_id if item else None), owner_org_unit_id=org.id if org else None,
        originating_org_unit_id=user.primary_org_unit_id, owner_id=user.id, classification=classification, keywords=keywords, status="DRAFT",
    )
    db.add(doc)
    db.flush()
    rev = DocumentRevision(document_id=doc.id, revision_no=1, label=revision_label(dt.revision_scheme, 1), iteration=0, status="DRAFT", created_by_id=user.id, change_summary="Initial issue")
    db.add(rev)
    db.flush()
    doc.current_revision_id = rev.id
    if content:
        add_iteration(db, user, doc, rev, content[0], content[1], source="UPLOAD")
    elif from_template and dt.default_template:
        values = {
            "DOC_NUMBER": number, "TITLE": doc.title, "DOC_TYPE": dt.name, "REVISION": rev.label, "PROJECT": project.name if project else "",
            "ITEM": f"{item.code} — {item.name}" if item else "", "OWNER_ORG": org.name if org else "", "OWNER": user.full_name,
            "DATE": utcnow().strftime("%d %b %Y"), "CLASSIFICATION": classification, "ORG": "Aeronautical Development Agency",
        }
        add_iteration(db, user, doc, rev, f"{number}.{dt.default_template}", stamp_template(dt.default_template, values), source="TEMPLATE", validate=False)
    if parent_id:
        from app.models import DocumentRelation

        parent = db.get(Document, parent_id)
        if parent:
            db.add(DocumentRelation(source_id=parent.id, target_id=doc.id, relation_type="PARENT_OF", source_revision_id=parent.current_revision_id, created_by_id=user.id))
    audit.record(db, actor_id=user.id, action="document.create", entity_type="document", entity_id=doc.id, summary=f"Created {number} — {doc.title}", data={"type": dt.code, "project": project.code if project else None, "item": item.code if item else None})
    return doc


def add_iteration(db: Session, user: User, doc: Document, rev: DocumentRevision, filename: str, data: bytes, source: str = "UPLOAD", note: str | None = None, validate: bool = True) -> RevisionIteration:
    if rev.locked or rev.status not in ("DRAFT", "CHANGES_REQUESTED", "REJECTED"):
        raise Conflict(f"Revision {rev.label} is {rev.status.replace('_', ' ').lower()} and cannot be modified. Create a new revision instead.")
    dt = db.get(DocumentType, doc.type_id)
    ext = storage.ext_of(filename)
    if validate:
        storage.validate_content(data, ext, [x.strip() for x in dt.allowed_extensions.split(",") if x.strip()])
    fo = storage.put_bytes(db, data, filename, user.id)
    if rev.sha256 == fo.sha256:
        return db.execute(select(RevisionIteration).where(RevisionIteration.revision_id == rev.id).order_by(RevisionIteration.iteration.desc())).scalars().first()
    rev.iteration += 1
    it = RevisionIteration(revision_id=rev.id, iteration=rev.iteration, file_id=fo.id, sha256=fo.sha256, source=source, note=note, created_by_id=user.id)
    db.add(it)
    rev.file_id = fo.id
    rev.sha256 = fo.sha256
    doc.version += 1
    doc.updated_at = utcnow()
    audit.record(db, actor_id=user.id, action="document.content", entity_type="document", entity_id=doc.id, summary=f"{doc.number} rev {rev.label}.{rev.iteration} saved ({source.lower()})", data={"sha256": fo.sha256, "size": fo.size_bytes, "file": fo.original_name})
    return it


def revise(db: Session, user: User, doc: Document, change_summary: str) -> DocumentRevision:
    cur = db.get(DocumentRevision, doc.current_revision_id)
    if cur and cur.status not in ("RELEASED", "WITHDRAWN", "SUPERSEDED"):
        raise Conflict("A new revision can be started only after the current revision is released (or withdrawn).")
    dt = db.get(DocumentType, doc.type_id)
    n = (db.execute(select(func.max(DocumentRevision.revision_no)).where(DocumentRevision.document_id == doc.id)).scalar() or 0) + 1
    rev = DocumentRevision(document_id=doc.id, revision_no=n, label=revision_label(dt.revision_scheme, n), iteration=0, status="DRAFT", created_by_id=user.id, change_summary=change_summary, derived_from_revision_id=cur.id if cur else None)
    db.add(rev)
    db.flush()
    if cur and cur.file:
        data = storage.read_bytes(cur.file, verify=True)
        add_iteration(db, user, doc, rev, cur.file.original_name, data, source="COPY", note=f"Copied from rev {cur.label}", validate=False)
    if cur:
        from app.services import doc_checklist

        doc_checklist.copy_forward(db, cur, rev, user.id)  # the author adapts it for the new revision
    doc.current_revision_id = rev.id
    doc.status = "DRAFT"
    doc.version += 1
    audit.record(db, actor_id=user.id, action="document.revise", entity_type="document", entity_id=doc.id, summary=f"{doc.number}: revision {rev.label} started — {change_summary}")
    return rev
