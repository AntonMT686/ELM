"""Programme / project planning (architecture §9): plans, phases, milestones, work packages, activities, task detail
records (dependencies, participants, checklist, deliverables, comments, history), plan baselines, legacy-import bookkeeping.

`WorkItem` (models/project.py) remains the task entity, so engineering and non-engineering tasks share one lifecycle."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow
from app.models.base import IdMixin, TimestampMixin, VersionMixin


class PlanPhase(IdMixin, TimestampMixin, Base):
    """Configurable phase. project_id NULL = shared template; a project with its own rows uses only those,
    so hardware and other domains are never forced onto SDLC labels (architecture §17.1)."""

    __tablename__ = "plan_phases"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_phase_code"),)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    weight: Mapped[float] = mapped_column(Float, default=1.0)  # share of project progress (architecture §17.3)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProjectPlan(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "project_plans"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    version_label: Mapped[str] = mapped_column(String(20), default="1.0")
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")  # DRAFT | ACTIVE | ARCHIVED
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Milestone(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "milestones"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("project_plans.id"), index=True)
    code: Mapped[str | None] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    achieved_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="PLANNED")  # PLANNED | IN_PROGRESS | ACHIEVED | CANCELLED
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("org_units.id"))
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("engineering_items.id"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class WorkPackage(IdMixin, TimestampMixin, VersionMixin, Base):
    """Cross-directorate unit of planned work: lead directorate plus contributors, domain and engineering item."""

    __tablename__ = "work_packages"
    __table_args__ = (UniqueConstraint("plan_id", "code", name="uq_wp_code"),)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project_plans.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    domain_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("process_domains.id"))
    lead_org_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("org_units.id"), index=True)
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("engineering_items.id"), index=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # ACTIVE | ON_HOLD | CLOSED
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class WorkPackageOrg(IdMixin, Base):
    __tablename__ = "work_package_orgs"
    __table_args__ = (UniqueConstraint("work_package_id", "org_unit_id", name="uq_wp_org"),)
    work_package_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_packages.id"), index=True)
    org_unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("org_units.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="CONTRIBUTOR")


class PlanActivity(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "plan_activities"
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project_plans.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    work_package_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work_packages.id"), index=True)
    phase_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plan_phases.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    estimated_hours: Mapped[float] = mapped_column(Float, default=0.0)
    priority: Mapped[str] = mapped_column(String(10), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(20), default="NOT_STARTED")  # NOT_STARTED | IN_PROGRESS | COMPLETED | ON_HOLD | CANCELLED
    weight: Mapped[float | None] = mapped_column(Float)  # NULL = weigh by estimated hours
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class TaskDependency(IdMixin, Base):
    """successor depends on predecessor. dep_type FS | SS | FF | SF, lag in calendar days."""

    __tablename__ = "task_dependencies"
    __table_args__ = (UniqueConstraint("successor_id", "predecessor_id", name="uq_task_dep"),)
    successor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_items.id"), index=True)
    predecessor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_items.id"), index=True)
    dep_type: Mapped[str] = mapped_column(String(2), default="FS")
    lag_days: Mapped[int] = mapped_column(Integer, default=0)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TaskParticipant(IdMixin, Base):
    """One owner lives on WorkItem.assignee_id; contributors and reviewers live here (architecture §9.4)."""

    __tablename__ = "task_participants"
    __table_args__ = (UniqueConstraint("work_item_id", "user_id", "role", name="uq_task_participant"),)
    work_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_items.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="CONTRIBUTOR")  # CONTRIBUTOR | REVIEWER


class TaskChecklistItem(IdMixin, TimestampMixin, Base):
    __tablename__ = "task_checklist_items"
    work_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_items.id"), index=True)
    text: Mapped[str] = mapped_column(String(500))
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    done_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class TaskDeliverable(IdMixin, TimestampMixin, Base):
    """Controlled document a task must produce. The completion gate reads the document's real status."""

    __tablename__ = "task_deliverables"
    __table_args__ = (UniqueConstraint("work_item_id", "document_id", name="uq_task_deliverable"),)
    work_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_items.id"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    required_status: Mapped[str] = mapped_column(String(20), default="RELEASED")  # APPROVED | RELEASED
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class TaskComment(IdMixin, Base):
    """Append-only. created_at is kept from the source system for migrated comments."""

    __tablename__ = "task_comments"
    work_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_items.id"), index=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class WorkItemEvent(IdMixin, Base):
    """Readable task history: status transitions and assignment changes (the hash-chained audit trail stays authoritative)."""

    __tablename__ = "work_item_events"
    work_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_items.id"), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(30))  # CREATED | STATUS | ASSIGNED | LEGACY_STATE
    from_value: Mapped[str | None] = mapped_column(String(100))
    to_value: Mapped[str | None] = mapped_column(String(100))
    comment: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class PlanBaseline(IdMixin, Base):
    """Immutable, SHA-256 sealed snapshot of a plan. Re-baselining adds a row; nothing is overwritten."""

    __tablename__ = "plan_baselines"
    __table_args__ = (UniqueConstraint("plan_id", "seq", name="uq_plan_baseline_seq"),)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project_plans.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(Text)
    snapshot: Mapped[str] = mapped_column(Text)  # canonical JSON
    sha256: Mapped[str] = mapped_column(String(64))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LegacyImportRun(IdMixin, Base):
    __tablename__ = "legacy_import_runs"
    source_system: Mapped[str] = mapped_column(String(40))
    source_database: Mapped[str | None] = mapped_column(String(120))
    bundle_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="COMMITTED")  # COMMITTED | ROLLED_BACK
    report: Mapped[str | None] = mapped_column(Text)  # JSON reconciliation report
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LegacyImportMap(IdMixin, Base):
    """Source row → target row. Makes re-runs idempotent, and is what rollback and reconciliation work from."""

    __tablename__ = "legacy_import_map"
    __table_args__ = (UniqueConstraint("source_system", "source_table", "source_id", name="uq_legacy_source"),)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("legacy_import_runs.id"), index=True)
    source_system: Mapped[str] = mapped_column(String(40))
    source_table: Mapped[str] = mapped_column(String(80))
    source_id: Mapped[str] = mapped_column(String(80))
    target_table: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[uuid.UUID] = mapped_column()
    created: Mapped[bool] = mapped_column(Boolean, default=True)  # False = matched an existing row; rollback leaves it alone


class LegacyAuditRecord(IdMixin, Base):
    """Legacy audit history, preserved read-only and apart from the hash chain so that chain's time order stays true."""

    __tablename__ = "legacy_audit_records"
    __table_args__ = (UniqueConstraint("source_system", "source_table", "source_id", name="uq_legacy_audit"),)
    source_system: Mapped[str] = mapped_column(String(40))
    source_table: Mapped[str] = mapped_column(String(80))
    source_id: Mapped[str] = mapped_column(String(80))
    at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    username: Mapped[str | None] = mapped_column(String(250))
    action: Mapped[str | None] = mapped_column(String(100))
    entity_type: Mapped[str | None] = mapped_column(String(100))
    entity_id: Mapped[str | None] = mapped_column(String(100))
    details: Mapped[str | None] = mapped_column(Text)
