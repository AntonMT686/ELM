"""Protected file storage adapter (local volume / NAS). Content-addressed keys generated server-side only."""
from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import FileObject

MAGIC = {
    "pdf": [b"%PDF"],
    "docx": [b"PK\x03\x04"],
    "xlsx": [b"PK\x03\x04"],
    "pptx": [b"PK\x03\x04"],
    "vsdx": [b"PK\x03\x04"],
    "zip": [b"PK\x03\x04"],
    "png": [b"\x89PNG"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "drawio": [b"<mxfile", b"<?xml"],
    "xml": [b"<?xml", b"<"],
}
OFFICE_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_name(name: str) -> str:
    base = os.path.basename(name or "file").strip() or "file"
    return _SAFE.sub("_", base)[:200]


def ext_of(name: str) -> str:
    return (name.rsplit(".", 1)[-1] if "." in name else "").lower()


def _root() -> Path:
    return get_settings().storage_dir


def validate_content(data: bytes, ext: str, allowed: list[str]) -> None:
    s = get_settings()
    if allowed and ext not in allowed:
        raise AppError(f"File type .{ext} is not allowed for this document type. Allowed: {', '.join(allowed)}", code="FILE_TYPE")
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise AppError(f"File exceeds the {s.max_upload_mb} MB limit.", code="FILE_TOO_LARGE")
    if not data:
        raise AppError("File is empty.", code="FILE_EMPTY")
    sigs = MAGIC.get(ext)
    if sigs and not any(data.lstrip()[: len(m)] == m for m in sigs):
        raise AppError("File content does not match its extension.", code="FILE_SIGNATURE")


def put_bytes(db: Session, data: bytes, original_name: str, user_id: uuid.UUID | None) -> FileObject:
    sha = hashlib.sha256(data).hexdigest()
    ext = ext_of(original_name)
    key = f"{sha[:2]}/{sha[2:4]}/{sha}-{uuid.uuid4().hex[:8]}"
    path = _root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    mime = OFFICE_MIME.get(ext) or mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    fo = FileObject(
        storage_key=key,
        original_name=safe_name(original_name),
        mime_type=mime,
        extension=ext,
        size_bytes=len(data),
        sha256=sha,
        created_by_id=user_id,
        scan_status="NOT_SCANNED",
    )
    db.add(fo)
    db.flush()
    return fo


def read_bytes(fo: FileObject, verify: bool = False) -> bytes:
    data = (_root() / fo.storage_key).read_bytes()
    if verify and hashlib.sha256(data).hexdigest() != fo.sha256:
        raise AppError("Stored file failed integrity verification.", code="INTEGRITY", status_code=500)
    return data


def file_path(fo: FileObject) -> Path:
    return _root() / fo.storage_key
