"""Architecture §12: development lifecycle and GitLab integration (allow-listed repositories, task branches, merge
requests, webhook traceability, lifecycle automation through the system actor, completion gate, failure handling)."""
from __future__ import annotations

import json
import uuid

import pytest

from app.core.config import get_settings
from tests.fake_gitlab import TOKEN, FakeGitLab

API = "/api/v1"
SECRET = "hook-secret-for-tests"


@pytest.fixture(scope="module")
def gitlab():
    fake = FakeGitLab()
    s = get_settings()
    saved = (s.gitlab_enabled, s.gitlab_url, s.gitlab_token, s.gitlab_webhook_secret)
    s.gitlab_enabled, s.gitlab_url, s.gitlab_token, s.gitlab_webhook_secret = True, fake.url, TOKEN, SECRET
    yield fake
    s.gitlab_enabled, s.gitlab_url, s.gitlab_token, s.gitlab_webhook_secret = saved
    fake.stop()


@pytest.fixture(scope="module")
def pe(client_factory):
    return client_factory("pe.kumar")


@pytest.fixture(scope="module")
def project(pe):
    return next(p for p in pe.get(f"{API}/projects").json() if p["code"] == "ALPHA")["id"]


@pytest.fixture(scope="module")
def repo(pe, project, gitlab):
    existing = pe.get(f"{API}/projects/{project}/repositories").json()["items"]
    if existing:
        return existing[0]
    r = pe.post(f"{API}/projects/{project}/repositories", json={"path": "product-alpha/cpu-software"})
    assert r.status_code == 200, r.text
    return r.json()


def _uid(c):
    return c.get(f"{API}/auth/me").json()["user"]["id"]


def _dev_task(pe, project, title="Implement channel health monitor"):
    r = pe.post(f"{API}/work-items", json={"title": title, "project_id": project, "kind": "DEVELOPMENT", "assignee_id": _uid(pe)})
    assert r.status_code == 200, r.text
    return r.json()


def _go(c, wid, to, comment=None):
    return c.post(f"{API}/work-items/{wid}/transition", json={"to": to, "comment": comment})


def _hook(client, event, payload, token=SECRET, delivery=None):
    return client.post(f"{API}/scm/gitlab/webhook", content=json.dumps(payload), headers={"X-Gitlab-Token": token, "X-Gitlab-Event": event, "X-Gitlab-Event-UUID": delivery or str(uuid.uuid4()), "Content-Type": "application/json"})


def test_status_and_registration_needs_permission(pe, project, gitlab, client_factory):
    st = pe.get(f"{API}/scm/status", params={"check": True}).json()
    assert st["enabled"] and st["reachable"] and st["version"] == "17.5.0-fake"
    assert "token" not in json.dumps(st).lower().replace("webhook_secret_set", "")
    eng = client_factory("eng.priya")
    r = eng.post(f"{API}/projects/{project}/repositories", json={"path": "product-alpha/cpu-software"})
    assert r.status_code == 403 and r.json()["error"]["details"]["permission"] == "scm.manage"
    missing = pe.post(f"{API}/projects/{project}/repositories", json={"path": "nobody/nothing"})
    assert missing.status_code == 502 and missing.json()["error"]["code"] == "GITLAB_ERROR"


