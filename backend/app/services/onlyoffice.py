"""OnlyOffice Document Server integration (self-hosted). JWT-signed editor config + version-safe save callbacks."""
from __future__ import annotations

import urllib.parse
import urllib.request
import uuid

import jwt

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import create_scoped_token
from app.models import Document, DocumentRevision, User

DOC_TYPES = {"docx": "word", "doc": "word", "odt": "word", "rtf": "word", "txt": "word", "pdf": "pdf",
             "xlsx": "cell", "xls": "cell", "ods": "cell", "csv": "cell", "pptx": "slide", "ppt": "slide", "odp": "slide"}
EDITABLE = {"docx", "xlsx", "pptx", "odt", "ods", "odp"}


def editor_config(doc: Document, rev: DocumentRevision, user: User, can_edit: bool) -> dict:
    s = get_settings()
    if not rev.file:
        raise AppError("This revision has no content yet.", code="NO_CONTENT")
    ext = rev.file.extension
    if ext not in DOC_TYPES:
        raise AppError(f".{ext} files cannot be opened in the online editor.", code="EDITOR_UNSUPPORTED")
    mode = "edit" if (can_edit and ext in EDITABLE and not rev.locked) else "view"
    file_tok = create_scoped_token("oo_file", minutes=60, rid=str(rev.id), sha=rev.sha256)
    cb_tok = create_scoped_token("oo_cb", minutes=60 * 12, rid=str(rev.id), uid=str(user.id), it=rev.iteration)
    base = s.backend_internal_url.rstrip("/")
    cfg = {
        "documentType": DOC_TYPES[ext],
        "document": {
            "fileType": ext,
            # key changes whenever content changes so co-editing sessions never mix iterations
            "key": f"{rev.id.hex[:20]}-{rev.iteration}-{(rev.sha256 or '')[:12]}",
            "title": f"{doc.number} rev {rev.label} - {doc.title}.{ext}"[:180],
            "url": f"{base}/api/v1/onlyoffice/file/{rev.id}?t={file_tok}",
            "permissions": {"edit": mode == "edit", "download": True, "print": True, "comment": True, "review": mode == "edit", "copy": True},
        },
        "editorConfig": {
            "mode": mode,
            "lang": "en",
            "callbackUrl": f"{base}/api/v1/onlyoffice/callback/{rev.id}?t={cb_tok}",
            "user": {"id": str(user.id), "name": user.full_name},
            "customization": {"autosave": True, "forcesave": True, "compactHeader": True, "toolbarNoTabs": False, "feedback": False, "help": False, "chat": False, "plugins": False, "uiTheme": "theme-light"},
        },
        "height": "100%",
        "width": "100%",
    }
    if s.onlyoffice_jwt_secret:
        cfg["token"] = jwt.encode(cfg, s.onlyoffice_jwt_secret, algorithm="HS256")
    return {"documentServerUrl": s.onlyoffice_public_url.rstrip("/"), "mode": mode, "config": cfg}


def verify_callback_jwt(body: dict, auth_header: str | None) -> dict:
    s = get_settings()
    if not s.onlyoffice_jwt_secret:
        return body
    token = body.get("token")
    if not token and auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:]
    if not token:
        raise AppError("Missing OnlyOffice token.", status_code=403, code="OO_TOKEN")
    try:
        payload = jwt.decode(token, s.onlyoffice_jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise AppError("Invalid OnlyOffice token.", status_code=403, code="OO_TOKEN") from e
    return payload.get("payload", payload)


def fetch_saved_file(url: str) -> bytes:
    """Download the saved document from OnlyOffice. Host allow-list prevents SSRF."""
    s = get_settings()
    allowed = {urllib.parse.urlparse(u).netloc for u in (s.onlyoffice_internal_url, s.onlyoffice_public_url) if u}
    target = urllib.parse.urlparse(url)
    if target.scheme not in ("http", "https") or target.netloc not in allowed:
        # OnlyOffice may report its public host; rewrite to the internal one if configured.
        pub = urllib.parse.urlparse(s.onlyoffice_public_url)
        if target.netloc == pub.netloc:
            url = url.replace(f"{pub.scheme}://{pub.netloc}", s.onlyoffice_internal_url.rstrip("/"), 1)
        else:
            raise AppError("Callback file URL host is not allowed.", status_code=403, code="OO_SSRF")
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 - host allow-listed above
        return r.read()


def parse_rid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as e:
        raise AppError("Bad revision id.") from e
