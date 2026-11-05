"""Configurable, versioned workflow engine model + signatures + releases."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin


class WorkflowDefinition(IdMixin, TimestampMixin, Base):
    __tablename__ = "workflow_definitions"
    code: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30), default="DOCUMENT")  # DOCUMENT | WORK_ITEM | CHANGE
    draft_spec: Mapped[str | None] = mapped_column(Text)  # JSON of editable draft (validated on save/publish)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class WorkflowVersion(IdMixin, TimestampMixin, Base):
    """Immutable once published. Instances stay pinned to the version they started with."""

    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("definition_id", "version_no", name="uq_wf_ver"),)
    definition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_definitions.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    spec: Mapped[str] = mapped_column(Text)  # validated JSON spec
    spec_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="PUBLISHED")  # PUBLISHED | RETIRED
    published_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    definition: Mapped[WorkflowDefinition] = relationship()


class WorkflowBinding(IdMixin, TimestampMixin, Base):
    """Most specific matching binding wins (score = number of non-null criteria, then priority)."""

    __tablename__ = "workflow_bindings"
    definition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_definitions.id"), index=True)
    document_type_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_types.id"))
    domain_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("process_domains.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("org_units.id"))
    level_code: Mapped[str | None] = mapped_column(String(30))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class WorkflowInstance(IdMixin, TimestampMixin, Base):
    __tablename__ = "workflow_instances"
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_versions.id"), index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"), index=True)
    revision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_revisions.id"), index=True)
    iteration: Mapped[int | None] = mapped_column(Integer)
    revision_sha256: Mapped[str | None] = mapped_column(String(64))
    cycle_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # ACTIVE | COMPLETED | CHANGES_REQUESTED | REJECTED | CANCELLED
    current_stage_key: Mapped[str | None] = mapped_column(String(60))
    initiator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    planned_assignees: Mapped[str | None] = mapped_column(Text)  # JSON {stage_key: [user_id]}
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    version: Mapped[WorkflowVersion] = relationship()


class WorkflowStageRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "workflow_stage_runs"
    instance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_instances.id"), index=True)
    stage_key: Mapped[str] = mapped_column(String(60))
    stage_name: Mapped[str] = mapped_column(String(120))
    stage_type: Mapped[str] = mapped_column(String(20))
    seq: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # ACTIVE | DONE | SKIPPED | RETURNED | REJECTED | CANCELLED
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowTask(IdMixin, TimestampMixin, Base):
    """An assignment to a person, bound to the exact revision iteration + hash under review."""

    __tablename__ = "workflow_tasks"
    instance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_instances.id"), index=True)
    stage_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_stage_runs.id"), index=True)
    stage_key: Mapped[str] = mapped_column(String(60))
    assignee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    # PENDING | APPROVED | CHANGES_REQUESTED | REJECTED | SIGNED | CANCELLED | REASSIGNED
    decision_comment: Mapped[str | None] = mapped_column(Text)
    checklist_result: Mapped[str | None] = mapped_column(Text)  # JSON
    acted_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))  # differs when delegate acted
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_revisions.id"))
    revision_sha256: Mapped[str | None] = mapped_column(String(64))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SignatureRecord(IdMixin, TimestampMixin, Base):
    __tablename__ = "signature_records"
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_revisions.id"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_tasks.id"))
    signer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    signer_role: Mapped[str | None] = mapped_column(String(120))  # "Prepared By", "Approved By" ...
    provider: Mapped[str] = mapped_column(String(40))
    algorithm: Mapped[str] = mapped_column(String(40))
    signed_sha256: Mapped[str] = mapped_column(String(64))
    signature_b64: Mapped[str] = mapped_column(Text)
    certificate_pem: Mapped[str] = mapped_column(Text)
    certificate_subject: Mapped[str] = mapped_column(String(300))
    certificate_serial: Mapped[str] = mapped_column(String(80))
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="VALID")  # VALID | INVALID | REVOKED
    is_cryptographic: Mapped[bool] = mapped_column(Boolean, default=True)


class ReleasePackage(IdMixin, TimestampMixin, Base):
    __tablename__ = "release_packages"
    code: Mapped[str] = mapped_column(String(60), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("engineering_items.id"))
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")  # DRAFT | RELEASED | WITHDRAWN
    release_note: Mapped[str | None] = mapped_column(Text)
    released_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manifest_json: Mapped[str | None] = mapped_column(Text)
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    withdrawn_reason: Mapped[str | None] = mapped_column(Text)


class ReleasePackageItem(IdMixin, Base):
    __tablename__ = "release_package_items"
    __table_args__ = (UniqueConstraint("package_id", "revision_id", name="uq_pkg_rev"),)
    package_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("release_packages.id"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_revisions.id"))


class ReleaseRegisterEntry(IdMixin, TimestampMixin, Base):
    """Central Release Register: one row per formally released revision. Never hard-deleted."""

    __tablename__ = "release_register"
    release_no: Mapped[str] = mapped_column(String(60), unique=True)
    package_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("release_packages.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_revisions.id"), unique=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("engineering_items.id"), index=True)
    owner_org_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("org_units.id"), index=True)
    sha256: Mapped[str] = mapped_column(String(64))
    signature_count: Mapped[int] = mapped_column(Integer, default=0)
    released_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="RELEASED")  # RELEASED | SUPERSEDED | WITHDRAWN
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("release_register.id"))
    status_reason: Mapped[str | None] = mapped_column(Text)
