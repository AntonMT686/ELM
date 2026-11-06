"""Architecture §13: reviewed test cases, approved and activated plans, runs, append-only executions with evidence,
failure taxonomy (only application defects create defects), defect lifecycle with retest and verification, SoD on
defect verification and run closure, exit criteria, automation jobs (no runner = clear failure, idempotent results)."""
from __future__ import annotations

import pytest

from app.core.config import get_settings

API = "/api/v1"


@pytest.fixture(scope="module")
def pe(client_factory):
    return client_factory("pe.kumar")


@pytest.fixture(scope="module")
def qa(client_factory):
    return client_factory("qa.verma")


@pytest.fixture(scope="module")
def joshi(client_factory):
    return client_factory("rev.joshi")


@pytest.fixture(scope="module")
def project(pe):
    return next(p for p in pe.get(f"{API}/projects").json() if p["code"] == "ALPHA")["id"]


def _uid(c):
    return c.get(f"{API}/auth/me").json()["user"]["id"]


STEPS = [{"action": "Apply input pattern P1", "expected": "Output matches table T1"}]


def _approved_case(pe, joshi, project, title, **kw):
    c = pe.post(f"{API}/projects/{project}/test-cases", json={"title": title, "steps": STEPS, "test_type": "FUNCTIONAL", **kw}).json()
    pe.post(f"{API}/test-cases/{c['id']}/submit", json={"approvers": [_uid(joshi)]})
    rid = joshi.get(f"{API}/test-cases/{c['id']}").json()["reviews"][0]["id"]
    out = joshi.post(f"{API}/test-cases/{c['id']}/reviews/{rid}/decide", json={"decision": "approve"}).json()
    assert out["status"] == "APPROVED", out
    return out


def _active_plan(pe, joshi, project, case_ids, **exit_):
    p = pe.post(f"{API}/projects/{project}/test-plans", json={"title": "Integration campaign", "build_version": "2.0.0", "exit_criteria": exit_ or {"all_executed": True, "min_pass_rate": 100, "no_open_defects": ["CRITICAL", "HIGH"]}}).json()
    pe.post(f"{API}/test-suites/{p['suites'][0]['id']}/cases", json={"case_ids": case_ids})
    pe.post(f"{API}/test-plans/{p['id']}/submit", json={"approvers": [_uid(joshi)]})
    rid = joshi.get(f"{API}/test-plans/{p['id']}").json()["reviews"][0]["id"]
    assert joshi.post(f"{API}/test-plans/{p['id']}/reviews/{rid}/decide", json={"decision": "approve"}).json()["status"] == "APPROVED"
    act = pe.post(f"{API}/test-plans/{p['id']}/activate").json()
    assert act["status"] == "ACTIVE"
    return act


def test_seeded_campaign_and_coverage(pe, project):
    runs = pe.get(f"{API}/projects/{project}/test-runs").json()
    seeded = next(r for r in runs if r["key"] == "ALPHA-RUN-0001")
    assert seeded["counts"] == {"PASSED": 1, "FAILED": 1}
    det = pe.get(f"{API}/test-runs/{seeded['id']}").json()
    failed = next(c for c in det["cases"] if c["status"] == "FAILED")
    assert failed["executions"][-1]["defect"]["key"] == "ALPHA-DEF-0001" and failed["case"]["steps"]
    assert not det["exit"]["automatic_ok"]
    s = pe.get(f"{API}/projects/{project}/test-summary").json()
    assert s["covered_by_approved_cases"] >= 2 and s["defects_by_status"]["OPEN"] >= 1


def test_case_review_lock_and_revision(pe, joshi, project):
    c = pe.post(f"{API}/projects/{project}/test-cases", json={"title": "Watchdog restarts a hung channel", "steps": STEPS}).json()
    assert c["status"] == "DRAFT" and c["revision"] == 1 and len(c["sha256"]) == 64
    assert pe.post(f"{API}/test-cases/{c['id']}/submit", json={"approvers": [_uid(pe)]}).json()["error"]["code"] == "SOD_VIOLATION"
    pe.post(f"{API}/test-cases/{c['id']}/submit", json={"approvers": [_uid(joshi)]})
    body = {"title": "Changed while in review", "steps": STEPS}
    assert pe.put(f"{API}/test-cases/{c['id']}", json=body).json()["error"]["code"] == "LOCKED"
    rid = joshi.get(f"{API}/test-cases/{c['id']}").json()["reviews"][0]["id"]
    assert joshi.post(f"{API}/test-cases/{c['id']}/reviews/{rid}/decide", json={"decision": "approve"}).json()["status"] == "APPROVED"
    assert pe.put(f"{API}/test-cases/{c['id']}", json=body).json()["error"]["code"] == "REASON_REQUIRED"
    changed = pe.put(f"{API}/test-cases/{c['id']}", json={**body, "reason": "New timing limit"}).json()
    assert changed["status"] == "DRAFT" and changed["revision"] == 2 and [r["revision"] for r in changed["revisions"]] == [2, 1]
    req = next(r for r in pe.get(f"{API}/projects/{project}/requirements").json()["items"] if r["key"] == "ALPHA-CPU-0004")
    linked = pe.post(f"{API}/test-cases/{c['id']}/links", json={"to_type": "REQUIREMENT", "to_id": req["id"], "link_type": "verifies"}).json()
    assert linked["links"][0]["target"]["key"] == "ALPHA-CPU-0004"


