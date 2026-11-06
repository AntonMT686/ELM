"""Requirements tagged in documents (architecture §10.2, PROJECT_CONTEXT §8.2 "in-document tagging").

* Each requirement source has a tag format, e.g. ``{PREFIX}-{SEQ:4}`` → ``ALPHA-CPU-0007`` or
  ``{PROJECT}-{ITEM}-SRS-{SEQ:3}`` → ``ALPHA-CTL-CPU-SRS-012``. Tokens: PREFIX (the source's key prefix), PROJECT,
  ITEM (code of the breakdown item the requirement belongs to), LEVEL (code of that item's level) and SEQ:n
  (running number, n digits). The format must contain SEQ exactly once.
* A Word document (.docx) is read paragraph by paragraph, including tables, with the nearest heading as its section.
  A paragraph is a candidate when it already carries a tag in the source's format, or (optionally) when it contains a
  "shall" statement that has no tag yet.
* Importing creates or updates the requirements, links each to the document and section, and can write the newly
  assigned tags back into the document as a new iteration of its current revision (``[TAG] `` at the start of the
  paragraph), so document and register stay in step. Approved or baselined requirements are never overwritten.
"""
from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import EngineeringItem, HierarchyLevel, NumberSequence, Project

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TOKEN = re.compile(r"\{(PREFIX|PROJECT|ITEM|LEVEL|SEQ(?::(\d))?)\}")
SHALL = re.compile(r"\b(shall|must)\b", re.I)
DEFAULT_FORMAT = "{PREFIX}-{SEQ:4}"
NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+){0,5})\.?\s+(\S.{0,150})$")


def validate_format(fmt: str) -> None:
    seqs = re.findall(r"\{SEQ(?::\d)?\}", fmt)
    if len(seqs) != 1:
        raise AppError("The tag format must contain {SEQ} or {SEQ:n} exactly once, e.g. {PREFIX}-{SEQ:4}.", code="TAG_FORMAT")
    left = TOKEN.sub("", fmt)
    if not re.fullmatch(r"[A-Za-z0-9_.\-/]*", left):
        raise AppError("Besides the {tokens}, a tag format may contain letters, digits and - _ . / only.", code="TAG_FORMAT")
    unknown = set(re.findall(r"\{([^}]*)\}", fmt)) - {"PREFIX", "PROJECT", "ITEM", "LEVEL", "SEQ"} - {f"SEQ:{n}" for n in range(1, 10)}
    if unknown:
        raise AppError(f"Unknown token(s) in the tag format: {', '.join(sorted(unknown))}.", code="TAG_FORMAT")


def _context(db: Session, src, item_id) -> dict:
    project = db.get(Project, src.project_id)
    item = db.get(EngineeringItem, item_id) if item_id else None
    level = db.get(HierarchyLevel, item.level_id) if item and item.level_id else None
    return {"PREFIX": src.key_prefix, "PROJECT": project.code if project else "", "ITEM": item.code if item else "X", "LEVEL": level.code if level else "X"}


def render(fmt: str, ctx: dict, seq: int | None) -> str:
    def sub(m):
        if m.group(1).startswith("SEQ"):
            return "{SEQ}" if seq is None else str(seq).zfill(int(m.group(2) or 1))
        return ctx[m.group(1)]
    return TOKEN.sub(sub, fmt)


def next_tag(db: Session, src, item_id=None) -> str:
    """Next free tag for this source (and item, when the format uses ITEM / LEVEL)."""
    fmt = src.tag_format or DEFAULT_FORMAT
    ctx = _context(db, src, item_id)
    from app.services.numbering import next_seq

    counter = "req:" + render(fmt, ctx, None)
    if fmt == DEFAULT_FORMAT:
        counter = "req:" + src.key_prefix  # same counter as requirements created by hand
    return render(fmt, ctx, next_seq(db, counter))


