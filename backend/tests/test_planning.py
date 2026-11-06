"""Architecture §9 and acceptance scenario G: plans, WBS, validated transitions, gates, dependencies, scope isolation, baselines, CSV."""
from __future__ import annotations

import pytest

API = "/api/v1"


def _alpha(c):
    return next(p for p in c.get(f"{API}/projects").json() if p["code"] == "ALPHA")


def _plan_id(c):
    items = c.get(f"{API}/projects/{_alpha(c)['id']}/plans").json()["items"]
    return next(p for p in items if p["status"] == "ACTIVE")["id"]


def _new_task(c, project_id, **kw):
    body = {"title": kw.pop("title", "A planning test task"), "project_id": project_id, **kw}
    r = c.post(f"{API}/work-items", json=body)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def pe(client_factory):
    return client_factory("pe.kumar")


@pytest.fixture()
def me_id(pe):
    return pe.get(f"{API}/auth/me").json()["user"]["id"]


def _go(c, task_id, to, comment=None):
    return c.post(f"{API}/work-items/{task_id}/transition", json={"to": to, "comment": comment})


def test_seeded_plan_wbs_and_overview_are_explainable(pe):
    pid = _plan_id(pe)
    w = pe.get(f"{API}/plans/{pid}").json()
    assert w["work_packages"] and w["activities"] and w["tasks"] and w["milestones"] and w["dependencies"]
    assert {f["code"] for f in w["phases"]} >= {"PRELIM", "DETAIL"}, "project phases replace the shared SDLC template"
    ov = pe.get(f"{API}/plans/{pid}/overview").json()
    assert 0 < ov["progress"] < 100
    assert ov["tasks"]["total"] == len(w["tasks"])
    assert ov["tasks"]["overdue"] >= 1 and ov["overdue"][0]["days_late"] > 0
    assert ov["workload"] and ov["calculation"]["rule"]
    assert ov["cross_directorate_dependencies"], "a CTL task waits on an ELX task in the seed"
    row = ov["cross_directorate_dependencies"][0]
    assert row["successor_owner"] and row["predecessor_owner"] and row["successor_org"]["code"] != row["predecessor_org"]["code"]
    assert any(t["critical"] for t in w["tasks"])


def test_lifecycle_rejects_illegal_jumps_and_requires_reasons(pe, me_id):
    project = _alpha(pe)["id"]
    t = _new_task(pe, project, assignee_id=me_id)
    assert t["status"] == "OPEN"
    r = _go(pe, t["id"], "COMPLETED")
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_TRANSITION"
    assert "IN_PROGRESS" in r.json()["error"]["details"]["allowed"]
    assert _go(pe, t["id"], "NOT_A_STATE").json()["error"]["code"] == "INVALID_STATE"
    assert _go(pe, t["id"], "ON_HOLD").json()["error"]["code"] == "REASON_REQUIRED"
    assert _go(pe, t["id"], "ON_HOLD", "Waiting for a test rig").status_code == 200
    assert _go(pe, t["id"], "OPEN").status_code == 200
    d = _go(pe, t["id"], "IN_PROGRESS").json()
    assert d["actual_start"]
    assert [h["to"] for h in d["history"] if h["kind"] == "STATUS"] == ["ON_HOLD", "OPEN", "IN_PROGRESS"]
    # PUT no longer carries status, so a stale client cannot skip the gates
    r = pe.put(f"{API}/work-items/{t['id']}", json={"title": t["title"], "project_id": project, "assignee_id": me_id, "status": "COMPLETED"})
    assert r.status_code == 200 and r.json()["status"] == "IN_PROGRESS"