def test_run_execution_defect_retest_and_closure(pe, qa, joshi, project):
    c = _approved_case(pe, joshi, project, "Output pattern P1")
    draft = pe.post(f"{API}/projects/{project}/test-cases", json={"title": "Not yet approved", "steps": STEPS}).json()
    plan = _active_plan(pe, joshi, project, [c["id"], draft["id"]])
    bad = pe.post(f"{API}/test-plans/{plan['id']}/runs", json={"title": "Run with a draft case"})
    assert bad.json()["error"]["code"] == "CASE_NOT_APPROVED"
    run = pe.post(f"{API}/test-plans/{plan['id']}/runs", json={"title": "Run A", "case_ids": [c["id"]], "executor_id": _uid(qa)}).json()
    rc = run["cases"][0]["id"]
    ex = f"{API}/test-runs/{run['id']}/cases/{rc}/execute"
    assert qa.post(ex, json={"result": "FAILED"}).json()["error"]["code"] == "CAUSE_REQUIRED"
    env = qa.post(ex, json={"result": "FAILED", "failure_cause": "environment", "actual_result": "Rig power dropped"}).json()
    assert env["cases"][0]["executions"][-1]["defect"] is None, "non-defect causes are analysis outcomes only"
    assert qa.post(ex, json={"result": "FAILED", "failure_cause": "environment", "defect_id": None}).status_code == 200
    real = qa.post(ex, json={"result": "FAILED", "failure_cause": "application_defect", "actual_result": "Output differs at row 3", "new_defect": {"title": "Row 3 mismatch", "severity": "HIGH", "assignee_id": _uid(pe)}}).json()
    last = real["cases"][0]["executions"][-1]
    assert last["defect"]["key"].startswith("ALPHA-DEF-") and last["defect"]["status"] == "OPEN"
    assert len(real["cases"][0]["executions"]) == 3, "executions are append-only"
    did = last["defect"]["id"]

    ev = qa.post(f"{API}/test-executions/{last['id']}/evidence", files={"file": ("rig.log", b"row3: expected 5 got 7\n", "text/plain")}, data={"kind": "LOG"})
    assert ev.status_code == 200 and len(ev.json()["sha256"]) == 64
    got = qa.get(f"{API}/test-evidence/{ev.json()['id']}/file")
    assert got.status_code == 200 and got.headers["x-content-sha256"] == ev.json()["sha256"]

    d = pe.get(f"{API}/defects/{did}").json()
    assert {t["to"] for t in d["transitions"]} >= {"IN_PROGRESS"}
    pe.post(f"{API}/defects/{did}/transition", json={"to": "IN_PROGRESS"})
    fixed = pe.post(f"{API}/defects/{did}/transition", json={"to": "FIXED", "fixed_in_build": "2.0.1"}).json()
    assert fixed["status"] == "FIXED" and fixed["fixed_in_build"] == "2.0.1"
    assert "VERIFIED" not in {t["to"] for t in fixed["transitions"]}, "the fixer does not verify"
    assert pe.post(f"{API}/defects/{did}/transition", json={"to": "VERIFIED"}).json()["error"]["code"] == "SOD_VIOLATION"
    r = qa.get(f"{API}/test-runs/{run['id']}").json()
    assert r["cases"][0]["status"] == "RETEST"
    assert not r["exit"]["automatic_ok"], "a case due for retest blocks closure"
    passed = qa.post(ex, json={"result": "PASSED", "actual_result": "Matches T1"}).json()
    assert passed["cases"][0]["executions"][-1]["is_retest"]
    assert qa.get(f"{API}/defects/{did}").json()["status"] == "VERIFIED", "a passing retest verifies the defect"
    assert qa.post(f"{API}/defects/{did}/transition", json={"to": "CLOSED"}).json()["status"] == "CLOSED"

    assert qa.post(f"{API}/test-runs/{run['id']}/close", json={"note": "done"}).json()["error"]["code"] == "SOD_VIOLATION", "the executor cannot close the run"
    closed = pe.post(f"{API}/test-runs/{run['id']}/close", json={"note": "Exit criteria met"}).json()
    assert closed["status"] == "CLOSED" and closed["closed_by"]["username"] == "pe.kumar"
    assert qa.post(ex, json={"result": "PASSED"}).json()["error"]["code"] == "RUN_CLOSED"


