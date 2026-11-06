"""Organization, identity and scoped-role model."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin
from app.models.types import LongText, UTCDateTime


class OrgUnit(IdMixin, TimestampMixin, Base):
    """ADA → Head Directorate / Directorate → Division / Department → Group. Master data, never enums."""

    __tablename__ = "elm_org_units"
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_org_units.id"), index=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    unit_type: Mapped[str] = mapped_column(String(40), nullable=False)  # ORGANIZATION|HEAD_DIRECTORATE|DIRECTORATE|DIVISION|DEPARTMENT|GROUP
    path: Mapped[str] = mapped_column(String(1000), index=True, default="/")  # materialized path "/<id>/<id>/"
    description: Mapped[str | None] = mapped_column(LongText)
    is_oversight: Mapped[bool] = mapped_column(Boolean, default=False)  # Head Directorate style central visibility
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(default=0)

    parent: Mapped[OrgUnit | None] = relationship(remote_side="OrgUnit.id")


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "elm_users"
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(200))
    employee_no: Mapped[str | None] = mapped_column(String(40), unique=True)
    designation: Mapped[str | None] = mapped_column(String(120))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    auth_source: Mapped[str] = mapped_column(String(20), default="local")  # local | ldap
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_system_admin: Mapped[bool] = mapped_column(Boolean, default=False)  # platform admin only, no business approvals
    primary_org_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_org_units.id"))
    failed_logins: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    preferences: Mapped[str | None] = mapped_column(LongText)  # JSON UI prefs (theme, density, pinned items)

    primary_org_unit: Mapped[OrgUnit | None] = relationship()


class UserOrgAssignment(IdMixin, TimestampMixin, Base):
    __tablename__ = "elm_user_org_assignments"
    __table_args__ = (UniqueConstraint("user_id", "org_unit_id", name="uq_user_org"),)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_users.id"), index=True)
    org_unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_org_units.id"), index=True)
    position: Mapped[str] = mapped_column(String(40), default="MEMBER")  # MEMBER | HEAD | COORDINATOR
    valid_from: Mapped[datetime | None] = mapped_column(UTCDateTime)
    valid_to: Mapped[datetime | None] = mapped_column(UTCDateTime)

    org_unit: Mapped[OrgUnit] = relationship()
    user: Mapped[User] = relationship()


class Role(IdMixin, TimestampMixin, Base):
    __tablename__ = "elm_roles"
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)  # PGD, TD, PE, ...  (labels configurable)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(LongText)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class RolePermission(IdMixin, Base):
    __tablename__ = "elm_role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission", name="uq_role_perm"),)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_roles.id"), index=True)
    permission: Mapped[str] = mapped_column(String(80), nullable=False)


class RoleAssignment(IdMixin, TimestampMixin, Base):
    """Role granted to a user within a scope: GLOBAL | ORG_UNIT | PROJECT | ENG_ITEM."""

    __tablename__ = "elm_role_assignments"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_users.id"), index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_roles.id"), index=True)
    scope_type: Mapped[str] = mapped_column(String(20), default="GLOBAL")
    scope_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    include_descendants: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[datetime | None] = mapped_column(UTCDateTime)
    valid_to: Mapped[datetime | None] = mapped_column(UTCDateTime)
    granted_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))

    role: Mapped[Role] = relationship()
    user: Mapped[User] = relationship(foreign_keys=[user_id])


class Delegation(IdMixin, TimestampMixin, Base):
    """Delegate workflow actions of `from_user` to `to_user` for a period. Original identity is preserved in decisions."""

    __tablename__ = "elm_delegations"
    from_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_users.id"), index=True)
    to_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_users.id"), index=True)
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime)
    valid_to: Mapped[datetime] = mapped_column(UTCDateTime)
    reason: Mapped[str | None] = mapped_column(LongText)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
