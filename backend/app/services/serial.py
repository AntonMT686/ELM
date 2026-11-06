"""Response serializers (stable public shapes; never expose secrets / storage paths)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import (
    Document,
    DocumentRevision,
    DocumentType,
    EngineeringItem,
    OrgUnit,
    ProcessDomain,
    Project,
    User,
)


def iso(v):
    return v.isoformat() if v else None


def user_brief(u: User | None) -> dict | None:
    if not u:
        return None
    return {"id": str(u.id), "username": u.username, "full_name": u.full_name, "designation": u.designation, "email": u.email}


def org_brief(o: OrgUnit | None) -> dict | None:
    if not o:
        return None
    return {"id": str(o.id), "code": o.code, "name": o.name, "unit_type": o.unit_type}


def doc_type_dict(t: DocumentType) -> dict:
    return {
        "id": str(t.id), "code": t.code, "name": t.name, "category": t.category, "description": t.description,
        "numbering_pattern": t.numbering_pattern, "revision_scheme": t.revision_scheme, "allowed_extensions": t.allowed_extensions,
        "default_template": t.default_template, "requires_signature": t.requires_signature, "require_review_checklist": t.require_review_checklist, "applicable_levels": t.applicable_levels,
        "icon": t.icon, "color": t.color, "active": t.active,
    }


def revision_dict(db: Session, r: DocumentRevision | None) -> dict | None:
    if not r:
        return None
    f = r.file
    return {
        "id": str(r.id), "revision_no": r.revision_no, "label": r.label, "iteration": r.iteration, "status": r.status, "locked": r.locked,
        "sha256": r.sha256, "change_summary": r.change_summary, "created_at": iso(r.created_at), "approved_at": iso(r.approved_at),
        "released_at": iso(r.released_at), "created_by": user_brief(db.get(User, r.created_by_id)),
        "file": {"name": f.original_name, "extension": f.extension, "size": f.size_bytes, "mime": f.mime_type} if f else None,
    }


def item_brief(db: Session, it: EngineeringItem | None) -> dict | None:
    if not it:
        return None
    return {"id": str(it.id), "code": it.code, "name": it.name, "level": it.level.code, "level_name": it.level.name}


def doc_dict(db: Session, d: Document, full: bool = False) -> dict:
    t = db.get(DocumentType, d.type_id)
    p = db.get(Project, d.project_id) if d.project_id else None
    it = db.get(EngineeringItem, d.item_id) if d.item_id else None
    cur = db.get(DocumentRevision, d.current_revision_id) if d.current_revision_id else None
    rel = db.get(DocumentRevision, d.released_revision_id) if d.released_revision_id else None
    out = {
        "id": str(d.id), "number": d.number, "title": d.title, "status": d.status, "classification": d.classification,
        "type": {"id": str(t.id), "code": t.code, "name": t.name, "category": t.category, "color": t.color, "icon": t.icon},
        "project": {"id": str(p.id), "code": p.code, "name": p.name} if p else None,
        "item": item_brief(db, it),
        "owner": user_brief(db.get(User, d.owner_id)),
        "owner_org": org_brief(db.get(OrgUnit, d.owner_org_unit_id)) if d.owner_org_unit_id else None,
        "current_revision": {"id": str(cur.id), "label": cur.label, "iteration": cur.iteration, "status": cur.status, "ext": cur.file.extension if cur and cur.file else None} if cur else None,
        "released_revision": {"id": str(rel.id), "label": rel.label} if rel else None,
        "updated_at": iso(d.updated_at), "created_at": iso(d.created_at), "version": d.version,
    }
    if full:
        dom = db.get(ProcessDomain, d.domain_id) if d.domain_id else None
        out.update({"description": d.description, "keywords": d.keywords, "external_ref": d.external_ref, "domain": {"id": str(dom.id), "code": dom.code, "name": dom.name} if dom else None,
                    "current_revision_full": revision_dict(db, cur)})
    return out
