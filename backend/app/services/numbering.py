"""Configurable document numbering, e.g. "{PROJECT}-{ITEM}-{TYPE}-{SEQ:4}" → AMCA-FCS-SRS-0003."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NumberSequence

_TOKEN = re.compile(r"\{([A-Z_]+)(?::(\d+))?\}")


def next_seq(db: Session, key: str) -> int:
    row = db.execute(select(NumberSequence).where(NumberSequence.key == key).with_for_update()).scalar_one_or_none()
    if row is None:
        row = NumberSequence(key=key, next_value=1)
        db.add(row)
        db.flush()
    val = row.next_value
    row.next_value = val + 1
    return val


def render_number(db: Session, pattern: str, tokens: dict[str, str]) -> str:
    prefix = _TOKEN.sub(lambda m: tokens.get(m.group(1), m.group(1)) if m.group(1) != "SEQ" else "#", pattern)
    width = 4
    for m in _TOKEN.finditer(pattern):
        if m.group(1) == "SEQ" and m.group(2):
            width = int(m.group(2))
    seq = next_seq(db, f"doc:{prefix}")
    out = _TOKEN.sub(lambda m: str(seq).zfill(width) if m.group(1) == "SEQ" else tokens.get(m.group(1), m.group(1)), pattern)
    return re.sub(r"-{2,}", "-", out).strip("-")


def revision_label(scheme: str, n: int) -> str:
    if scheme == "NUMERIC":
        return f"{n:02d}"
    label = ""
    while n > 0:  # 1→A … 26→Z, 27→AA (I and O skipped per common drawing practice)
        n, r = divmod(n - 1, 24)
        label = "ABCDEFGHJKLMNPQRSTUVWXYZ"[r] + label
    return label
