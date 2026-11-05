from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import utcnow


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class VersionMixin:
    """Application-managed optimistic concurrency (portable to SQL Server)."""

    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
