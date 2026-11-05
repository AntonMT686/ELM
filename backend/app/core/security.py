"""Password hashing (Argon2id), session tokens (HttpOnly cookie JWT) and CSRF double-submit tokens."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

_ph = PasswordHasher()  # Argon2id defaults


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return _ph.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_session_token(user_id: str, session_id: str | None = None) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "sid": session_id or secrets.token_hex(8),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.access_token_minutes)).timestamp()),
        "typ": "session",
    }
    return jwt.encode(payload, s.secret_key, algorithm="HS256")


def decode_token(token: str, typ: str = "session") -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != typ:
        return None
    return payload


def create_scoped_token(typ: str, minutes: int = 10, **claims: Any) -> str:
    """Short-lived token for backend-mediated file access (e.g. OnlyOffice fetching a document)."""
    now = datetime.now(timezone.utc)
    payload = {"typ": typ, "iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=minutes)).timestamp()), **claims}
    return jwt.encode(payload, get_settings().secret_key, algorithm="HS256")


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)
