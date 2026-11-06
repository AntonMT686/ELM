"""Design and engineering artefacts (architecture §11): configurable artefact types, design records with immutable
versions (diagram source + preview, uploaded file or external link), review, approval and baseline."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin, VersionMixin
from app.models.types import LongText, UTCDateTime


class DesignType(IdMixin, TimestampMixin, Base):
    """Configurable artefact type: architecture, sequence, ER, interface, drawing, calculation, analysis ... (ADA supplies the list)."""

    __tablename__ = "elm_design_types"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    category: Mapped[str] = mapped_column(String(20), default="SOFTWARE")  # SOFTWARE | ENGINEERING | SYSTEMS | OTHER
    description: Mapped[str | None] = mapped_column(LongText)
    allowed_extensions: Mapped[str] = mapped_column(String(200), default="drawio,svg,png,jpg,pdf")
    diagram_editor: Mapped[bool] = mapped_column(Boolean, default=True)  # offer the embedded draw.io editor
    fields: Mapped[str | None] = mapped_column(LongText)  # JSON list of configurable widgets: [{key, label, type, required, options}]
    color: Mapped[str | None] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class DesignRecord(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "elm_design_records"
    __table_args__ = (UniqueConstraint("key", name="uq_design_key"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_projects.id"), index=True)
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_engineering_items.id"), index=True)
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_org_units.id"))
    type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_design_types.id"))
    key: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(LongText)
    attributes: Mapped[str | None] = mapped_column(LongText)  # JSON values of the type's configurable fields
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)  # §11.1 lifecycle
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"), index=True)
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    baselined_version: Mapped[int | None] = mapped_column(Integer)
    baseline_sha256: Mapped[str | None] = mapped_column(String(64))
    baselined_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    baselined_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))


class DesignVersion(IdMixin, Base):
    """Immutable. A restore makes a new version that copies an older one; nothing is ever overwritten."""

    __tablename__ = "elm_design_versions"
    __table_args__ = (UniqueConstraint("design_id", "version_no", name="uq_design_version"),)
    design_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_design_records.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))  # DIAGRAM (draw.io XML) | FILE | LINK
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_file_objects.id"))  # .drawio XML or uploaded file
    preview_file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_file_objects.id"))  # SVG / PNG preview
    external_url: Mapped[str | None] = mapped_column(String(1000))
    content_sha256: Mapped[str] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(String(1000))
    restored_from: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
