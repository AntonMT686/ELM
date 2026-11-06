"""Architecture §14: environments with approved configurations, deployment requests, hash-bound approvals with SoD,
validation gates that name the missing condition, queued execution through manual / GitLab pipeline / script adapters,
masked logs, health checks, retry as a new attempt, rollback as a new deployment, signed CI callback, access."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import textwrap

import pytest

from app.core.config import get_settings
from tests.fake_gitlab import TOKEN, FakeGitLab
from tests.test_testing import _active_plan, _approved_case

API = "/api/v1"


@pytest.fixture(scope="module")
def gitlab():
    fake = FakeGitLab()
    s = get_settings()
    saved = (s.gitlab_enabled, s.gitlab_url, s.gitlab_token, s.deploy_health_retry_seconds, s.deploy_callback_secret, s.deploy_scripts_dir)
    s.gitlab_enabled, s.gitlab_url, s.gitlab_token, s.deploy_health_retry_seconds, s.deploy_callback_secret = True, fake.url, TOKEN, 0, "cb-secret"
    yield fake
    s.gitlab_enabled, s.gitlab_url, s.gitlab_token, s.deploy_health_retry_seconds, s.deploy_callback_secret, s.deploy_scripts_dir = saved
    fake.stop()


@pytest.fixture(scope="module")
def pe(client_factory):
    return client_factory("pe.kumar")


@pytest.fixture(scope="module")
def td(client_factory):
    return client_factory("td.menon")


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


def _worker():
    from app.core.db import SessionLocal
    from app.services.deployment import run_pending

    db = SessionLocal()
    try:
        n = run_pending(db)
        db.commit()
        return n
    finally:
        db.close()


def _env(pe, td, project, code, cfg, approve=True):
    r = pe.post(f"{API}/projects/{project}/deploy-environments", json={"code": code, "name": f"{code} environment", "config": cfg})
    assert r.status_code == 200, r.text
    e = r.json()
    if approve and e["config"]["require_config_approval"]:
        e = td.post(f"{API}/deploy-environments/{e['id']}/approve-config").json()
        assert e["config_status"] == "APPROVED"
    return e


def _closed_run(pe, qa, joshi, project, build):
    c = _approved_case(pe, joshi, project, f"Smoke {build}")
    plan = _active_plan(pe, joshi, project, [c["id"]])
    pe.put(f"{API}/test-plans/{plan['id']}", json={**{k: plan[k] for k in ("title", "scope", "environments", "entry_criteria", "exit_criteria")}, "build_version": build, "reason": "set build"})
    # editing an active plan returns it to draft; approve and activate again
    p = pe.get(f"{API}/test-plans/{plan['id']}").json()
    if p["status"] == "DRAFT":
        pe.post(f"{API}/test-plans/{plan['id']}/submit", json={"approvers": [_uid(joshi)]})
        rid = joshi.get(f"{API}/test-plans/{plan['id']}").json()["reviews"][0]["id"]
        joshi.post(f"{API}/test-plans/{plan['id']}/reviews/{rid}/decide", json={"decision": "approve"})
        pe.post(f"{API}/test-plans/{plan['id']}/activate")
    run = pe.post(f"{API}/test-plans/{plan['id']}/runs", json={"title": f"Run for {build}", "executor_id": _uid(qa)}).json()
    qa.post(f"{API}/test-runs/{run['id']}/cases/{run['cases'][0]['id']}/execute", json={"result": "PASSED"})
    return run


def _request(pe, project, env, version, **kw):
    r = pe.post(f"{API}/projects/{project}/deployments", json={"environment_id": env["id"], "version_label": version, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _approve(td, d):
    rid = next(a["id"] for a in td.get(f"{API}/deployments/{d['id']}").json()["approvals"] if a["mine"])
    out = td.post(f"{API}/deployments/{d['id']}/approvals/{rid}/decide", json={"decision": "approve"}).json()
    assert out["status"] == "APPROVED", out
    return out


def _manual_success(pe, d):
    det = pe.get(f"{API}/deployments/{d['id']}").json()
    a = next(x for x in det["attempts"] if x["status"] == "WAITING")
    return pe.post(f"{API}/deployment-attempts/{a['id']}/report", json={"outcome": "SUCCEEDED", "log": "installed"}).json()


def test_seeded_environments_and_overview(pe, project):
    ov = pe.get(f"{API}/projects/{project}/deployment-overview").json()
    by = {x["environment"]["code"]: x for x in ov}
    assert by["INT"]["current"]["version_label"] == "1.4.0"
    assert by["UAT"]["in_flight"][0]["status"] == "AWAITING_APPROVAL"
    d3 = by["UAT"]["in_flight"][0]
    gates = {g["code"]: g for g in pe.get(f"{API}/deployments/{d3['id']}/gates").json()["gates"]}
    assert not gates["test"]["ok"] and "ALPHA-RUN-0001 is in progress" in gates["test"]["detail"], "the gate names the exact missing condition"
    assert not gates["approval"]["ok"] and "0 of 1" in gates["approval"]["detail"]
    envs = pe.get(f"{API}/projects/{project}/deploy-environments").json()["items"]
    assert next(e for e in envs if e["code"] == "PROD")["config_status"] == "DRAFT"


def test_configuration_validation_and_approval_sod(pe, td, project, gitlab):
    bad = pe.post(f"{API}/projects/{project}/deploy-environments", json={"code": "BAD", "name": "Bad", "config": {"blocking_defect_severities": ["SEVERE"], "adapter": "gitlab_pipeline", "secrets": ["lower"], "change_window": {"days": [9], "start": "25:00", "end": "x"}}})
    errs = bad.json()["error"]["details"]["errors"]
    assert bad.json()["error"]["code"] == "CONFIG_INVALID" and len(errs) == 4
    assert pe.post(f"{API}/projects/{project}/deploy-environments", json={"code": "X1", "name": "xx", "config": {"nonsense": 1}}).status_code == 400
    e = _env(pe, td, project, "SYS", {"approvals_required": 1}, approve=False)
    assert e["config_status"] == "DRAFT"
    own = pe.post(f"{API}/deploy-environments/{e['id']}/approve-config")
    assert own.status_code == 403, "PE has no approval right and changed it"
    ok = td.post(f"{API}/deploy-environments/{e['id']}/approve-config").json()
    assert ok["config_status"] == "APPROVED"
    changed = pe.put(f"{API}/deploy-environments/{e['id']}", json={"code": "SYS", "name": "SYS environment", "config": {"approvals_required": 2}}).json()
    assert changed["config_status"] == "DRAFT", "an edited configuration needs approval again"
    td_edit = td.put(f"{API}/deploy-environments/{e['id']}", json={"code": "SYS", "name": "SYS environment", "config": {"approvals_required": 3}}).json()
    assert td.post(f"{API}/deploy-environments/{td_edit['id']}/approve-config").json()["error"]["code"] == "SOD_VIOLATION"


def test_manual_flow_gates_health_retry_and_rollback(pe, td, qa, joshi, project, gitlab, client_factory):
    run = _closed_run(pe, qa, joshi, project, "2.0.0")
    env = _env(pe, td, project, "SIT", {"approvals_required": 1, "checklist": ["Smoke plan ready"], "health_check": {"url": f"{gitlab.url}/health", "retries": 2, "timeout_seconds": 5}})
    d = _request(pe, project, env, "2.0.0", test_run_id=run["id"])
    assert d["status"] == "PLANNED" and len(d["sha256"]) == 64
    assert pe.post(f"{API}/deployments/{d['id']}/submit", json={"approvers": []}).json()["error"]["code"] == "APPROVER_REQUIRED"
    assert pe.post(f"{API}/deployments/{d['id']}/submit", json={"approvers": [_uid(pe)]}).status_code == 403, "requester cannot approve"
    assert pe.post(f"{API}/deployments/{d['id']}/submit", json={"approvers": [_uid(joshi)]}).json()["error"]["details"]["permission"] == "deploy.approve"
    assert pe.post(f"{API}/deployments/{d['id']}/submit", json={"approvers": [_uid(td)]}).json()["status"] == "AWAITING_APPROVAL"
    assert pe.post(f"{API}/deployments/{d['id']}/execute").json()["error"]["code"] == "INVALID_STATE"
    _approve(td, d)

    blocked = pe.post(f"{API}/deployments/{d['id']}/execute").json()["error"]
    assert blocked["code"] == "GATE_BLOCKED"
    text = " ".join(blocked["details"]["errors"])
    assert "checklist: Smoke plan ready" in text and "is in progress" in text
    pe.post(f"{API}/deployments/{d['id']}/checklist", json={"item": "Smoke plan ready", "done": True})
    assert pe.post(f"{API}/test-runs/{run['id']}/close", json={"note": "passed"}).json()["status"] == "CLOSED"
    job = pe.post(f"{API}/deployments/{d['id']}/execute").json()
    assert job["job_id"] and job["status"] == "QUEUED" and job["deployment"]["status"] == "DEPLOYING"
    assert _worker() >= 1
    waiting = pe.get(f"{API}/deployments/{d['id']}").json()
    assert waiting["attempts"][0]["status"] == "WAITING" and waiting["can_report"]
    a1 = waiting["attempts"][0]["id"]
    assert pe.post(f"{API}/deployment-attempts/{a1}/report", json={"outcome": "FAILED"}).json()["error"]["code"] == "REASON_REQUIRED"
    done = pe.post(f"{API}/deployment-attempts/{a1}/report", json={"outcome": "SUCCEEDED", "log": "copied build; password=hunter2"}).json()
    assert done["status"] == "DEPLOYED" and done["attempts"][0]["health"]["ok"]
    assert "hunter2" not in done["attempts"][0]["log"] and "password=****" in done["attempts"][0]["log"], "secrets are masked in logs"

    # a second version fails its health check, is retried as a new attempt, then rolled back
    d2 = _request(pe, project, env, "2.0.1", test_run_id=run["id"])
    pe.post(f"{API}/deployments/{d2['id']}/submit", json={"approvers": [_uid(td)]})
    _approve(td, d2)
    pe.post(f"{API}/deployments/{d2['id']}/checklist", json={"item": "Smoke plan ready", "done": True})
    gates = {g["code"]: g for g in pe.get(f"{API}/deployments/{d2['id']}/gates").json()["gates"]}
    assert not gates["test"]["ok"] and "not 2.0.1" in gates["test"]["detail"], "the test run must have tested this build"
    env_cfg = {**env["config"], "match_test_build": False}
    env = pe.put(f"{API}/deploy-environments/{env['id']}", json={"code": "SIT", "name": "SIT environment", "config": env_cfg}).json()
    assert "configuration" in " ".join(pe.post(f"{API}/deployments/{d2['id']}/execute").json()["error"]["details"]["errors"])
    td.post(f"{API}/deploy-environments/{env['id']}/approve-config")
    gitlab.health_status = 500
    pe.post(f"{API}/deployments/{d2['id']}/execute")
    _worker()
    failed = _manual_success(pe, d2)
    assert failed["status"] == "FAILED" and "Health check failed" in failed["attempts"][0]["failure_reason"]
    gitlab.health_status = 200
    retry = pe.post(f"{API}/deployments/{d2['id']}/execute").json()
    assert retry["attempt_no"] == 2
    _worker()
    ok2 = _manual_success(pe, d2)
    assert ok2["status"] == "DEPLOYED" and [a["status"] for a in ok2["attempts"]] == ["SUCCEEDED", "FAILED"], "retry is a new attempt; history is kept"

    assert pe.post(f"{API}/deployments/{d['id']}/rollback", json={"reason": "old one"}).json()["error"]["code"] in ("INVALID_STATE", "BAD_REQUEST")
    rb = pe.post(f"{API}/deployments/{d2['id']}/rollback", json={"reason": "Field issue in 2.0.1"}).json()
    assert rb["version_label"] == "2.0.0" and rb["rollback_of"]["key"] == d2["key"] and rb["status"] == "PLANNED"
    pe.post(f"{API}/deployments/{rb['id']}/submit", json={"approvers": [_uid(td)]})
    _approve(td, rb)
    pe.post(f"{API}/deployments/{rb['id']}/checklist", json={"item": "Smoke plan ready", "done": True})
    pe.post(f"{API}/deployments/{rb['id']}/execute")
    _worker()
    assert _manual_success(pe, rb)["status"] == "DEPLOYED"
    orig = pe.get(f"{API}/deployments/{d2['id']}").json()
    assert orig["status"] == "ROLLED_BACK" and len(orig["attempts"]) == 2, "the original record is kept, only its status changes"
    ov = {x["environment"]["code"]: x for x in pe.get(f"{API}/projects/{project}/deployment-overview").json()}
    assert ov["SIT"]["current"]["version_label"] == "2.0.0"
    assert client_factory("adm.babu").get(f"{API}/projects/{project}/deployments").status_code == 403


def test_gitlab_pipeline_adapter_and_version_gate(pe, td, project, gitlab):
    repos = pe.get(f"{API}/projects/{project}/repositories").json()["items"]
    repo = repos[0] if repos else pe.post(f"{API}/projects/{project}/repositories", json={"path": "product-alpha/cpu-software"}).json()
    sha = "f" * 40
    gitlab.tags["42"]["v2.1.0"] = sha
    env = _env(pe, td, project, "CI", {"requires_approval": False, "require_test_run": False, "blocking_defect_severities": [], "require_commit": True,
                                       "adapter": "gitlab_pipeline", "adapter_config": {"repository_id": repo["id"], "variables": {"TARGET": "ci"}}})
    wrong = _request(pe, project, env, "2.1.0", repository_id=repo["id"], git_ref="v2.1.0", commit_sha="e" * 40)
    pe.post(f"{API}/deployments/{wrong['id']}/submit", json={})
    g = {x["code"]: x for x in pe.get(f"{API}/deployments/{wrong['id']}/gates").json()["gates"]}
    assert not g["version"]["ok"] and "not the approved eeeeeeeeeeee" in g["version"]["detail"]
    pe.post(f"{API}/deployments/{wrong['id']}/cancel", json={"reason": "wrong commit"})
    d = _request(pe, project, env, "2.1.0", repository_id=repo["id"], git_ref="v2.1.0", commit_sha=sha)
    assert pe.post(f"{API}/deployments/{d['id']}/submit", json={}).json()["status"] == "APPROVED", "no approval needed for CI"
    pe.post(f"{API}/deployments/{d['id']}/execute")
    _worker()
    att = pe.get(f"{API}/deployments/{d['id']}").json()["attempts"][0]
    assert att["status"] == "WAITING" and att["external_ref"]
    pl = gitlab.pipelines[int(att["external_ref"])]
    assert pl["ref"] == "v2.1.0" and pl["variables"]["ELM_VERSION"] == "2.1.0" and pl["variables"]["TARGET"] == "ci"
    assert _worker() == 0, "still running"
    pl["status"] = "success"
    _worker()
    assert pe.get(f"{API}/deployments/{d['id']}").json()["status"] == "DEPLOYED"


def test_script_adapter_secrets_and_masking(pe, td, project, gitlab, tmp_path):
    (tmp_path / "deploy_ok.py").write_text(textwrap.dedent("""
        import os, sys
        print("deploying", sys.argv[1], sys.argv[2])
        print("using key", os.environ["ELM_DEPLOY_SECRET_SIT_KEY"])
    """))
    (tmp_path / "deploy_bad.py").write_text("import sys\nprint('disk full')\nsys.exit(3)\n")
    get_settings().deploy_scripts_dir = str(tmp_path)
    env = _env(pe, td, project, "SCR", {"requires_approval": False, "require_test_run": False, "blocking_defect_severities": [], "secrets": ["SIT_KEY"], "adapter": "script", "adapter_config": {"script": "deploy_ok.py"}})
    d = _request(pe, project, env, "3.0.0")
    pe.post(f"{API}/deployments/{d['id']}/submit", json={})
    os.environ.pop("ELM_DEPLOY_SECRET_SIT_KEY", None)
    err = pe.post(f"{API}/deployments/{d['id']}/execute").json()["error"]
    assert "ELM_DEPLOY_SECRET_SIT_KEY is not set" in " ".join(err["details"]["errors"])
    os.environ["ELM_DEPLOY_SECRET_SIT_KEY"] = "s3cr3t-value-123"
    try:
        pe.post(f"{API}/deployments/{d['id']}/execute")
        _worker()
        out = pe.get(f"{API}/deployments/{d['id']}").json()
        assert out["status"] == "DEPLOYED", out["attempts"][0]
        log = out["attempts"][0]["log"]
        assert "deploying SCR 3.0.0" in log and "s3cr3t-value-123" not in log and "****" in log
        env2 = pe.put(f"{API}/deploy-environments/{env['id']}", json={"code": "SCR", "name": "SCR", "config": {**env["config"], "adapter_config": {"script": "deploy_bad.py"}}}).json()
        td.post(f"{API}/deploy-environments/{env2['id']}/approve-config")
        d2 = _request(pe, project, env, "3.0.1")
        pe.post(f"{API}/deployments/{d2['id']}/submit", json={})
        pe.post(f"{API}/deployments/{d2['id']}/execute")
        _worker()
        bad = pe.get(f"{API}/deployments/{d2['id']}").json()
        assert bad["status"] == "FAILED" and "exited with code 3" in bad["attempts"][0]["failure_reason"]
        env3 = pe.put(f"{API}/deploy-environments/{env['id']}", json={"code": "SCR", "name": "SCR", "config": {**env["config"], "adapter_config": {"script": "../etc/passwd"}}})
        assert env3.json()["error"]["code"] == "CONFIG_INVALID", "no paths outside the script folder"
    finally:
        os.environ.pop("ELM_DEPLOY_SECRET_SIT_KEY", None)
    assert sys.executable


def test_change_window_callback_and_cancel(pe, td, project, gitlab, client_factory):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tomorrow = (datetime.now(ZoneInfo(get_settings().timezone)).weekday() + 1) % 7
    env = _env(pe, td, project, "WIN", {"requires_approval": False, "require_test_run": False, "blocking_defect_severities": [], "change_window": {"days": [tomorrow], "start": "00:00", "end": "23:59"}})
    d = _request(pe, project, env, "4.0.0")
    pe.post(f"{API}/deployments/{d['id']}/submit", json={})
    g = {x["code"]: x for x in pe.get(f"{API}/deployments/{d['id']}/gates").json()["gates"]}
    assert not g["window"]["ok"] and "outside the change window" in g["window"]["detail"]
    assert pe.post(f"{API}/deployments/{d['id']}/cancel", json={"reason": "postponed"}).json()["status"] == "CANCELLED"
    assert pe.post(f"{API}/deployments/{d['id']}/execute").json()["error"]["code"] == "INVALID_STATE"

    open_env = _env(pe, td, project, "CB", {"requires_approval": False, "require_test_run": False, "blocking_defect_severities": []})
    d2 = _request(pe, project, open_env, "4.0.1")
    pe.post(f"{API}/deployments/{d2['id']}/submit", json={})
    job = pe.post(f"{API}/deployments/{d2['id']}/execute").json()
    _worker()
    body = json.dumps({"attempt_id": job["job_id"], "status": "success", "log": "pipeline ok token=abcd1234"}).encode()
    anon = client_factory()
    assert anon.post(f"{API}/deployments/callback", content=body, headers={"X-ELM-Signature": "sha256=00", "Content-Type": "application/json"}).status_code == 401
    sig = "sha256=" + hmac.new(b"cb-secret", body, hashlib.sha256).hexdigest()
    ok = anon.post(f"{API}/deployments/callback", content=body, headers={"X-ELM-Signature": sig, "Content-Type": "application/json"})
    assert ok.status_code == 200 and ok.json()["status"] == "SUCCEEDED"
    det = pe.get(f"{API}/deployments/{d2['id']}").json()
    assert det["status"] == "DEPLOYED" and "abcd1234" not in det["attempts"][0]["log"]
    kinds = {h["kind"] for h in det["history"]}
    assert "STATUS" in kinds and "CREATED" in kinds
