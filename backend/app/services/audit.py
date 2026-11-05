"""Append-only, hash-chained audit trail. Each event hash = SHA256(prev_hash | canonical event)."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.models import AuditChainHead, AuditEvent

GENESIS = "0" * 64


def _ts(at) -> str:
    # Normalise to naive UTC so the hash is identical whatever the DB driver returns.
    if at.tzinfo is not None:
        at = at.astimezone(timezone.utc).replace(tzinfo=None)
    return at.isoformat(timespec="microseconds")


def _canon(ev: AuditEvent) -> str:
    return json.dumps(
        {
            "id": str(ev.id),
            "at": _ts(ev.at),
            "actor": str(ev.actor_id) if ev.actor_id else None,
            "obo": str(ev.on_behalf_of_id) if ev.on_behalf_of_id else None,
            "action": ev.action,
            "etype": ev.entity_type,
            "eid": ev.entity_id,
            "summary": ev.summary,
            "data": ev.data,
            "outcome": ev.outcome,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def compute_hash(prev: str, ev: AuditEvent) -> str:
    return hashlib.sha256((prev + "|" + _canon(ev)).encode()).hexdigest()


def record(
    db: Session,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: Any = None,
    summary: str,
    data: dict | None = None,
    ip: str | None = None,
    request_id: str | None = None,
    on_behalf_of_id: uuid.UUID | None = None,
    outcome: str = "SUCCESS",
) -> AuditEvent:
    """Writes within the caller's transaction so the business change and its audit commit atomically."""
    head = db.execute(select(AuditChainHead).where(AuditChainHead.id == 1).with_for_update()).scalar_one_or_none()
    if head is None:
        head = AuditChainHead(id=1, last_hash=GENESIS, last_seq=0)
        db.add(head)
        db.flush()
    ev = AuditEvent(
        id=uuid.uuid4(),
        at=utcnow(),
        actor_id=actor_id,
        on_behalf_of_id=on_behalf_of_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        summary=summary[:500],
        data=json.dumps(data, default=str, sort_keys=True) if data else None,
        ip=ip,
        request_id=request_id,
        outcome=outcome,
        prev_hash=head.last_hash,
    )
    ev.hash = compute_hash(head.last_hash, ev)
    db.add(ev)
    db.flush()
    head.last_hash = ev.hash
    head.last_seq = ev.seq
    return ev


def verify_chain(db: Session, limit: int | None = None) -> dict:
    prev = GENESIS
    count = 0
    q = select(AuditEvent).order_by(AuditEvent.seq)
    for ev in db.execute(q).scalars():
        if ev.prev_hash != prev or compute_hash(prev, ev) != ev.hash:
            return {"valid": False, "checked": count, "broken_at_seq": ev.seq}
        prev = ev.hash
        count += 1
        if limit and count >= limit:
            break
    return {"valid": True, "checked": count, "broken_at_seq": None}
