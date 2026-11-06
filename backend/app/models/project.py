"""Programme/project, configurable product breakdown (Product → System → Subsystem → Unit → ...), work items."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin, VersionMixin
from app.models.types import LongText, UTCDateTime


class ProcessDomain(IdMixin, TimestampMixin, Base):
    """SOFTWARE | HARDWARE | SYSTEMS | HYBRID | ADMIN | QUALITY ... configurable."""

    __tablename__ = "elm_process_domains"
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    is_engineering: Mapped[bool] = mapped_column(Boolean, default=True)
    color: Mapped[str | None] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Project(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "elm_projects"
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    programme: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(LongText)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")  # PLANNED|ACTIVE|ON_HOLD|CLOSED
    lead_org_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_org_units.id"))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    color: Mapped[str | None] = mapped_column(String(20))
    classification: Mapped[str | None] = mapped_column(String(40))

    levels: Mapped[list[HierarchyLevel]] = relationship(order_by="HierarchyLevel.level_no", cascade="all, delete-orphan")


class ProjectOrgAssignment(IdMixin, TimestampMixin, Base):
    __tablename__ = "elm_project_org_assignments"
    __table_args__ = (UniqueConstraint("project_id", "org_unit_id", name="uq_project_org"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_projects.id"), index=True)
    org_unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_org_units.id"), index=True)
    participation: Mapped[str] = mapped_column(String(20), default="CONTRIBUTOR")  # LEAD | CONTRIBUTOR | OVERSIGHT


class ProjectMember(IdMixin, TimestampMixin, Base):
    __tablename__ = "elm_project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_projects.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_users.id"), index=True)


class HierarchyLevel(IdMixin, Base):
    """Configurable breakdown levels per project. e.g. 1 PRODUCT, 2 SYSTEM, 3 SUBSYSTEM, 4 UNIT, 5 MODULE/COMPONENT."""

    __tablename__ = "elm_hierarchy_levels"
    __table_args__ = (UniqueConstraint("project_id", "level_no", name="uq_level_no"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_projects.id"), index=True)
    level_no: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(80))
    icon: Mapped[str | None] = mapped_column(String(40))
    color: Mapped[str | None] = mapped_column(String(20))


class EngineeringItem(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "elm_engineering_items"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_item_code"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_projects.id"), index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_engineering_items.id"), index=True)
    level_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_hierarchy_levels.id"))
    code: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(200))
    part_number: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(LongText)
    domain_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_process_domains.id"))
    lead_org_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_org_units.id"))
    technical_owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    lifecycle_phase: Mapped[str] = mapped_column(String(40), default="CONCEPT")  # configurable phase label
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    path: Mapped[str] = mapped_column(String(2000), index=True, default="/")
    sort_order: Mapped[int] = mapped_column(default=0)

    level: Mapped[HierarchyLevel] = relationship()


class EngineeringItemOrg(IdMixin, Base):
    __tablename__ = "elm_engineering_item_orgs"
    __table_args__ = (UniqueConstraint("item_id", "org_unit_id", name="uq_item_org"),)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_engineering_items.id"), index=True)
    org_unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_org_units.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="CONTRIBUTOR")  # LEAD | CONTRIBUTOR | REVIEWER


class WorkItem(IdMixin, TimestampMixin, VersionMixin, Base):
    """Task / action item — engineering or non-engineering (admin, procurement, quality, meetings ...)."""

    __tablename__ = "elm_work_items"
    key: Mapped[str] = mapped_column(String(40), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(LongText)
    kind: Mapped[str] = mapped_column(String(30), default="TASK")  # TASK | ACTION | MILESTONE | CHANGE_REQUEST | ISSUE
    status: Mapped[str] = mapped_column(String(30), default="OPEN")  # lifecycle state code; see services/task_lifecycle.py
    priority: Mapped[str] = mapped_column(String(10), default="MEDIUM")
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_projects.id"), index=True)
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_engineering_items.id"), index=True)
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_org_units.id"), index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_documents.id"), index=True)
    domain_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_process_domains.id"))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"), index=True)
    reporter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    start_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # server-calculated; see services/task_lifecycle.py
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # planning (architecture §9). Foreign keys to planning tables are by name: models/planning.py imports this module's Base.
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_project_plans.id"), index=True)
    work_package_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_work_packages.id"), index=True)
    activity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_plan_activities.id"), index=True)
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_milestones.id"), index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_work_items.id"), index=True)
    reported_progress: Mapped[float] = mapped_column(Float, default=0.0)  # assignee's estimate, capped by state when progress is calculated
    estimated_hours: Mapped[float] = mapped_column(Float, default=0.0)
    actual_hours: Mapped[float] = mapped_column(Float, default=0.0)
    weight: Mapped[float | None] = mapped_column(Float)  # NULL = weigh by estimated hours
    actual_start: Mapped[date | None] = mapped_column(Date)
    actual_end: Mapped[date | None] = mapped_column(Date)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    legacy_key: Mapped[str | None] = mapped_column(String(80))  # key in the source system; not unique there
    legacy_type: Mapped[str | None] = mapped_column(String(60))
