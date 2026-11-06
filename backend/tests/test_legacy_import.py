"""PMS import on a small synthetic bundle that reproduces the quirks found in the real data."""
from __future__ import annotations

import copy
import uuid

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.legacy_import import load as loader
from app.legacy_import.mapping import ROLE_MAP, map_state
from app.models import LegacyImportMap, PlanActivity, Project, ProjectPlan, Requirement, RequirementBaselineItem, RequirementEvent, RequirementReview, RoleAssignment, TaskDependency, User, WorkItem, WorkItemEvent

BUNDLE = {
    "format": 1,
    "source": {"system": "PMS", "database": "synthetic", "extracted_at": "2026-11-04T00:00:00+00:00"},
    "inventory": {"requirement_notes": 3, "project": 2},
    "missing_tables": [],
    "data": {
        "department": [{"id": 1, "name": "Electronics Dept", "enabled": 1}],
        "user": [
            {"id": 1, "first_name": "Sys", "last_name": "Admin", "username": "ADMIN", "email": "a@example.test", "designation": None, "department_id": 1, "user_level": 1, "status": 1, "employment_status": 1, "lastLogin": None, "dateCreated": "2026-01-01 10:00:00"},
            {"id": 2, "first_name": "Test", "last_name": "Editor", "username": "tc.editor", "email": "t@example.test", "designation": "Tester", "department_id": 1, "user_level": 8, "status": 1, "employment_status": 1, "lastLogin": None, "dateCreated": None},
            {"id": 3, "first_name": "Gone", "last_name": "User", "username": "left.org", "email": "g@example.test", "designation": None, "department_id": 99, "user_level": 2, "status": 1, "employment_status": 5, "lastLogin": None, "dateCreated": None},
        ],
        "auth_item": [{"id": 1, "name": "admin", "description": "Administrator"}, {"id": 2, "name": "dev", "description": "Developer"}, {"id": 8, "name": "td", "description": "Test Case Editor"}],
        "project": [{"id": 9, "name": "Synth One", "description": "x", "status_id": 1, "short_code": "SYN1", "start_date": "2026-01-01", "end_date": "2026-12-31", "enabled": 1, "dateCreated": "2026-01-01 00:00:00"},
                    {"id": 10, "name": "Synth Two", "description": None, "status_id": 2, "short_code": "SYN2", "start_date": None, "end_date": None, "enabled": 1, "dateCreated": None}],
        "project_user_role": [{"id": 1, "project_id": 9, "user_id": 2, "role_id": 8, "status": 1}, {"id": 2, "project_id": 9, "user_id": 1, "role_id": 1, "status": 1}, {"id": 3, "project_id": 77, "user_id": 2, "role_id": 2, "status": 1}],
        "user_project_mapping": [{"id": 1, "user_id": 2, "project_id": 9, "record_status": 1}],
        "projectteam": [],
        "system": [{"id": 1, "name": "Sys A", "short_code": "SA"}],
        "subsystem": [{"id": 1, "name": "Sub A", "short_code": "SUBA"}, {"id": 2, "name": "Shared Sub", "short_code": "SHARED"}],
        "project_mapping": [{"id": 1, "project_id": 9, "system_id": 1, "subsys_id": 1, "record_status": 1}, {"id": 2, "project_id": 9, "system_id": 1, "subsys_id": 2, "record_status": 1}, {"id": 3, "project_id": 10, "system_id": 1, "subsys_id": 2, "record_status": 1}],
        "project_milestone": [{"id": 1, "project_id": 9, "milestone_name": "M1", "description": None, "start_date": "2026-02-01", "end_date": "2026-03-01", "status": 1, "created_by": 2}, {"id": 2, "project_id": 77, "milestone_name": "Orphan", "description": None, "start_date": None, "end_date": None, "status": 1, "created_by": 2}],
        "milestone": [],
        "project_plans": [{"id": 1, "project_id": 9, "name": "Plan 1", "description": None, "version": "1.0", "status": "active", "created_by": 2, "created_at": "2026-06-25 17:35:21", "updated_at": None}],
        "plan_activities": [{"id": 1, "plan_id": 1, "project_id": 9, "phase_id": 7, "title": "Reqs", "description": None, "assigned_to": 2, "start_date": "2026-06-25", "end_date": "2026-07-10", "estimated_hours": 100.0, "actual_hours": 0.0, "priority": "medium", "status": "not_started", "progress": 10.0, "sort_order": 0, "created_by": 2, "created_at": None}],
        "masterdata_main": [{"id": 7, "name": "Requirement", "code": "PLANPHASE", "record_status": 1}],
        "act_masterdata": [{"id": 76, "name": "HIGH", "code": "PRIORITY"}, {"id": 77, "name": "MEDIUM", "code": "PRIORITY"}],
        "act_task_main": [
            {"id": 1, "name": "Parent via requirement", "description": None, "task_id": "TASK0001", "state": "45", "task_type_id": 1, "record_status": "Y", "act_system": "1", "sub_system": "1", "req_id": "5", "created_by": 2, "created_on": "2026-01-22 12:09:44", "modified_on": None, "holding_reason": None, "shortclose_reason": None, "paret_task_id": None, "plan_activity_id": None, "mile_stone": None},
            {"id": 2, "name": "Child by parent, name in sub_system", "description": None, "task_id": "TASK0001", "state": "112", "task_type_id": 2, "record_status": "Y", "act_system": "", "sub_system": "Sub A", "req_id": "", "created_by": 2, "created_on": None, "modified_on": "2026-02-01 10:00:00", "holding_reason": None, "shortclose_reason": None, "paret_task_id": 1, "plan_activity_id": None, "mile_stone": None},
            {"id": 3, "name": "From plan", "description": None, "task_id": None, "state": "52", "task_type_id": 1, "record_status": "Y", "act_system": None, "sub_system": None, "req_id": None, "created_by": 2, "created_on": None, "modified_on": None, "holding_reason": None, "shortclose_reason": None, "paret_task_id": None, "plan_activity_id": 1, "mile_stone": None},
            {"id": 4, "name": "Shared subsystem, so unknown project", "description": None, "task_id": "X", "state": "999", "task_type_id": 1, "record_status": "Y", "act_system": None, "sub_system": "2", "req_id": None, "created_by": 2, "created_on": None, "modified_on": None, "holding_reason": None, "shortclose_reason": None, "paret_task_id": None, "plan_activity_id": None, "mile_stone": None},
            {"id": 5, "name": "Deleted", "description": None, "task_id": "D", "state": "52", "task_type_id": 1, "record_status": "N", "act_system": None, "sub_system": None, "req_id": None, "created_by": 2, "created_on": None, "modified_on": None, "holding_reason": None, "shortclose_reason": None, "paret_task_id": None, "plan_activity_id": None, "mile_stone": None},
        ],
        "act_schedule": [{"id": 1, "task_id": 1, "assigned_to": 2, "plan_start_date": "2026-05-06", "plan_end_date": "0000-00-00", "exp_dev_complete": "2026-05-11", "priority": 76, "estimation_hr": "8", "record_status": "Y"},
                         {"id": 2, "task_id": 3, "assigned_to": 3, "plan_start_date": "2026-06-25", "plan_end_date": "2026-07-31", "exp_dev_complete": None, "priority": 2, "estimation_hr": "500.00", "record_status": "Y"}],
        "task_dependency": [{"id": 1, "task_id": 3, "predecessor_id": 1, "type": "FS", "lag_days": 2, "created_by": 2}, {"id": 2, "task_id": 1, "predecessor_id": 3, "type": "FS", "lag_days": 0, "created_by": 2}, {"id": 3, "task_id": 1, "predecessor_id": 404, "type": "FS", "lag_days": 0, "created_by": 2}],
        "task_completion_rule": [{"id": 1, "task_type_id": None, "rule_key": "child_tasks_completed", "required": 1, "enabled": 1, "description": ""}],
        "states": [{"state_id": 45, "name": "TM_Submitted", "record_type_id": 1, "state_status": 1, "state_display_value": "submit"}, {"state_id": 112, "name": "Close", "record_type_id": 2, "state_status": 7, "state_display_value": None}, {"state_id": 52, "name": "Open", "record_type_id": 1, "state_status": 3, "state_display_value": None}],
        "record_types": [{"record_type_id": 1, "record_type": "task", "description": "General Task"}, {"record_type_id": 2, "record_type": "task_child_task_dev", "description": ""}],
        "workflow": [{"workflow_id": 1, "object_id": 1, "record_type_id": 1, "current_state": "45", "from_user": 2, "to_user": 2, "created_date": "2026-01-22 17:39:44"}, {"workflow_id": 2, "object_id": 1, "record_type_id": 7, "current_state": "1", "from_user": 2, "to_user": 2, "created_date": "2026-01-22 17:39:44"}],
        "act_dailystatus": [{"id": 1, "activity_id": 1, "remarks": "done part one", "review_remarks": "next part", "record_status": 1, "created_by": 2, "created_on": "2026-05-28 12:43:52", "availed_work_hr": "8"}],
        "requirements": [{"id": 5, "project": "Synth One"}],
        "audit_log": [{"id": 1, "user_id": 2, "username": "tc.editor", "project_id": 9, "module": "task", "entity_type": "task", "entity_id": "1", "action": "create", "old_value": None, "new_value": "x", "remarks": None, "created_at": "2026-01-22 17:39:44"}],
        "log_activity": [],
    },
}


