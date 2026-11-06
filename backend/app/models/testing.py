"""Testing, verification and defects (architecture §13): test cases (reviewed), plans with entry/exit criteria, suites,
runs, append-only executions with evidence, defects with their lifecycle, and automation jobs."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow
from app.models.base import IdMixin, TimestampMixin, VersionMixin
from app.models.types import LongText, UTCDateTime


class TestCase(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "elm_test_cases"
    __test__ = False  # not a pytest class
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_projects.id"), index=True)
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_engineering_items.id"), index=True)
    key: Mapped[str] = mapped_column(String(60), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    objective: Mapped[str | None] = mapped_column(LongText)
    preconditions: Mapped[str | None] = mapped_column(LongText)
    test_type: Mapped[str] = mapped_column(String(30), default="FUNCTIONAL")
    steps: Mapped[str | None] = mapped_column(LongText)  # JSON [{action, expected}]
    expected_result: Mapped[str | None] = mapped_column(LongText)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)  # DRAFT | UNDER_REVIEW | APPROVED | OBSOLETE
    revision: Mapped[int] = mapped_column(Integer, default=1)
    content_sha256: Mapped[str] = mapped_column(String(64))
    automation_id: Mapped[str | None] = mapped_column(String(200))  # identifier in the automation tool (e.g. Playwright test title)
    automation_tool: Mapped[str | None] = mapped_column(String(40))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"), index=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))


class TestCaseRevision(IdMixin, Base):
    """Snapshot of every revision, so a run always shows the steps that were actually executed."""

    __tablename__ = "elm_test_case_revisions"
    __test__ = False
    __table_args__ = (UniqueConstraint("case_id", "revision", name="uq_case_revision"),)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_test_cases.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[str] = mapped_column(LongText)  # canonical JSON of the content fields
    content_sha256: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))


class TestPlan(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "elm_test_plans"
    __test__ = False
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_projects.id"), index=True)
    key: Mapped[str] = mapped_column(String(60), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    scope: Mapped[str | None] = mapped_column(LongText)
    build_version: Mapped[str | None] = mapped_column(String(120))
    environments: Mapped[str | None] = mapped_column(String(500))
    entry_criteria: Mapped[str | None] = mapped_column(LongText)  # JSON [text]
    exit_criteria: Mapped[str | None] = mapped_column(LongText)  # JSON {all_executed, min_pass_rate, no_open_defects: [severities], manual: [text]}
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)  # DRAFT | UNDER_REVIEW | APPROVED | ACTIVE | CLOSED
    revision: Mapped[int] = mapped_column(Integer, default=1)
    content_sha256: Mapped[str] = mapped_column(String(64))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))


class TestSuite(IdMixin, TimestampMixin, Base):
    __tablename__ = "elm_test_suites"
    __test__ = False
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_test_plans.id"), index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_test_suites.id"))
    name: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class TestSuiteCase(IdMixin, Base):
    __tablename__ = "elm_test_suite_cases"
    __test__ = False
    __table_args__ = (UniqueConstraint("suite_id", "case_id", name="uq_suite_case"),)
    suite_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_test_suites.id"), index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_test_cases.id"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class TestRun(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "elm_test_runs"
    __test__ = False
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_test_plans.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_projects.id"), index=True)
    key: Mapped[str] = mapped_column(String(60), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    build_version: Mapped[str | None] = mapped_column(String(120))
    environment: Mapped[str | None] = mapped_column(String(200))
    executor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    status: Mapped[str] = mapped_column(String(20), default="PLANNED", index=True)  # PLANNED | IN_PROGRESS | CLOSED
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    closed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    closure_note: Mapped[str | None] = mapped_column(LongText)
    closure_evaluation: Mapped[str | None] = mapped_column(LongText)  # JSON of the exit-criteria evaluation at closure
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))


class TestRunCase(IdMixin, TimestampMixin, Base):
    __tablename__ = "elm_test_run_cases"
    __test__ = False
    __table_args__ = (UniqueConstraint("run_id", "case_id", name="uq_run_case"),)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_test_runs.id"), index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_test_cases.id"), index=True)
    case_revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="NOT_RUN")  # NOT_RUN | PASSED | FAILED | BLOCKED | SKIPPED | RETEST
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    last_execution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # elm_test_executions.id (no key: the two tables point at each other)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class TestExecution(IdMixin, Base):
    """Append-only: corrections are new executions, never edits."""

    __tablename__ = "elm_test_executions"
    __test__ = False
    run_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_test_run_cases.id"), index=True)
    result: Mapped[str] = mapped_column(String(20))  # PASSED | FAILED | BLOCKED | SKIPPED
    actual_result: Mapped[str | None] = mapped_column(LongText)
    failure_cause: Mapped[str | None] = mapped_column(String(40))
    defect_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_defects.id"), index=True)
    is_retest: Mapped[bool] = mapped_column(Boolean, default=False)
    tester_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    source: Mapped[str] = mapped_column(String(20), default="MANUAL")  # MANUAL | AUTOMATION
    external_result_id: Mapped[str | None] = mapped_column(String(200), unique=True)  # makes automation re-delivery idempotent
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    executed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    notes: Mapped[str | None] = mapped_column(LongText)


class TestEvidence(IdMixin, Base):
    __tablename__ = "elm_test_evidence"
    __test__ = False
    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_test_executions.id"), index=True)
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_file_objects.id"))
    kind: Mapped[str] = mapped_column(String(30), default="ATTACHMENT")  # SCREENSHOT | LOG | VIDEO | TRACE | REPORT | ATTACHMENT
    uploaded_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))


class Defect(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "elm_defects"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_projects.id"), index=True)
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_engineering_items.id"))
    key: Mapped[str] = mapped_column(String(60), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(LongText)
    severity: Mapped[str] = mapped_column(String(20), default="MEDIUM")  # LOW | MEDIUM | HIGH | CRITICAL
    priority: Mapped[str] = mapped_column(String(10), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)  # §13.4 lifecycle
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"), index=True)
    reporter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    fixed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    found_in_build: Mapped[str | None] = mapped_column(String(120))
    fixed_in_build: Mapped[str | None] = mapped_column(String(120))
    work_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_work_items.id"))  # fix task (for example a DEVELOPMENT task)
    resolution: Mapped[str | None] = mapped_column(LongText)


class TestAutomationJob(IdMixin, TimestampMixin, Base):
    """A request to run automated cases. Results come back through the validated ingestion API."""

    __tablename__ = "elm_test_automation_jobs"
    __test__ = False
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elm_test_runs.id"), index=True)
    tool: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)  # QUEUED | RUNNING | SUCCEEDED | FAILED
    case_ids: Mapped[str] = mapped_column(LongText)  # JSON list of run-case ids
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("elm_users.id"))
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    error: Mapped[str | None] = mapped_column(String(1000))
    results_received: Mapped[int] = mapped_column(Integer, default=0)
