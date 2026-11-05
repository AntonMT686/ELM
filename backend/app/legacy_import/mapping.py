"""PMS → ELM code mappings, kept apart from the loader so ADA can review and change them.

A mapping of None means "do not guess": the row is reported for a person to decide (PROJECT_CONTEXT §16.3)."""
from __future__ import annotations

import re
from datetime import timedelta, timezone

# PMS stores most local times in IST. act_task_main.created_on is the exception: for the same event it reads 5h30 behind
# workflow.created_date (task 1: 12:09:44 against 17:39:44), so it is treated as UTC.
LEGACY_TZ = timezone(timedelta(hours=5, minutes=30), "IST")

# auth_item.name → ELM role code. The PMS codes are not ELM's: PMS `td` is "Test Case Editor", not ELM's TD, and `tm` is
# "Technical Manager". None = no business authority is granted automatically; the person is listed for an administrator.
ROLE_MAP: dict[str, str | None] = {
    "admin": None,   # the sysadmin flag and business authority are separate in ELM; decide per person
    "cm": None,      # release authority is a governance decision, not a data mapping
    "pm": "PE",
    "tl": "PE",
    "tm": "PE",
    "dev": "TEAM_MEMBER",
    "rm": "TEAM_MEMBER",
    "rd": "TEAM_MEMBER",
    "td": "TEAM_MEMBER",
    "te": "TEAM_MEMBER",
    "re": "TEAM_MEMBER",
    "rv": "REVIEWER",
}

PROJECT_STATUS = {1: "ACTIVE", 2: "ON_HOLD"}  # projectstatus.id
PLAN_STATUS = {"draft": "DRAFT", "active": "ACTIVE", "archived": "ARCHIVED"}
ACTIVITY_STATUS = {"not_started": "NOT_STARTED", "in_progress": "IN_PROGRESS", "completed": "COMPLETED", "on_hold": "ON_HOLD", "cancelled": "CANCELLED"}
PRIORITY = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "critical": "CRITICAL"}
# project_milestone.status / milestone.status, as documented in models/ProjectMilestone.php
MILESTONE_STATUS = {0: "PLANNED", 1: "IN_PROGRESS", 2: "ACHIEVED", 3: "ACHIEVED", 4: "CANCELLED"}
# requirements.states. A state not listed here is reported and imported as DRAFT. "Baselined" also needs evidence: the loader
# keeps it only when baselined_requirements holds the requirement, and otherwise falls back to APPROVED and reports it.
REQUIREMENT_STATE = {"proposed": "DRAFT", "reviewing": "UNDER_REVIEW", "reviewed": "UNDER_REVIEW", "approving": "UNDER_REVIEW", "approved": "APPROVED", "validated": "APPROVED", "rejected": "REJECTED", "baselined": "BASELINED"}
# The tag's type suffix (tag_type table): SEC and INFO tags mark sections and information, not requirements.
REQUIREMENT_TYPE_SUFFIX = {"REQ": "FUNCTIONAL", "SEC": "SECTION", "INFO": "INFORMATION"}
REQUIREMENT_PRIORITY = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "critical": "CRITICAL"}
EMPLOYMENT_ENDED = {5, 6}  # masterdata_main EMPSTATUS: RESSIGNED, TERMINATE
PHASE_ALIASES = {"requirement": "REQUIREMENTS", "requirements": "REQUIREMENTS", "design": "DESIGN", "development": "DEVELOPMENT", "testing": "TESTING", "deployment": "DEPLOYMENT", "maintenance": "MAINTENANCE", "planning": "PLANNING"}
ACTION_RECORD_TYPES = {"mom"}  # record_types.record_type treated as action items instead of tasks

# PMS has over 200 per-type state names. The name decides first, because state_status groups some names misleadingly
# (On_Hold sits in group 1, TCC_Close in group 6); the group number covers the rest.
_NAME_RULES = [
    (re.compile(r"short.?clos", re.I), "CANCELLED"),
    (re.compile(r"reject", re.I), "CHANGES_REQUESTED"),
    (re.compile(r"on.?hold|holding", re.I), "ON_HOLD"),
    (re.compile(r"clos|finish", re.I), "COMPLETED"),
]
_STATUS_GROUPS = {
    1: "OPEN",               # submitted, not picked up
    2: "OPEN",               # assigned, not picked up
    3: "IN_PROGRESS",        # opened by the assignee
    4: "REVIEW",             # resolved, waiting for verification
    5: "REVIEW",             # submitted for freeze or verification
    6: "REVIEW",             # assigned for review
    7: "COMPLETED",
    8: "CHANGES_REQUESTED",
    9: "ON_HOLD",            # waiting for a clarification
}


def map_state(name: str | None, group: int | None) -> str | None:
    """ELM status for a PMS state, or None when neither rule applies, which the loader reports as an exception."""
    for pattern, target in _NAME_RULES:
        if name and pattern.search(name):
            return target
    return _STATUS_GROUPS.get(group) if group is not None else None