def _load():
    db = SessionLocal()
    report = loader.Loader(db, copy.deepcopy(BUNDLE), "f" * 64).load()
    return db, report


def _task(db, legacy_title):
    return db.execute(select(WorkItem).where(WorkItem.title == legacy_title)).scalar_one()


def test_state_mapping_prefers_the_name():
    assert map_state("On_Hold", 1) == "ON_HOLD"
    assert map_state("TCC_Close", 6) == "COMPLETED"
    assert map_state("short_close", 7) == "CANCELLED"
    assert map_state("TM_Rejection", 8) == "CHANGES_REQUESTED"
    assert map_state("Assign", 2) == "OPEN"
    assert map_state("mystery", None) is None
    assert ROLE_MAP["td"] == "TEAM_MEMBER", "PMS td is Test Case Editor, not ELM's TD"
    assert ROLE_MAP["admin"] is None and ROLE_MAP["cm"] is None


def test_import_dry_run_keeps_nothing(client_factory):
    db, report = _load()
    try:
        assert report["ok"] is False, "the bundle's deliberate dependency loop is an ERROR, which stops a plain --commit"
        assert report["totals"]["exceptions"]["ERROR"] == 1
        assert all(r["match"] for r in report["reconciliation"].values()) and not report["unbalanced_counts"]
        assert report["entities"]["work_items"]["created"] == 4 and report["entities"]["work_items"]["skipped"] == 1
    finally:
        db.rollback()
        db.close()
    db = SessionLocal()
    try:
        assert db.execute(select(Project).where(Project.code == "SYN1")).first() is None
    finally:
        db.close()