def test_failed_retest_reopens_defect_and_exit_gate(pe, qa, joshi, project):
    c = _approved_case(pe, joshi, project, "Output pattern P2")
    plan = _active_plan(pe, joshi, project, [c["id"]], all_executed=True, min_pass_rate=100, no_open_defects=["CRITICAL", "HIGH"], manual=["Rig log archived"])
    run = pe.post(f"{API}/test-plans/{plan['id']}/runs", json={"title": "Run B", "executor_id": _uid(qa)}).json()
    ex = f"{API}/test-runs/{run['id']}/cases/{run['cases'][0]['id']}/execute"
    out = qa.post(ex, json={"result": "FAILED", "failure_cause": "application_defect", "new_defect": {"title": "P2 mismatch", "severity": "CRITICAL", "assignee_id": _uid(pe)}}).json()
    did = out["cases"][0]["executions"][-1]["defect"]["id"]
    pe.post(f"{API}/defects/{did}/transition", json={"to": "IN_PROGRESS"})
    pe.post(f"{API}/defects/{did}/transition", json={"to": "FIXED"})
    again = qa.post(ex, json={"result": "FAILED", "failure_cause": "application_defect", "actual_result": "Still wrong"}).json()
    assert again["cases"][0]["executions"][-1]["defect"]["id"] == did, "a failed retest stays on the same defect"
    assert qa.get(f"{API}/defects/{did}").json()["status"] == "IN_PROGRESS", "a failed retest re-opens the defect"
    blocked = pe.post(f"{API}/test-runs/{run['id']}/close", json={"note": "try", "manual_confirmed": [True]})
    assert blocked.json()["error"]["code"] == "GATE_BLOCKED"
    errors = " ".join(blocked.json()["error"]["details"]["errors"])
    assert "Pass rate" in errors and "defects" in errors


def test_automation_jobs(pe, joshi, project):
    from app.api.v1.testing import sweep_automation
    from app.core.db import SessionLocal

    c = _approved_case(pe, joshi, project, "Automated smoke", automation_id="smoke > boots", automation_tool="playwright")
    plan = _active_plan(pe, joshi, project, [c["id"]])
    run = pe.post(f"{API}/test-plans/{plan['id']}/runs", json={"title": "Automated run"}).json()
    job = pe.post(f"{API}/test-runs/{run['id']}/automation", json={"tool": "playwright"}).json()
    assert job["status"] == "QUEUED" and job["cases"] == 1
    db = SessionLocal()
    try:
        assert sweep_automation(db) >= 1
        db.commit()
    finally:
        db.close()
    failed = pe.get(f"{API}/test-runs/{run['id']}/automation").json()[0]
    assert failed["status"] == "FAILED" and "No playwright runner" in failed["error"], "no runner means a clear failure, never a pass"
    assert pe.get(f"{API}/test-runs/{run['id']}").json()["cases"][0]["status"] == "NOT_RUN"

    s = get_settings()
    saved = (s.test_runners, s.test_results_token)
    s.test_runners, s.test_results_token = "playwright", "runner-secret"
    try:
        job2 = pe.post(f"{API}/test-runs/{run['id']}/automation", json={"tool": "playwright"}).json()
        assert pe.post(f"{API}/test-automation/claim", params={"tool": "playwright"}, headers={"X-ELM-Runner-Token": "wrong"}).status_code == 401
        claim = pe.post(f"{API}/test-automation/claim", params={"tool": "playwright"}, headers={"X-ELM-Runner-Token": "runner-secret"}).json()["job"]
        assert claim["id"] == job2["id"] and claim["cases"][0]["automation_id"] == "smoke > boots"
        body = {"job_id": job2["id"], "results": [{"run_case_id": claim["cases"][0]["run_case_id"], "result": "PASSED", "external_result_id": "pw-run-77-case-1", "duration_seconds": 3.2}], "finished": False}
        first = pe.post(f"{API}/test-automation/results", json=body, headers={"X-ELM-Runner-Token": "runner-secret"}).json()
        again = pe.post(f"{API}/test-automation/results", json={**body, "finished": True}, headers={"X-ELM-Runner-Token": "runner-secret"}).json()
        assert first["recorded"] == 1 and again["recorded"] == 0 and again["duplicates"] == 1, "retries never duplicate executions"
        assert again["job"]["status"] == "SUCCEEDED"
        det = pe.get(f"{API}/test-runs/{run['id']}").json()
        assert det["cases"][0]["status"] == "PASSED" and det["cases"][0]["executions"][-1]["source"] == "AUTOMATION"
    finally:
        s.test_runners, s.test_results_token = saved


def test_configuration_and_access(pe, project, client_factory):
    cfg = pe.get(f"{API}/test-config").json()
    assert [c["code"] for c in cfg["failure_causes"] if c["creates_defect"]] == ["application_defect"]
    assert pe.put(f"{API}/test-config/failure-causes", json={"causes": cfg["failure_causes"]}).status_code == 403, "needs workflow.configure"
    adm = client_factory("adm.babu")
    assert adm.get(f"{API}/projects/{project}/test-cases").status_code == 403
    assert adm.get(f"{API}/projects/{project}/defects").status_code == 403
    proc = client_factory("proc.krishnan")
    assert proc.put(f"{API}/test-config/failure-causes", json={"causes": [{"code": "env", "label": "Environment"}]}).json()["error"]["message"].startswith("At least one cause")