def test_development_lifecycle_branch_and_merge_request(pe, project, repo, gitlab, client_factory):
    assert repo["external_id"] == "42" and repo["default_branch"] == "main"
    dup = pe.post(f"{API}/projects/{project}/repositories", json={"path": "42"})
    assert dup.status_code == 400 and dup.json()["error"]["code"] == "DUPLICATE"
    t = _dev_task(pe, project)
    assert t["status"] == "OPEN" and t["kind"] == "DEVELOPMENT"
    detail = pe.get(f"{API}/work-items/{t['id']}").json()
    assert {s["code"] for s in detail["lifecycle"]["states"]} >= {"CODE_REVIEW", "APPROVED", "MERGED", "TESTING"}
    assert _go(pe, t["id"], "IN_PROGRESS").status_code == 200

    bad = pe.post(f"{API}/work-items/{t['id']}/scm/branch", json={"repository_id": repo["id"], "name": "feature/no-key"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_BRANCH"
    b = pe.post(f"{API}/work-items/{t['id']}/scm/branch", json={"repository_id": repo["id"]})
    assert b.status_code == 200, b.text
    branch = b.json()["ref"]
    assert branch.startswith(f"task/{t['key']}-") and branch in gitlab.branches["42"]

    mr = pe.post(f"{API}/work-items/{t['id']}/scm/merge-request", json={"repository_id": repo["id"]})
    assert mr.status_code == 200, mr.text
    assert mr.json()["state"] == "opened" and mr.json()["title"].startswith(t["key"])
    after = pe.get(f"{API}/work-items/{t['id']}").json()
    assert after["status"] == "CODE_REVIEW", "opening the MR moves the task into code review (system actor)"
    assert any(h["kind"] == "SCM" for h in after["history"])
    view = pe.get(f"{API}/work-items/{t['id']}/scm").json()
    assert {x["kind"] for x in view["links"]} == {"BRANCH", "MERGE_REQUEST"}
    assert "No linked merge request has been merged yet." in view["blockers"]
    assert any(o["operation"] == "create_merge_request" and o["status"] == "SUCCEEDED" for o in view["operations"])

    # A merge seen in GitLab before the ELM code-review approval does not skip the approval.
    iid = int(mr.json()["ref"])
    payload = {"object_kind": "merge_request", "project": {"id": 42}, "user": {"username": "rakesh"},
               "object_attributes": {"iid": iid, "title": mr.json()["title"], "description": "", "state": "merged", "action": "merge", "source_branch": branch, "target_branch": "main", "url": "http://gitlab.local/x"}}
    assert _hook(pe, "Merge Request Hook", payload, token="wrong").status_code == 401
    r = _hook(client_factory(), "Merge Request Hook", payload, delivery="delivery-1")
    assert r.status_code == 200 and r.json()["status"] == "PROCESSED"
    assert pe.get(f"{API}/work-items/{t['id']}").json()["status"] == "CODE_REVIEW"
    assert _hook(client_factory(), "Merge Request Hook", payload, delivery="delivery-1").json()["status"] == "DUPLICATE"

    # Code review in ELM: the named reviewer approves; then the (already merged) MR moves the task on at the next event.
    rev = client_factory("rev.joshi")
    assert pe.put(f"{API}/work-items/{t['id']}/participants", json={"contributors": [], "reviewers": [_uid(rev)]}).status_code == 200
    assert _go(rev, t["id"], "APPROVED").status_code == 200
    assert _hook(client_factory(), "Merge Request Hook", payload).status_code == 200
    assert pe.get(f"{API}/work-items/{t['id']}").json()["status"] == "MERGED"
    assert _go(pe, t["id"], "TESTING").status_code == 200
    assert pe.get(f"{API}/work-items/{t['id']}/scm").json()["blockers"] == []
    assert _go(rev, t["id"], "COMPLETED").status_code == 200


def test_push_webhook_links_commits_by_task_key(pe, project, repo, gitlab, client_factory):
    t = _dev_task(pe, project, "Add watchdog self-test")
    sha = "b" * 40
    payload = {"object_kind": "push", "project_id": 42, "project": {"id": 42}, "ref": "refs/heads/main", "after": sha,
               "commits": [{"id": sha, "message": f"{t['key']} add watchdog self-test\n\nDetails", "timestamp": "2026-11-05T12:00:00+05:30", "url": "http://gitlab.local/c", "author": {"name": "Rakesh Gupta"}},
                           {"id": "c" * 40, "message": "Unrelated change", "timestamp": "2026-11-05T12:01:00+05:30", "author": {"name": "Someone"}}]}
    r = _hook(client_factory(), "Push Hook", payload)
    assert r.status_code == 200 and r.json()["links_created"] == 1
    links = pe.get(f"{API}/work-items/{t['id']}/scm").json()["links"]
    assert [(x["kind"], x["ref"], x["origin"]) for x in links] == [("COMMIT", sha, "WEBHOOK")]
    other = _hook(client_factory(), "Push Hook", {**payload, "project": {"id": 999}, "project_id": 999})
    assert other.json()["status"] == "IGNORED", "pushes to repositories ELM does not know are ignored"
    # webhook-confirmed links cannot be removed by hand
    assert pe.delete(f"{API}/work-items/{t['id']}/scm/links/{links[0]['id']}").json()["error"]["code"] == "IMMUTABLE"


def test_sync_finds_branches_mrs_and_commits(pe, project, repo, gitlab):
    t = _dev_task(pe, project, "Tune scheduler")
    name = f"feature/{t['key']}-tune"
    gitlab.branches["42"][name] = {"name": name, "default": False, "commit": {"id": "d" * 40}}
    gitlab.add_commit(name, "d" * 40, f"{t['key']}: tune scheduler")
    gitlab.mrs["42"].append({"iid": 90, "title": f"{t['key']} tune", "state": "opened", "source_branch": name, "target_branch": "main", "web_url": "http://gitlab.local/mr/90", "author": {"username": "rakesh"}})
    counts = pe.post(f"{API}/work-items/{t['id']}/scm/sync").json()
    assert counts == {"branches": 1, "merge_requests": 1, "commits": 1, "repositories": 1}
    again = pe.post(f"{API}/work-items/{t['id']}/scm/sync").json()
    assert again["branches"] == again["merge_requests"] == again["commits"] == 0, "sync is idempotent"
    cmp = pe.get(f"{API}/repositories/{repo['id']}/compare", params={"head": name}).json()
    assert cmp["files"] and cmp["commits"]


def test_gitlab_failure_is_clear_and_recorded(pe, project, repo, gitlab):
    t = _dev_task(pe, project, "Failure handling")
    gitlab.down = True
    try:
        r = pe.post(f"{API}/work-items/{t['id']}/scm/branch", json={"repository_id": repo["id"]})
    finally:
        gitlab.down = False
    assert r.status_code == 502 and "503" in r.json()["error"]["message"]
    view = pe.get(f"{API}/work-items/{t['id']}/scm").json()
    assert view["links"] == [], "nothing is linked when GitLab did not confirm"
    assert view["operations"][0]["status"] == "FAILED" and view["operations"][0]["error"]


def test_manual_reference_mode_and_repo_allow_list(pe, project, repo, gitlab, client_factory):
    t = _dev_task(pe, project, "Manual reference")
    r = pe.post(f"{API}/work-items/{t['id']}/scm/links", json={"repository_id": repo["id"], "kind": "COMMIT", "ref": "e" * 12, "title": "Committed from an offline clone"})
    assert r.status_code == 200 and r.json()["origin"] == "MANUAL"
    assert pe.post(f"{API}/work-items/{t['id']}/scm/links", json={"repository_id": repo["id"], "kind": "COMMIT", "ref": "e" * 12}).json()["error"]["code"] == "DUPLICATE"
    assert pe.delete(f"{API}/work-items/{t['id']}/scm/links/{r.json()['id']}").json() == {"ok": True}
    # a task in another project cannot use this project's repository
    adm = client_factory("adm.babu")
    other = adm.post(f"{API}/work-items", json={"title": "Office task with no project"}).json()
    assert adm.post(f"{API}/work-items/{other['id']}/scm/branch", json={"repository_id": repo["id"]}).status_code == 400
    # outsiders cannot see the project's repositories
    assert adm.get(f"{API}/projects/{project}/repositories").status_code == 403


def test_kind_lifecycles_are_separate(pe, project):
    dev = pe.get(f"{API}/task-lifecycle", params={"kind": "DEVELOPMENT"}).json()
    plain = pe.get(f"{API}/task-lifecycle").json()
    assert "MERGED" in {s["code"] for s in dev["states"]} and "MERGED" not in {s["code"] for s in plain["states"]}
    t = pe.post(f"{API}/work-items", json={"title": "Plain task", "project_id": project}).json()
    body = {"title": t["title"], "project_id": project, "kind": "DEVELOPMENT"}
    assert pe.put(f"{API}/work-items/{t['id']}", json=body).status_code == 200, "OPEN exists in both lifecycles"
