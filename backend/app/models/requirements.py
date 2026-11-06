"""Requirement management (architecture §10): sources, requirements with revisions, reviews bound to a content hash,
links, traceability to tasks and documents, and immutable baselines. Typed tables, no polymorphic (type, id) references."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow
from app.models.base import IdMixin, TimestampMixin, VersionMixin
from app.models.types import LongText, UTCDateTime


class RequirementSource(IdMixin, TimestampMixin, Base):
    """Where requirements came from: a BRD, SRS, a tool export. Keeps provenance per architecture §10.2 and §14.1."""

    __tablename__ = "elm_requirement_sources"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_req_source_name"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    source_system: Mapped[str] = mapped_column(String(40), default="ELM")  # ELM | PMS | DOORS | ... free text, not an enum
    external_ref: Mapped[str | None] = mapped_column(String(300))
    external_version: Mapped[str | None] = mapped_column(String(80))
    key_prefix: Mapped[str] = mapped_column(String(40))  # requirement IDs are <prefix>-0001
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_documents.id"))
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_org_units.id"))
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))


class Requirement(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "elm_requirements"
    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_req_key"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_projects.id"), index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_requirement_sources.id"), index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_requirements.id"), index=True)
    key: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(LongText)
    acceptance_criteria: Mapped[str | None] = mapped_column(LongText)
    req_type: Mapped[str] = mapped_column(String(40), default="FUNCTIONAL")  # configurable label
    priority: Mapped[str] = mapped_column(String(10), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)  # content revision; `version` is the optimistic lock
    content_sha256: Mapped[str] = mapped_column(String(64))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"), index=True)
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_org_units.id"), index=True)
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_engineering_items.id"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(200), index=True)
    external_version: Mapped[str | None] = mapped_column(String(80))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class RequirementRevision(IdMixin, Base):
    """Content of each revision. Rows of a revision that left draft are never changed."""

    __tablename__ = "elm_requirement_revisions"
    __table_args__ = (UniqueConstraint("requirement_id", "revision", name="uq_req_revision"),)
    requirement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_requirements.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(LongText)
    acceptance_criteria: Mapped[str | None] = mapped_column(LongText)
    req_type: Mapped[str] = mapped_column(String(40))
    priority: Mapped[str] = mapped_column(String(10))
    content_sha256: Mapped[str] = mapped_column(String(64))
    change_reason: Mapped[str | None] = mapped_column(LongText)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RequirementReview(IdMixin, Base):
    """One person's decision on one exact revision and hash. A new review cycle adds rows; decisions are never rewritten."""

    __tablename__ = "elm_requirement_reviews"
    requirement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_requirements.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64))
    cycle: Mapped[int] = mapped_column(Integer, default=1)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="REVIEWER")  # REVIEWER | APPROVER
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)  # PENDING | APPROVED | REJECTED | CANCELLED
    comment: Mapped[str | None] = mapped_column(LongText)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class RequirementLink(IdMixin, Base):
    """from → to, read as "from <type> to": A depends_on B, A derived_from B, A implements B, A conflicts_with B, A related_to B."""

    __tablename__ = "elm_requirement_links"
    __table_args__ = (UniqueConstraint("from_id", "to_id", "link_type", name="uq_req_link"),)
    from_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_requirements.id"), index=True)
    to_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_requirements.id"), index=True)
    link_type: Mapped[str] = mapped_column(String(30))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RequirementWorkItem(IdMixin, Base):
    __tablename__ = "elm_requirement_work_items"
    __table_args__ = (UniqueConstraint("requirement_id", "work_item_id", name="uq_req_task"),)
    requirement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_requirements.id"), index=True)
    work_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_work_items.id"), index=True)
    link_type: Mapped[str] = mapped_column(String(30), default="implements")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RequirementDocument(IdMixin, Base):
    __tablename__ = "elm_requirement_documents"
    __table_args__ = (UniqueConstraint("requirement_id", "document_id", name="uq_req_doc"),)
    requirement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_requirements.id"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_documents.id"), index=True)
    link_type: Mapped[str] = mapped_column(String(30), default="specified_in")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RequirementEvent(IdMixin, Base):
    __tablename__ = "elm_requirement_events"
    requirement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_requirements.id"), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    kind: Mapped[str] = mapped_column(String(30))  # CREATED | STATUS | REVISION | DECISION | BASELINED | IMPORTED | LEGACY_STATE
    from_value: Mapped[str | None] = mapped_column(String(100))
    to_value: Mapped[str | None] = mapped_column(String(100))
    comment: Mapped[str | None] = mapped_column(LongText)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class RequirementBaseline(IdMixin, Base):
    """Immutable snapshot of selected requirements. Re-baselining adds a new row with the next seq."""

    __tablename__ = "elm_requirement_baselines"
    __table_args__ = (UniqueConstraint("project_id", "seq", name="uq_req_baseline_seq"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_projects.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(300))
    reason: Mapped[str] = mapped_column(LongText)
    sha256: Mapped[str] = mapped_column(String(64))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RequirementBaselineItem(IdMixin, Base):
    __tablename__ = "elm_requirement_baseline_items"
    __table_args__ = (UniqueConstraint("baseline_id", "key", "revision", name="uq_req_baseline_item"),)
    baseline_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_requirement_baselines.id"), index=True)
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_requirements.id"), index=True)
    key: Mapped[str] = mapped_column(String(100))
    revision: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(LongText)
    acceptance_criteria: Mapped[str | None] = mapped_column(LongText)
    req_type: Mapped[str] = mapped_column(String(40))
    priority: Mapped[str] = mapped_column(String(10))
    content_sha256: Mapped[str] = mapped_column(String(64))