def test_import_commit_rerun_and_rollback(client_factory):
    db, report = _load()
    try:
        run_id = uuid.UUID(report["run_id"])
        assert all(r["match"] for r in report["reconciliation"].values())
        assert report["deferred_tables"] == {"requirement_notes": 3}, "unmigrated tables are listed, not silently dropped"
        messages = " | ".join(e["message"] for e in report["exceptions"])
        assert "ADMIN" in messages or "admin" in messages
        assert "would create a loop" in messages and "404" in messages and "0000-00-00" in messages and "Orphan" in messages
        db.commit()

        # existing ELM account is linked, not overwritten; no legacy password is ever stored
        admin = db.execute(select(User).where(User.username == "admin")).scalar_one()
        assert admin.password_hash and admin.is_system_admin
        tester = db.execute(select(User).where(User.username == "tc.editor")).scalar_one()
        assert tester.password_hash is None and tester.is_active and tester.is_system_admin is False
        assert db.execute(select(User).where(User.username == "left.org")).scalar_one().is_active is False

        # project found through requirement, then parent, then activity; a subsystem shared by two projects is not guessed
        parent, child, planned, unknown = (_task(db, t) for t in ("Parent via requirement", "Child by parent, name in sub_system", "From plan", "Shared subsystem, so unknown project"))
        syn1 = db.execute(select(Project).where(Project.code == "SYN1")).scalar_one()
        assert parent.project_id == child.project_id == planned.project_id == syn1.id
        assert unknown.project_id is None and unknown.status == "OPEN"
        assert child.parent_id == parent.id and child.status == "COMPLETED" and child.progress == 100
        assert parent.progress == 95, "open parent with one finished child is capped below 100"
        assert parent.key.startswith("SYN1-") and parent.legacy_key == "TASK0001" and child.legacy_key == "TASK0001"
        assert str(parent.due_date) == "2026-05-11" and parent.priority == "HIGH" and parent.actual_hours == 8
        assert parent.created_at.hour == 12, "act_task_main.created_on is UTC"
        event = db.execute(select(WorkItemEvent).where(WorkItemEvent.work_item_id == parent.id, WorkItemEvent.kind == "LEGACY_STATE")).scalars().all()
        assert len(event) == 1 and event[0].to_value == "TM_Submitted", "workflow rows of other record types must not attach to this task"
        assert event[0].at.hour == 12, "workflow.created_date is IST"
        activity = db.get(PlanActivity, planned.activity_id)
        assert planned.plan_id == activity.plan_id and db.get(ProjectPlan, planned.plan_id).status == "ACTIVE"
        deps = db.execute(select(TaskDependency).where(TaskDependency.successor_id == planned.id)).scalars().all()
        assert len(deps) == 1 and deps[0].lag_days == 2
        roles = db.execute(select(RoleAssignment).where(RoleAssignment.user_id == tester.id, RoleAssignment.scope_id == syn1.id)).scalars().all()
        assert [r.role.code for r in roles] == ["TEAM_MEMBER"]
        db.close()

        # re-running adds nothing
        db, again = _load()
        assert again["totals"]["created"] == 0 and again["totals"]["already_imported"] > 0
        db.rollback()
        db.close()

        # rollback refuses once someone has used an imported record
        db = SessionLocal()
        _task(db, "From plan").version = 2
        db.commit()
        with pytest.raises(SystemExit):
            loader.rollback(db, run_id, force=False)
        db.rollback()
        _task(db, "From plan").version = 1
        db.commit()
        removed = loader.rollback(db, run_id, force=False)
        db.commit()
        assert removed["work_items"] == 4 and removed["projects"] == 2 and removed["users"] == 2
        assert db.execute(select(Project).where(Project.code == "SYN1")).first() is None
        assert db.execute(select(LegacyImportMap).where(LegacyImportMap.run_id == run_id)).first() is None
        assert db.execute(select(User).where(User.username == "admin")).scalar_one(), "a linked account survives rollback"
    finally:
        db.close()


