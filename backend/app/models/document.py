"""Controlled document management: types, documents, revisions, iterations, files, relations, grants, comments."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin, VersionMixin
from app.models.types import LongText, UTCDateTime


class FileObject(IdMixin, TimestampMixin, Base):
    """Binary stored outside the DB (filesystem / object store). DB keeps key + hash only."""

    __tablename__ = "elm_file_objects"
    storage_key: Mapped[str] = mapped_column(String(300), unique=True)
    original_name: Mapped[str] = mapped_column(String(300))
    mime_type: Mapped[str] = mapped_column(String(150))
    extension: Mapped[str] = mapped_column(String(20))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    scan_status: Mapped[str] = mapped_column(String(20), default="NOT_SCANNED")  # NOT_SCANNED|CLEAN|QUARANTINED


class DocumentType(IdMixin, TimestampMixin, Base):
    __tablename__ = "elm_document_types"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    category: Mapped[str] = mapped_column(String(30), default="ENGINEERING")  # ENGINEERING | MANAGEMENT | NON_ENGINEERING
    description: Mapped[str | None] = mapped_column(LongText)
    numbering_pattern: Mapped[str] = mapped_column(String(200), default="{PROJECT}-{TYPE}-{SEQ:4}")
    revision_scheme: Mapped[str] = mapped_column(String(20), default="ALPHA")  # ALPHA (A,B,C) | NUMERIC (01,02)
    allowed_extensions: Mapped[str] = mapped_column(String(300), default="docx,xlsx,pptx,pdf")
    default_template: Mapped[str | None] = mapped_column(String(20))  # docx | xlsx | pptx
    requires_signature: Mapped[bool] = mapped_column(Boolean, default=True)
    applicable_levels: Mapped[str | None] = mapped_column(String(300))  # comma list of level codes; empty = any
    icon: Mapped[str | None] = mapped_column(String(40))
    color: Mapped[str | None] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class NumberSequence(IdMixin, Base):
    __tablename__ = "elm_number_sequences"
    key: Mapped[str] = mapped_column(String(200), unique=True)
    next_value: Mapped[int] = mapped_column(Integer, default=1)


class Document(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "elm_documents"
    number: Mapped[str] = mapped_column(String(120), unique=True)
    title: Mapped[str] = mapped_column(String(400))
    description: Mapped[str | None] = mapped_column(LongText)
    type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_document_types.id"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_projects.id"), index=True)
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_engineering_items.id"), index=True)
    domain_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_process_domains.id"))
    owner_org_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_org_units.id"), index=True)
    originating_org_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_org_units.id"))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_users.id"), index=True)
    classification: Mapped[str] = mapped_column(String(40), default="RESTRICTED")  # labels configurable (TBD by ADA)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    # Document lifecycle: DRAFT | IN_REVIEW | CHANGES_REQUESTED | APPROVED | RELEASED | SUPERSEDED | WITHDRAWN | OBSOLETE
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_document_revisions.id", use_alter=True, name="fk_elm_documents_current_revision"))
    released_revision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_document_revisions.id", use_alter=True, name="fk_elm_documents_released_revision"))
    keywords: Mapped[str | None] = mapped_column(String(500))
    due_date: Mapped[datetime | None] = mapped_column(UTCDateTime)
    external_ref: Mapped[str | None] = mapped_column(String(200))
    legacy_ref: Mapped[str | None] = mapped_column(String(100))  # ProFlow source id for migration reconciliation

    doc_type: Mapped[DocumentType] = relationship()


class DocumentRevision(IdMixin, TimestampMixin, Base):
    """A revision (A, B, C ...). Work-in-progress saves are iterations; reviews bind to iteration + SHA-256."""

    __tablename__ = "elm_document_revisions"
    __table_args__ = (UniqueConstraint("document_id", "revision_no", name="uq_doc_rev"),)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_documents.id"), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(20))
    iteration: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    # DRAFT | IN_REVIEW | CHANGES_REQUESTED | APPROVED | RELEASED | SUPERSEDED | WITHDRAWN | CANCELLED
    file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_file_objects.id"))
    sha256: Mapped[str | None] = mapped_column(String(64))
    change_summary: Mapped[str | None] = mapped_column(LongText)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_users.id"))
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    released_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    derived_from_revision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_document_revisions.id"))

    file: Mapped[FileObject | None] = relationship(foreign_keys=[file_id])


class RevisionIteration(IdMixin, TimestampMixin, Base):
    """Every save of a draft revision is kept (no silent overwrite)."""

    __tablename__ = "elm_revision_iterations"
    __table_args__ = (UniqueConstraint("revision_id", "iteration", name="uq_rev_iter"),)
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_document_revisions.id"), index=True)
    iteration: Mapped[int] = mapped_column(Integer)
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_file_objects.id"))
    sha256: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(20), default="UPLOAD")  # UPLOAD | ONLYOFFICE | TEMPLATE | COPY | MIGRATION
    note: Mapped[str | None] = mapped_column(LongText)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))

    file: Mapped[FileObject] = relationship()


class DocumentRelation(IdMixin, TimestampMixin, Base):
    __tablename__ = "elm_document_relations"
    __table_args__ = (UniqueConstraint("source_id", "target_id", "relation_type", name="uq_doc_rel"),)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_documents.id"), index=True)  # parent / referencing
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_documents.id"), index=True)  # child / referenced
    relation_type: Mapped[str] = mapped_column(String(30))  # PARENT_OF | DERIVED_FROM | REFERENCES | SUPERSEDES | RELATED
    source_revision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_document_revisions.id"))
    note: Mapped[str | None] = mapped_column(LongText)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))


class DocumentAccessGrant(IdMixin, TimestampMixin, Base):
    """Explicit sharing. Exactly one of user_id / org_unit_id / role_id is set."""

    __tablename__ = "elm_document_access_grants"
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_documents.id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"), index=True)
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_org_units.id"), index=True)
    permissions: Mapped[str] = mapped_column(String(200), default="view")  # comma list: view,download,comment,edit
    valid_to: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reason: Mapped[str | None] = mapped_column(LongText)
    granted_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class DocumentComment(IdMixin, TimestampMixin, Base):
    __tablename__ = "elm_document_comments"
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_documents.id"), index=True)
    revision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_document_revisions.id"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_document_comments.id"))
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_users.id"))
    body: Mapped[str] = mapped_column(LongText)
    anchor: Mapped[str | None] = mapped_column(String(200))  # page/section/requirement anchor
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))


class DocumentAccessLog(IdMixin, Base):
    __tablename__ = "elm_document_access_logs"
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_documents.id"), index=True)
    revision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_document_revisions.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    action: Mapped[str] = mapped_column(String(20))  # VIEW | DOWNLOAD | EDIT_SESSION
    at: Mapped[datetime] = mapped_column(UTCDateTime)
