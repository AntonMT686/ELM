from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Integer, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import utcnow
from app.models.types import UTCDateTime


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class VersionMixin:
    """Application-managed optimistic concurrency (portable to SQL Server)."""

    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