def test_progress_is_not_set_by_the_client(pe, me_id):
    project = _alpha(pe)["id"]
    t = _new_task(pe, project, assignee_id=me_id, reported_progress=100)
    assert t["progress"] == 0, "an unstarted task stays at 0 whatever the client sends"
    _go(pe, t["id"], "IN_PROGRESS")
    body = {"title": t["title"], "project_id": project, "assignee_id": me_id, "reported_progress": 100}
    u = pe.put(f"{API}/work-items/{t['id']}", json=body).json()
    assert u["progress"] == 95, "only the completion gate can give 100"
    _go(pe, t["id"], "REVIEW")
    assert _go(pe, t["id"], "COMPLETED").json()["progress"] == 100


def test_completion_gates_block_until_satisfied(pe, me_id):
    project = _alpha(pe)["id"]
    parent = _new_task(pe, project, title="Gated parent task", assignee_id=me_id)
    child = _new_task(pe, project, title="Gated child task", assignee_id=me_id, parent_id=parent["id"], estimated_hours=10)
    d = pe.post(f"{API}/work-items/{parent['id']}/checklist", json={"text": "Peer check done"}).json()
    item = d["checklist"][0]["id"]
    _go(pe, parent["id"], "IN_PROGRESS")
    _go(pe, parent["id"], "REVIEW")
    r = _go(pe, parent["id"], "COMPLETED")
    assert r.status_code == 400 and r.json()["error"]["code"] == "GATE_BLOCKED"
    errors = " | ".join(r.json()["error"]["details"]["errors"])
    assert child["key"] in errors and "Peer check done" in errors
    pe.patch(f"{API}/work-items/{parent['id']}/checklist/{item}", json={"done": True})
    _go(pe, child["id"], "IN_PROGRESS")
    pe.put(f"{API}/work-items/{child['id']}", json={"title": child["title"], "project_id": project, "assignee_id": me_id, "parent_id": parent["id"], "estimated_hours": 10, "reported_progress": 50})
    assert pe.get(f"{API}/work-items/{parent['id']}").json()["progress"] == 50, "a parent rolls up from its children"
    _go(pe, child["id"], "REVIEW")
    _go(pe, child["id"], "COMPLETED")
    assert _go(pe, parent["id"], "COMPLETED").status_code == 200


def test_mandatory_deliverable_uses_real_document_status(pe, me_id):
    project = _alpha(pe)["id"]
    docs = pe.get(f"{API}/documents", params={"status": "IN_REVIEW", "page_size": 5}).json()["items"]
    assert docs
    t = _new_task(pe, project, assignee_id=me_id)
    pe.post(f"{API}/work-items/{t['id']}/deliverables", json={"document_id": docs[0]["id"]})
    _go(pe, t["id"], "IN_PROGRESS")
    _go(pe, t["id"], "REVIEW")
    r = _go(pe, t["id"], "COMPLETED")
    assert r.status_code == 400 and docs[0]["number"] in r.text
    assert pe.get(f"{API}/work-items/{t['id']}").json()["completion_blockers"]


def test_named_reviewer_means_owner_cannot_self_accept(pe, me_id, client_factory):
    project = _alpha(pe)["id"]
    other = client_factory("eng.priya")
    other_id = other.get(f"{API}/auth/me").json()["user"]["id"]
    t = _new_task(other, project, assignee_id=other_id)
    assert pe.put(f"{API}/work-items/{t['id']}/participants", json={"contributors": [], "reviewers": [me_id]}).status_code == 200
    _go(other, t["id"], "IN_PROGRESS")
    _go(other, t["id"], "REVIEW")
    r = _go(other, t["id"], "COMPLETED")
    assert r.status_code == 403 and r.json()["error"]["code"] == "SOD_VIOLATION"
    assert _go(pe, t["id"], "CHANGES_REQUESTED").json()["error"]["code"] == "REASON_REQUIRED"
    assert _go(pe, t["id"], "COMPLETED").status_code == 200