def note_used(db: Session, src, tag: str, item_id=None) -> None:
    """A tag written by hand in a document moves the counter past it, so a generated tag never collides."""
    fmt = src.tag_format or DEFAULT_FORMAT
    ctx = _context(db, src, item_id)
    pattern = re.escape(render(fmt, ctx, None)).replace(re.escape("{SEQ}"), r"(\d+)")
    m = re.fullmatch(pattern, tag)
    if not m:
        return
    key = "req:" + (src.key_prefix if fmt == DEFAULT_FORMAT else render(fmt, ctx, None))
    row = db.execute(select(NumberSequence).where(NumberSequence.key == key)).scalar_one_or_none()
    if row is None:
        db.add(NumberSequence(key=key, next_value=int(m.group(1)) + 1))
    elif row.next_value <= int(m.group(1)):
        row.next_value = int(m.group(1)) + 1
    db.flush()


def tag_regex(src) -> re.Pattern:
    """Finds tags of this source's format anywhere in a paragraph, with or without [brackets]."""
    fmt = src.tag_format or DEFAULT_FORMAT
    out, pos = "", 0
    for m in TOKEN.finditer(fmt):
        out += re.escape(fmt[pos:m.start()])
        name = m.group(1)
        if name == "PREFIX":
            out += re.escape(src.key_prefix)
        elif name.startswith("SEQ"):
            out += r"\d{%d,}" % int(m.group(2) or 1)
        else:
            out += r"[A-Za-z0-9][A-Za-z0-9_.\-]*?"
        pos = m.end()
    out += re.escape(fmt[pos:])
    return re.compile(r"\[?\b(" + out + r")\b\]?")


# ------------------------------------------------------------------ Word documents
def _xml(data: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return z.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError):
        raise AppError("Only Word documents (.docx) can be scanned for requirements.", code="NOT_DOCX") from None


def paragraphs(data: bytes) -> list[dict]:
    """All paragraphs in document order (tables included), each with its section (nearest heading)."""
    xml = _xml(data)
    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        raise AppError("The document contains XML entity declarations, which are not allowed.", code="FILE_SIGNATURE")
    root = ElementTree.fromstring(xml)
    out, section = [], None
    for n, p in enumerate(root.iter(W + "p")):
        text = "".join(t.text or "" for t in p.iter(W + "t")).strip()
        style_el = p.find(f"{W}pPr/{W}pStyle")
        style = style_el.get(W + "val") if style_el is not None else ""
        is_heading = bool(re.match(r"(?i)^(heading|titre|berschrift)\s*\d", style or "")) or bool(text and NUMBERED_HEADING.match(text) and len(text) < 120 and not SHALL.search(text))
        if is_heading and text:
            section = text[:300]
        out.append({"index": n, "text": text, "style": style, "heading": is_heading, "section": section})
    return out


def write_tags(data: bytes, tags: dict[int, str]) -> bytes:
    """Puts ``[TAG] `` at the start of the given paragraphs (by document-order index). Everything else is unchanged
    byte for byte, so the document's formatting, numbering and other parts are kept."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        files = {i.filename: (i, z.read(i.filename)) for i in z.infolist()}
    xml = files["word/document.xml"][1].decode("utf-8")
    starts = [m for m in re.finditer(r"<w:p(?=[\s>/])[^>]*>", xml)]
    edits = []
    for idx, tag in tags.items():
        if idx >= len(starts):
            continue
        m = starts[idx]
        if m.group(0).endswith("/>"):
            continue  # empty paragraph, nothing to tag
        pos = m.end()
        rest = xml[pos:]
        if rest.startswith("<w:pPr/>"):
            pos += len("<w:pPr/>")
        elif rest.startswith("<w:pPr"):
            pos += rest.index("</w:pPr>") + len("</w:pPr>")
        safe = tag.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        edits.append((pos, f'<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">[{safe}] </w:t></w:r>'))
    for pos, ins in sorted(edits, reverse=True):
        xml = xml[:pos] + ins + xml[pos:]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for name, (info, content) in files.items():
            out.writestr(info, xml.encode("utf-8") if name == "word/document.xml" else content)
    return buf.getvalue()


def strip_tag(text: str, rx: re.Pattern) -> str:
    return re.sub(r"\s{2,}", " ", rx.sub("", text)).strip(" -:–—")


def title_of(text: str) -> str:
    first = re.split(r"(?<=[.;])\s", text, maxsplit=1)[0]
    return (first if len(first) >= 10 else text)[:300]
