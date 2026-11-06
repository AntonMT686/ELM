"""Source control (architecture §12.2–12.3): GitLab repositories allow-listed per project, links from tasks to branches,
commits and merge requests, the log of operations ELM performed, and the received webhook deliveries."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow
from app.models.base import IdMixin, TimestampMixin, VersionMixin
from app.models.types import LongText, UTCDateTime


class ScmRepository(IdMixin, TimestampMixin, VersionMixin, Base):
    """A GitLab project ELM may work with. Only registered repositories are ever called (allow-list)."""

    __tablename__ = "elm_scm_repositories"
    __table_args__ = (UniqueConstraint("provider", "external_id", "project_id", name="uq_scm_repo"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_projects.id"), index=True)
    provider: Mapped[str] = mapped_column(String(20), default="gitlab")
    external_id: Mapped[str] = mapped_column(String(64))  # GitLab numeric project id
    path: Mapped[str] = mapped_column(String(300))  # path_with_namespace, e.g. product-alpha/cpu-software
    name: Mapped[str] = mapped_column(String(200))
    web_url: Mapped[str | None] = mapped_column(String(500))
    default_branch: Mapped[str] = mapped_column(String(200), default="main")
    branch_prefix: Mapped[str] = mapped_column(String(60), default="task/")
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_engineering_items.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    last_event_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ScmLink(IdMixin, TimestampMixin, Base):
    """Traceability from a task to a branch, commit or merge request (architecture §12.3: every push/MR links back)."""

    __tablename__ = "elm_scm_links"
    __table_args__ = (UniqueConstraint("work_item_id", "repository_id", "kind", "ref", name="uq_scm_link"),)
    work_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_work_items.id"), index=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_scm_repositories.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # BRANCH | COMMIT | MERGE_REQUEST
    ref: Mapped[str] = mapped_column(String(255))  # branch name, commit SHA or MR iid
    title: Mapped[str | None] = mapped_column(String(500))
    url: Mapped[str | None] = mapped_column(String(500))
    state: Mapped[str | None] = mapped_column(String(30))  # MR: opened | merged | closed | locked; branch: active | deleted
    source_branch: Mapped[str | None] = mapped_column(String(255))
    target_branch: Mapped[str | None] = mapped_column(String(255))
    author: Mapped[str | None] = mapped_column(String(200))
    origin: Mapped[str] = mapped_column(String(20), default="ELM")  # ELM | WEBHOOK | MANUAL | SYNC
    external_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # when it happened in GitLab
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))


class ScmOperation(IdMixin, Base):
    """Every call ELM makes to GitLab on someone's behalf, with its outcome (the 'operation state' of §12.2)."""

    __tablename__ = "elm_scm_operations"
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    repository_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_scm_repositories.id"), index=True)
    work_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_work_items.id"), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    operation: Mapped[str] = mapped_column(String(40))  # create_branch | create_merge_request | sync | lookup
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")  # RUNNING | SUCCEEDED | FAILED
    request: Mapped[str | None] = mapped_column(LongText)  # JSON (never contains the token)
    result: Mapped[str | None] = mapped_column(LongText)  # JSON summary
    error: Mapped[str | None] = mapped_column(String(1000))


class ScmWebhookEvent(IdMixin, Base):
    """Received GitLab webhook deliveries. The delivery UUID makes re-deliveries idempotent."""

    __tablename__ = "elm_scm_webhook_events"
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    delivery_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    event: Mapped[str] = mapped_column(String(60))
    repository_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_scm_repositories.id"), index=True)
    external_project_id: Mapped[str | None] = mapped_column(String(64))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="RECEIVED")  # PROCESSED | IGNORED | FAILED
    links_created: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(String(1000))
