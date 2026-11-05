"""Explainable progress roll-up: engineering item subtree → documents (weights configurable)."""
from __future__ import annotations

import json
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, EngineeringItem, SystemSetting
from app.services.workflow_spec import DEFAULT_WEIGHTS

STATUSES = ["DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "REJECTED", "APPROVED", "RELEASED"]


def weights(db: Session) -> dict[str, int]:
    row = db.get(SystemSetting, "progress.weights")
    if row:
        try:
            return {**DEFAULT_WEIGHTS, **json.loads(row.value)}
        except ValueError:
            pass
    return dict(DEFAULT_WEIGHTS)


def item_rollup(db: Session, project_id: uuid.UUID, visible_doc_ids: set[uuid.UUID] | None = None) -> dict[str, dict]:
    w = weights(db)
    items = db.execute(select(EngineeringItem.id, EngineeringItem.parent_id).where(EngineeringItem.project_id == project_id)).all()
    children: dict[uuid.UUID | None, list[uuid.UUID]] = defaultdict(list)
    for iid, pid in items:
        children[pid].append(iid)
    direct: dict[uuid.UUID, list[str]] = defaultdict(list)
    q = select(Document.id, Document.item_id, Document.status).where(Document.project_id == project_id, Document.item_id.is_not(None))
    for did, iid, st in db.execute(q).all():
        if visible_doc_ids is not None and did not in visible_doc_ids:
            continue
        direct[iid].append("RELEASED" if st in ("SUPERSEDED",) else st)
    out: dict[str, dict] = {}

    def walk(iid: uuid.UUID) -> dict:
        counts = defaultdict(int)
        for st in direct.get(iid, []):
            counts[st] += 1
        for c in children.get(iid, []):
            sub = walk(c)
            for k, v in sub["counts"].items():
                counts[k] += v
        total = sum(v for k, v in counts.items() if k not in ("WITHDRAWN", "OBSOLETE"))
        score = sum(w.get(k, 0) * v for k, v in counts.items() if k not in ("WITHDRAWN", "OBSOLETE"))
        res = {"counts": dict(counts), "total": total, "released": counts.get("RELEASED", 0), "progress": round(score / total, 1) if total else 0.0}
        out[str(iid)] = res
        return res

    for root in children.get(None, []):
        walk(root)
    return out
