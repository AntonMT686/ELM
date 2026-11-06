"""Shared records for engineering artefacts that are not documents (design records, test cases, test plans, defects):
hash-bound reviews, traceability links and history. One mechanism, so review rules and traceability behave the same
for every artefact type (architecture §11, §13, §19)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow
from app.models.base import IdMixin, TimestampMixin
from app.models.types import LongText, UTCDateTime

# artifact_type values: DESIGN | TEST_CASE | TEST_PLAN | DEFECT | REQUIREMENT | DOCUMENT | TASK


class ArtifactReview(IdMixin, TimestampMixin, Base):
    """One reviewer's decision on one revision of an artefact. Bound to the revision number and its SHA-256."""

    __tablename__ = "elm_artifact_reviews"
    artifact_type: Mapped[str] = mapped_column(String(20), index=True)
    artifact_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64))
    cycle: Mapped[int] = mapped_column(Integer, default=1)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # REVIEWER | APPROVER
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING | APPROVED | CHANGES_REQUESTED | SUPERSEDED
    comment: Mapped[str | None] = mapped_column(LongText)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    submitted_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))


class ArtifactLink(IdMixin, Base):
    """Traceability between artefacts, e.g. DESIGN → REQUIREMENT (satisfies), TEST_CASE → REQUIREMENT (verifies)."""

    __tablename__ = "elm_artifact_links"
    __table_args__ = (UniqueConstraint("from_type", "from_id", "to_type", "to_id", "link_type", name="uq_artifact_link"),)
    from_type: Mapped[str] = mapped_column(String(20))
    from_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    to_type: Mapped[str] = mapped_column(String(20))
    to_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    link_type: Mapped[str] = mapped_column(String(30))  # satisfies | verifies | implements | describes | related_to | found_by
    section: Mapped[str | None] = mapped_column(String(200))  # document section / heading mapped to a design record
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))


class ArtifactEvent(IdMixin, Base):
    """Append-only history of an artefact (status changes, versions, decisions, restores)."""

    __tablename__ = "elm_artifact_events"
    artifact_type: Mapped[str] = mapped_column(String(20), index=True)
    artifact_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    kind: Mapped[str] = mapped_column(String(30))  # CREATED | STATUS | VERSION | REVIEW | DECISION | RESTORE | LINK | EXECUTION ...
    from_value: Mapped[str | None] = mapped_column(String(120))
    to_value: Mapped[str | None] = mapped_column(String(120))
    comment: Mapped[str | None] = mapped_column(LongText)