def test_requirements_import_with_real_data_quirks(client_factory):
    bundle = copy.deepcopy(BUNDLE)
    req = lambda i, tag, state="Proposed", project="Synth One", version="1", tagname="SYNREQ": {"id": i, "name": f"Text of {tag}", "description": "Body", "project": project, "requirement_tag": tag, "states": state, "priority": "high", "type_of_development": None, "reason": None, "tag": tagname, "document": "SRS.docx", "csci_version": version, "req_version": "1", "delete_ver": None, "dateCreated": "2026-05-25 15:00:00", "dateUpdated": None}  # noqa: E731
    bundle["data"]["requirements"] = [
        req(5, "SYNREQ1"), req(6, "SYNREQ1.1", "Reviewing"), req(7, "SYNREQ1.1.1", "Baselined"), req(8, "SYNREQ2", "Baselined", project="syn1"), req(9, "SYNDUP"), req(10, "SYNDUP"), req(11, "SYNSEC1", tagname="SYNSEC"), req(12, "SYNGONE", project="Nowhere"), req(13, "SYNODD", "Mystery"),
    ]
    bundle["data"]["baselined_requirements"] = [
        {"id": 1, "baseline_name": "B1", "name": "Old text of SYNREQ2", "description": "Then", "project": "SYN1", "requirement_tag": "SYNREQ2", "priority": "high", "csci_version": "1", "tag": "SYNREQ", "req_baseline_version": 2, "dateCreated": "2026-05-27 14:36:28"},
        {"id": 2, "baseline_name": "B1", "name": "Removed since", "description": None, "project": "Synth One", "requirement_tag": "SYNLOST", "priority": None, "csci_version": "1", "tag": "SYNREQ", "req_baseline_version": 1, "dateCreated": "2026-05-27 14:36:28"},
    ]
    bundle["data"]["requirement_review"] = [{"id": 1, "requirement_id": 6, "user_id": 2, "approver": 2, "status": 1, "created_at": "2026-05-27 15:00:00"}, {"id": 2, "requirement_id": 5, "user_id": 2, "approver": 1, "status": 2, "created_at": "2026-05-27 15:00:00"}]
    bundle["data"]["log_requirements"] = [{"id": 1, "requirement_id": 5, "states": "Proposed", "action": "UPDATE", "trigger_date": "2026-05-27 14:00:00"}, {"id": 2, "requirement_id": 5, "states": "Proposed", "action": "UPDATE", "trigger_date": "2026-05-27 14:01:00"}, {"id": 3, "requirement_id": 5, "states": "Reviewing", "action": "UPDATE", "trigger_date": "2026-05-27 14:02:00"}]
    bundle["inventory"] = {}
    db = SessionLocal()
    report = loader.Loader(db, bundle, "e" * 64).load()
    try:
        by_key = {r.external_id + ("" if "~" not in r.key else r.key[r.key.index("~"):]): r for r in db.execute(select(Requirement).where(Requirement.source_id.is_not(None), Requirement.external_id.like("SYN%"))).scalars()}
        assert by_key["SYNREQ1.1"].parent_id == by_key["SYNREQ1"].id and by_key["SYNREQ1.1.1"].parent_id == by_key["SYNREQ1.1"].id
        assert by_key["SYNREQ1.1"].status == "UNDER_REVIEW"
        assert by_key["SYNREQ1.1.1"].status == "APPROVED", "Baselined in PMS without a baseline holding it is not carried over"
        assert by_key["SYNREQ2"].status == "BASELINED" and by_key["SYNREQ2"].project_id == by_key["SYNREQ1"].project_id, "project found by name or short code, in any case"
        assert by_key["SYNODD"].status == "DRAFT" and by_key["SYNSEC1"].req_type == "SECTION"
        assert "SYNDUP~9" in by_key and "SYNDUP~10" in by_key
        assert all(r.owner_id is None for r in by_key.values())
        assert report["entities"]["requirements"]["skipped"] == 1, "SYNGONE refers to a project that does not exist"
        assert report["reconciliation"]["requirements"]["match"] and not report["unbalanced_counts"]
        # undocumented review status: pending only when under review today, history otherwise, and never a decision
        pending = db.execute(select(RequirementReview).where(RequirementReview.requirement_id == by_key["SYNREQ1.1"].id)).scalars().all()
        assert [(x.role, x.status) for x in pending] == [("APPROVER", "PENDING")]
        assert db.execute(select(RequirementReview).where(RequirementReview.requirement_id == by_key["SYNREQ1"].id)).first() is None
        states = db.execute(select(RequirementEvent).where(RequirementEvent.requirement_id == by_key["SYNREQ1"].id, RequirementEvent.kind == "LEGACY_STATE")).scalars().all()
        assert [(e.from_value, e.to_value) for e in states] == [("Proposed", "Reviewing")], "only real state changes become history"
        # baseline keeps the text as it was then, even for a requirement that has gone
        items = {i.key: i for i in db.execute(select(RequirementBaselineItem)).scalars()}
        assert items["SYNREQ2"].title == "Old text of SYNREQ2" and items["SYNREQ2"].revision == 2 and items["SYNLOST"].requirement_id is None
    finally:
        db.rollback()
        db.close()
