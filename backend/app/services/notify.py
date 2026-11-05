from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.models import Notification


def notify(
    db: Session,
    user_id: uuid.UUID,
    kind: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
    severity: str = "info",
    dedupe_key: str | None = None,
) -> Notification | None:
    """In-app notification (primary channel). De-duplicated by key within 24 h."""
    if dedupe_key:
        exists = db.execute(
            select(Notification.id).where(
                Notification.user_id == user_id,
                Notification.dedupe_key == dedupe_key,
                Notification.created_at >= utcnow() - timedelta(hours=24),
            )
        ).first()
        if exists:
            return None
    n = Notification(user_id=user_id, kind=kind, title=title, body=body, link=link, severity=severity, dedupe_key=dedupe_key)
    db.add(n)
    return n