def test_dependencies_block_start_and_reject_cycles(pe, me_id):
    project = _alpha(pe)["id"]
    a = _new_task(pe, project, title="Predecessor task", assignee_id=me_id)
    b = _new_task(pe, project, title="Successor task", assignee_id=me_id)
    c = _new_task(pe, project, title="Third task in chain", assignee_id=me_id)
    assert pe.post(f"{API}/work-items/{b['id']}/dependencies", json={"predecessor_id": a["id"], "type": "FS", "lag_days": 2}).status_code == 200
    assert pe.post(f"{API}/work-items/{c['id']}/dependencies", json={"predecessor_id": b["id"]}).status_code == 200
    r = pe.post(f"{API}/work-items/{a['id']}/dependencies", json={"predecessor_id": c["id"]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "CYCLE"
    assert pe.post(f"{API}/work-items/{a['id']}/dependencies", json={"predecessor_id": a["id"]}).json()["error"]["code"] == "CYCLE"
    assert pe.post(f"{API}/work-items/{b['id']}/dependencies", json={"predecessor_id": a["id"]}).status_code == 409
    r = _go(pe, b["id"], "IN_PROGRESS")
    assert r.status_code == 400 and a["key"] in r.text
    _go(pe, a["id"], "IN_PROGRESS")
    _go(pe, a["id"], "REVIEW")
    _go(pe, a["id"], "COMPLETED")
    assert _go(pe, b["id"], "IN_PROGRESS").status_code == 200


def test_scope_isolation_on_plans_and_tasks(pe, client_factory):
    adm = client_factory("adm.babu")
    project = _alpha(pe)
    pid = _plan_id(pe)
    assert adm.get(f"{API}/projects/{project['id']}/plans").status_code == 403
    assert adm.get(f"{API}/plans/{pid}").status_code == 403
    assert adm.get(f"{API}/plans/{pid}/overview").status_code == 403
    assert adm.get(f"{API}/plans/{pid}/export.csv").status_code == 403
    assert adm.get(f"{API}/projects/{project['id']}/tree").status_code == 403
    alpha_task = pe.get(f"{API}/plans/{pid}").json()["tasks"][0]
    assert adm.get(f"{API}/work-items/{alpha_task['id']}").status_code == 403
    assert _go(adm, alpha_task["id"], "CANCELLED", "not mine").status_code == 403
    keys = [w["key"] for w in adm.get(f"{API}/work-items").json()]
    assert keys and not any(k.startswith("ALPHA-") for k in keys), "task lists must not leak across directorates"
    # task.manage in another scope no longer means the right to change any task
    assert adm.put(f"{API}/work-items/{alpha_task['id']}", json={"title": "Hijacked title", "project_id": project["id"]}).status_code == 403
    assert not any(p["project"]["code"] == "ALPHA" for p in adm.get(f"{API}/planning/portfolio").json())


def test_plan_management_needs_plan_permission(pe, client_factory):
    project = _alpha(pe)["id"]
    member = client_factory("eng.priya")
    assert member.post(f"{API}/projects/{project}/plans", json={"name": "Not allowed"}).status_code == 403
    plan = pe.post(f"{API}/projects/{project}/plans", json={"name": "Replan draft"})
    assert plan.status_code == 200 and plan.json()["status"] == "DRAFT"
    wp = pe.post(f"{API}/plans/{plan.json()['id']}/work-packages", json={"code": "WP-T", "name": "Test package"})
    assert wp.status_code == 200
    assert pe.post(f"{API}/plans/{plan.json()['id']}/work-packages", json={"code": "WP-T", "name": "Duplicate"}).status_code == 409
    a = pe.post(f"{API}/plans/{plan.json()['id']}/activities", json={"title": "Test activity", "work_package_id": wp.json()["id"], "start_date": "2027-01-10", "end_date": "2027-01-01"})
    assert a.status_code == 400
    a = pe.post(f"{API}/plans/{plan.json()['id']}/activities", json={"title": "Test activity", "work_package_id": wp.json()["id"]})
    assert a.status_code == 200
    t = _new_task(pe, project, activity_id=a.json()["id"])
    assert t["plan"]["id"] == plan.json()["id"] and t["work_package"]["code"] == "WP-T", "links are derived from the activity"
    r = pe.put(f"{API}/activities/{a.json()['id']}", json={"title": "Test activity", "status": "COMPLETED"})
    assert r.status_code == 400 and t["key"] in r.text
    assert pe.delete(f"{API}/activities/{a.json()['id']}").status_code == 409


def test_links_must_agree_with_the_project(pe):
    plan = _plan_id(pe)
    assert pe.post(f"{API}/work-items", json={"title": "Plan link without its project", "plan_id": plan}).status_code == 400


def test_scenario_g_full_progress_with_open_gate_is_not_complete(pe, me_id):
    project = _alpha(pe)["id"]
    plan = pe.post(f"{API}/projects/{project}/plans", json={"name": "Scenario G plan"}).json()["id"]
    activity = pe.post(f"{API}/plans/{plan}/activities", json={"title": "Only activity", "estimated_hours": 10}).json()["id"]
    t = _new_task(pe, project, activity_id=activity, assignee_id=me_id)
    _go(pe, t["id"], "IN_PROGRESS")
    _go(pe, t["id"], "REVIEW")
    _go(pe, t["id"], "COMPLETED")
    pe.post(f"{API}/projects/{project}/milestones", json={"name": "Scenario G gate", "plan_id": plan, "due_date": "2030-01-01"})
    ov = pe.get(f"{API}/plans/{plan}/overview").json()
    assert ov["progress"] == 100
    assert ov["open_gates"] and ov["fully_complete"] is False


def test_milestone_gate_and_reason(pe, me_id):
    project = _alpha(pe)["id"]
    m = pe.post(f"{API}/projects/{project}/milestones", json={"name": "Gated milestone", "due_date": "2030-01-01"}).json()
    t = _new_task(pe, project, assignee_id=me_id, milestone_id=m["id"])
    r = pe.put(f"{API}/milestones/{m['id']}", json={"name": "Gated milestone", "due_date": "2030-01-01", "status": "ACHIEVED"})
    assert r.status_code == 400 and t["key"] in r.text
    assert pe.put(f"{API}/milestones/{m['id']}", json={"name": "Gated milestone", "due_date": "2031-01-01"}).json()["error"]["code"] == "REASON_REQUIRED"
    assert pe.put(f"{API}/milestones/{m['id']}", json={"name": "Gated milestone", "due_date": "2031-01-01", "reason": "Rig slipped"}).status_code == 200


def test_baseline_is_sealed_and_compares(pe, me_id):
    project = _alpha(pe)["id"]
    plan = pe.post(f"{API}/projects/{project}/plans", json={"name": "Baseline plan"}).json()["id"]
    a = pe.post(f"{API}/plans/{plan}/activities", json={"title": "Baselined activity"}).json()["id"]
    t = _new_task(pe, project, activity_id=a, assignee_id=me_id, start_date="2030-01-01", due_date="2030-02-01")
    assert pe.post(f"{API}/plans/{plan}/baselines", json={"label": "x", "reason": "first"}).status_code == 422
    b = pe.post(f"{API}/plans/{plan}/baselines", json={"label": "PDR baseline", "reason": "Approved at PDR"}).json()
    assert b["seq"] == 1 and len(b["sha256"]) == 64
    pe.put(f"{API}/work-items/{t['id']}", json={"title": t["title"], "project_id": project, "activity_id": a, "assignee_id": me_id, "start_date": "2030-01-01", "due_date": "2030-02-11"})
    added = _new_task(pe, project, activity_id=a, title="Added after baseline")
    cmp = pe.get(f"{API}/baselines/{b['id']}/compare").json()
    assert cmp["integrity_ok"] is True
    assert cmp["tasks"]["moved"][0]["slip_days"] == 10
    assert [x["key"] for x in cmp["tasks"]["added"]] == [added["key"]]


def test_csv_export_neutralises_formulas_and_import_validates(pe):
    project = _alpha(pe)["id"]
    plan = pe.post(f"{API}/projects/{project}/plans", json={"name": "CSV plan"}).json()["id"]
    pe.post(f"{API}/plans/{plan}/activities", json={"title": "CSV activity"})
    bad = "title,priority,assignee,due_date\nGood row title,HIGH,pe.kumar,2030-01-01\nx,URGENT,nobody,not-a-date\n"
    r = pe.post(f"{API}/plans/{plan}/import", files={"file": ("p.csv", bad, "text/csv")}, params={"dry_run": "false"}).json()
    assert r["committed"] is False and r["errors"][0]["row"] == 3 and len(r["errors"][0]["errors"]) == 4
    assert pe.get(f"{API}/plans/{plan}").json()["tasks"] == [], "one bad row means nothing is written"
    good = "title,activity,priority\n=HYPERLINK(1) risky title,CSV activity,HIGH\nSecond task title,,LOW\n"
    dry = pe.post(f"{API}/plans/{plan}/import", files={"file": ("p.csv", good, "text/csv")}).json()
    assert dry["dry_run"] is True and dry["would_create"] == 2 and pe.get(f"{API}/plans/{plan}").json()["tasks"] == []
    done = pe.post(f"{API}/plans/{plan}/import", files={"file": ("p.csv", good, "text/csv")}, params={"dry_run": "false"}).json()
    assert done["created"] == 2
    assert "'=HYPERLINK(1) risky title" in pe.get(f"{API}/plans/{plan}/export.csv").text


def test_lifecycle_is_configurable_and_validated(client_factory):
    proc = client_factory("proc.krishnan")
    pe = client_factory("pe.kumar")
    base = proc.get(f"{API}/task-lifecycle").json()
    assert {"states", "transitions", "completion_rules"} <= set(base)
    new = {"states": base["states"], "transitions": base["transitions"] + [{"from": "COMPLETED", "to": "IN_PROGRESS", "label": "Reopen", "actors": ["manager"], "reason": True}]}
    assert pe.put(f"{API}/task-lifecycle", json=new).status_code == 403
    cut = {"states": [s for s in base["states"] if s["code"] != "ON_HOLD"], "transitions": [t for t in base["transitions"] if "ON_HOLD" not in (t["from"], t["to"])]}
    r = proc.put(f"{API}/task-lifecycle", json=cut)
    assert r.status_code == 400 and "ON_HOLD" in r.text, "a state in use cannot be removed"
    assert proc.put(f"{API}/task-lifecycle", json={"states": base["states"], "transitions": [{"from": "OPEN", "to": "NOPE", "actors": ["manager"]}]}).status_code == 400
    assert proc.put(f"{API}/task-lifecycle", json=new).status_code == 200
    assert any(t["from"] == "COMPLETED" for t in pe.get(f"{API}/task-lifecycle").json()["transitions"])
    assert proc.put(f"{API}/task-lifecycle", json={"states": base["states"], "transitions": base["transitions"]}).status_code == 200


def test_every_change_is_audited(pe, me_id, client_factory):
    project = _alpha(pe)["id"]
    t = _new_task(pe, project, assignee_id=me_id)
    _go(pe, t["id"], "IN_PROGRESS")
    qa = client_factory("qa.verma")
    rows = qa.get(f"{API}/audit", params={"q": t["key"], "page_size": 20}).json()["items"]
    assert {"task.create", "task.transition"} <= {r["action"] for r in rows}


def test_due_date_sweep_notifies_once(pe):
    from app.core.db import SessionLocal
    from app.services import planning_sweep

    db = SessionLocal()
    try:
        first = planning_sweep.sweep(db)
        db.commit()
        again = planning_sweep.sweep(db)
        db.commit()
    finally:
        db.close()
    assert first > 0 and again == 0
