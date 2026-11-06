"""Software deployment and release to environments (architecture §14). Distinct from the document Release Register (§7).

* DeploymentEnvironment: per-project target (e.g. INT, UAT, PROD) with its approval rules, validation gates, execution
  adapter and health check. Its configuration is itself approved; any edit makes it a draft again.
* Deployment: one request to put a version (tag / commit) on an environment. A rollback is a new Deployment that points
  at the one it reverses; the original record is never rewritten (only its status becomes ROLLED_BACK).
* DeploymentAttempt: one execution of a deployment. A retry is a new attempt; attempts are never edited afterwards."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin, VersionMixin
from app.models.types import LongText, UTCDateTime


class DeploymentEnvironment(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "elm_deploy_environments"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_deploy_env_code"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_projects.id"), index=True)
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(LongText)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # The rules below form the "configuration". Its SHA-256 is what gets approved.
    config: Mapped[str] = mapped_column(LongText)  # JSON, see services/deployment.py DEFAULT_CONFIG
    config_sha256: Mapped[str] = mapped_column(String(64))
    config_status: Mapped[str] = mapped_column(String(20), default="DRAFT")  # DRAFT | APPROVED
    config_approved_sha256: Mapped[str | None] = mapped_column(String(64))
    config_approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    config_approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    config_changed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))


class Deployment(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "elm_deployments"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_projects.id"), index=True)
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_deploy_environments.id"), index=True)
    key: Mapped[str] = mapped_column(String(60), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    version_label: Mapped[str] = mapped_column(String(120))
    repository_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_scm_repositories.id"))
    git_ref: Mapped[str | None] = mapped_column(String(255))  # tag or branch name
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    release_notes: Mapped[str | None] = mapped_column(LongText)
    test_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_test_runs.id"))
    checklist: Mapped[str | None] = mapped_column(LongText)  # JSON {item text: true/false}
    status: Mapped[str] = mapped_column(String(20), default="PLANNED", index=True)  # §14.1 lifecycle
    content_sha256: Mapped[str] = mapped_column(String(64))  # binds approvals to environment + version + commit + notes
    rollback_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_deployments.id"))
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    deployed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status_reason: Mapped[str | None] = mapped_column(String(1000))


class DeploymentAttempt(IdMixin, Base):
    __tablename__ = "elm_deployment_attempts"
    __table_args__ = (UniqueConstraint("deployment_id", "attempt_no", name="uq_deploy_attempt"),)
    deployment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_deployments.id"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    adapter: Mapped[str] = mapped_column(String(30))  # manual | gitlab_pipeline | script
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)  # QUEUED | RUNNING | WAITING | SUCCEEDED | FAILED
    queued_at: Mapped[datetime] = mapped_column(UTCDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    triggered_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    worker: Mapped[str | None] = mapped_column(String(120))
    target: Mapped[str] = mapped_column(String(200))  # environment code + version, frozen at queue time
    gate_snapshot: Mapped[str] = mapped_column(LongText)  # JSON of the gate evaluation that allowed it
    external_ref: Mapped[str | None] = mapped_column(String(200))  # e.g. GitLab pipeline id
    external_url: Mapped[str | None] = mapped_column(String(500))
    log: Mapped[str | None] = mapped_column(LongText)  # secrets masked
    health: Mapped[str | None] = mapped_column(LongText)  # JSON health-check result
    failure_reason: Mapped[str | None] = mapped_column(String(1000))
