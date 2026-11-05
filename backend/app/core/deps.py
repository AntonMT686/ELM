from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import Unauthorized
from app.core.security import decode_token
from app.models import User
from app.services import audit
from app.services.authz import Principal, load_principal


@dataclass
class Ctx:
    db: Session
    p: Principal
    request: Request

    @property
    def user(self) -> User:
        return self.p.user

    def audit(self, action: str, entity_type: str, entity_id, summary: str, data: dict | None = None, **kw):
        return audit.record(
            self.db,
            actor_id=self.user.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary,
            data=data,
            ip=self.request.client.host if self.request.client else None,
            request_id=getattr(self.request.state, "request_id", None),
            **kw,
        )


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(get_settings().cookie_name)
    if not token:
        raise Unauthorized("Please sign in.")
    payload = decode_token(token)
    if not payload:
        raise Unauthorized("Your session has expired. Please sign in again.")
    user = db.get(User, uuid.UUID(payload["sub"]))
    if not user or not user.is_active:
        raise Unauthorized("Account is not active.")
    return user


def get_ctx(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Ctx:
    return Ctx(db=db, p=load_principal(db, user), request=request)


def get_or_404(db: Session, model, oid, what: str = "Record"):
    obj = db.get(model, oid)
    if obj is None:
        from app.core.errors import NotFound

        raise NotFound(f"{what} not found.")
    return obj
