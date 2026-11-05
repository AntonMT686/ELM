"""OnlyOffice endpoints. `/config` is user-authenticated; `/file` and `/callback` are called server-to-server
by the Document Server and are authenticated with short-lived scoped tokens + the OnlyOffice JWT secret."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import Ctx, get_ctx, get_or_404
from app.core.errors import AppError, Forbidden
from app.core.security import decode_token
from app.models import Document, DocumentRevision, User
from app.services import documents as docsvc
from app.services import onlyoffice as oo
from app.services import storage
from app.services.authz import can_on_document

router = APIRouter(prefix="/onlyoffice", tags=["onlyoffice"])
log = logging.getLogger("elm.onlyoffice")


@router.get("/config/{rid}")
def config(rid: uuid.UUID, mode: str = "edit", ctx: Ctx = Depends(get_ctx)):
    if not get_settings().onlyoffice_enabled:
        raise AppError("Online editor is disabled in this environment.", code="EDITOR_DISABLED")
    rev = get_or_404(ctx.db, DocumentRevision, rid, "Revision")
    doc = ctx.db.get(Document, rev.document_id)
    if not can_on_document(ctx.db, ctx.p, doc, "doc.view"):
        raise Forbidden("You do not have access to this document.")
    can_edit = mode == "edit" and doc.current_revision_id == rev.id and can_on_document(ctx.db, ctx.p, doc, "doc.edit")
    cfg = oo.editor_config(doc, rev, ctx.user, can_edit)
    ctx.audit("document.editor_open", "document", doc.id, f"Opened {doc.number} rev {rev.label} in editor ({cfg['mode']})")
    ctx.db.commit()
    return cfg


@router.get("/file/{rid}")
def file(rid: uuid.UUID, t: str = Query(...), db: Session = Depends(get_db)):
    claims = decode_token(t, "oo_file")
    if not claims or claims.get("rid") != str(rid):
        raise Forbidden("Invalid file token.")
    rev = get_or_404(db, DocumentRevision, rid, "Revision")
    if not rev.file:
        raise AppError("No content.")
    return FileResponse(storage.file_path(rev.file), media_type=rev.file.mime_type, filename=rev.file.original_name)


@router.post("/callback/{rid}")
async def callback(rid: uuid.UUID, request: Request, t: str = Query(...), db: Session = Depends(get_db)):
    """OnlyOffice save callback. status 2 = ready to save, 6 = force-save. Must answer {"error": 0}."""
    claims = decode_token(t, "oo_cb")
    if not claims or claims.get("rid") != str(rid):
        return JSONResponse({"error": 1, "message": "invalid token"}, status_code=403)
    body = await request.json()
    try:
        body = oo.verify_callback_jwt(body, request.headers.get(get_settings().onlyoffice_jwt_header))
    except AppError:
        return JSONResponse({"error": 1, "message": "invalid jwt"}, status_code=403)
    status = body.get("status")
    if status not in (2, 6):
        return {"error": 0}
    rev = db.get(DocumentRevision, rid)
    if not rev:
        return {"error": 1}
    doc = db.get(Document, rev.document_id)
    editor_ids = body.get("users") or [claims.get("uid")]
    user = db.get(User, uuid.UUID(str(editor_ids[0]))) if editor_ids and editor_ids[0] else db.get(User, uuid.UUID(claims["uid"]))
    try:
        data = oo.fetch_saved_file(body["url"])
        ext = rev.file.extension if rev.file else (body.get("filetype") or "docx")
        docsvc.add_iteration(db, user, doc, rev, f"{doc.number}.{ext}", data, source="ONLYOFFICE", note="Saved from online editor", validate=False)
        db.commit()
    except AppError as e:
        # Revision locked (submitted for review) → never overwrite reviewed content.
        log.warning("OnlyOffice save rejected for %s: %s", rid, e.message)
        db.rollback()
        return {"error": 0 if status == 6 else 1}
    return {"error": 0}
