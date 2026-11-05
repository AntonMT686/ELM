"""Architecture §10 and acceptance scenario D: lifecycle, hash-bound review, separation of duties, baselines, impact, RTM, CSV."""
from __future__ import annotations

import pytest

API = "/api/v1"
GOOD = {"description": "Full text", "acceptance_criteria": "Test passes", "req_type": "FUNCTIONAL", "priority": "HIGH"}


@pytest.fixture()
def pe(client_factory):
    return client_factory("pe.kumar")


def _amca(c):
    return next(p for p in c.get(f"{API}/projects").json() if p["code"] == "AMCA")["id"]


def _source(c, project, name="Test SRS", prefix="TST"):
    existing = [s for s in c.get(f"{API}/projects/{project}/requirement-sources").json() if s["name"] == name]
    if existing:
        return existing[0]["id"]
    r = c.post(f"{API}/projects/{project}/requirement-sources", json={"name": name, "key_prefix": prefix})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _new(c, project, title="The system shall do a thing", **kw):
    r = c.post(f"{API}/projects/{project}/requirements", json={"title": title, "source_id": _source(c, project), **GOOD, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _uid(c, username):
    return c.get(f"{API}/users", params={"q": username}).json()[0]["id"]


def _go(c, rid, to, **kw):
    return c.post(f"{API}/requirements/{rid}/transition", json={"to": to, **kw})


def _submit(c, rid, reviewers=(), approvers=()):
    assert _go(c, rid, "UNDER_ANALYSIS").status_code == 200
    r = _go(c, rid, "UNDER_REVIEW", reviewers=list(reviewers), approvers=list(approvers))
    assert r.status_code == 200, r.text
    return r.json()


def _decide(c, rid, decision="APPROVED", comment=None):
    return c.post(f"{API}/requirements/{rid}/decision", json={"decision": decision, "comment": comment})


def _approved(pe, client_factory, project, **kw):
    td = client_factory("td.menon")
    r = _new(pe, project, **kw)
    _submit(pe, r["id"], approvers=[_uid(pe, "td.menon")])
    assert _decide(td, r["id"]).json()["status"] == "APPROVED"
    return r


def test_ids_use_the_configured_prefix_and_seeded_data_exists(pe):
    project = _amca(pe)
    src = pe.post(f"{API}/projects/{project}/requirement-sources", json={"name": "Prefix check", "key_prefix": "PFX"}).json()["id"]
    a = pe.post(f"{API}/projects/{project}/requirements", json={"title": "First requirement", "source_id": src}).json()
    b = pe.post(f"{API}/projects/{project}/requirements", json={"title": "Second requirement", "source_id": src}).json()
    assert a["key"] == "PFX-0001" and b["key"] == "PFX-0002"
    assert a["status"] == "DRAFT" and a["revision"] == 1 and len(a["content_sha256"]) == 64
    listing = pe.get(f"{API}/projects/{project}/requirements", params={"q": "triplex"}).json()["items"]
    assert listing[0]["status"] == "BASELINED"


def test_lifecycle_rejects_illegal_moves_and_requires_fields_and_reason(pe):
    project = _amca(pe)
    r = pe.post(f"{API}/projects/{project}/requirements", json={"title": "Thin requirement"}).json()
    assert _go(pe, r["id"], "APPROVED").json()["error"]["code"] == "INVALID_TRANSITION"
    assert _go(pe, r["id"], "BASELINED").json()["error"]["code"] == "INVALID_TRANSITION"
    assert _go(pe, r["id"], "NOPE").json()["error"]["code"] == "INVALID_STATE"
    assert _go(pe, r["id"], "DEFERRED").json()["error"]["code"] == "REASON_REQUIRED"
    assert _go(pe, r["id"], "DEFERRED", comment="Next phase").status_code == 200
    assert _go(pe, r["id"], "DRAFT").status_code == 200
    d = _go(pe, r["id"], "UNDER_ANALYSIS").json()
    assert d["submit_blockers"]
    res = _go(pe, r["id"], "UNDER_REVIEW", approvers=[_uid(pe, "td.menon")])
    assert res.status_code == 400 and res.json()["error"]["code"] == "GATE_BLOCKED"
    assert "acceptance criteria" in res.text


def test_review_is_sequential_bound_to_hash_and_keeps_separation_of_duties(pe, client_factory):
    project = _amca(pe)
    joshi = client_factory("rev.joshi")
    td = client_factory("td.menon")
    r = _new(pe, project)
    _go(pe, r["id"], "UNDER_ANALYSIS")
    me = pe.get(f"{API}/auth/me").json()["user"]["id"]
    res = _go(pe, r["id"], "UNDER_REVIEW", approvers=[me])
    assert res.status_code == 400 and "owner or submitter" in res.text
    assert _go(pe, r["id"], "UNDER_REVIEW", reviewers=[_uid(pe, "rev.joshi")]).json()["error"]["code"] == "GATE_BLOCKED"
    d = _go(pe, r["id"], "UNDER_REVIEW", reviewers=[_uid(pe, "rev.joshi")], approvers=[_uid(pe, "td.menon")]).json()
    assert d["status"] == "UNDER_REVIEW"
    assert all(x["content_sha256"] == d["content_sha256"] and x["revision"] == 1 for x in d["reviews"])
    # locked while under review
    body = {"title": "Sneaky edit under review", "source_id": _source(pe, project), **GOOD}
    assert pe.put(f"{API}/requirements/{r['id']}", json=body).json()["error"]["code"] == "LOCKED"
    # approver waits for reviewers; outsiders have no vote
    assert _decide(td, r["id"]).json()["error"]["code"] == "GATE_BLOCKED"
    assert _decide(pe, r["id"]).status_code == 403
    assert _decide(joshi, r["id"], "REJECTED").json()["error"]["code"] == "REASON_REQUIRED"
    assert _decide(joshi, r["id"]).json()["status"] == "UNDER_REVIEW"
    assert _decide(joshi, r["id"]).status_code == 403
    assert _decide(td, r["id"]).json()["status"] == "APPROVED"


def test_rejection_goes_to_rework_and_old_approval_is_not_reused(pe, client_factory):
    """Scenario D: rejected decisions are kept, and a new cycle needs fresh decisions."""
    project = _amca(pe)
    joshi = client_factory("rev.joshi")
    td = client_factory("td.menon")
    r = _new(pe, project)
    _submit(pe, r["id"], reviewers=[_uid(pe, "rev.joshi")], approvers=[_uid(pe, "td.menon")])
    d = _decide(joshi, r["id"], "REJECTED", "Too vague").json()
    assert d["status"] == "REJECTED"
    assert {x["status"] for x in d["reviews"]} == {"REJECTED", "CANCELLED"}
    assert _decide(td, r["id"]).status_code == 400
    assert _go(pe, r["id"], "UNDER_ANALYSIS").status_code == 200
    d = _go(pe, r["id"], "UNDER_REVIEW", approvers=[_uid(pe, "td.menon")]).json()
    assert max(x["cycle"] for x in d["reviews"]) == 2
    assert _decide(td, r["id"]).json()["status"] == "APPROVED"


def test_withdraw_cancels_pending_reviews(pe, client_factory):
    project = _amca(pe)
    r = _new(pe, project)
    _submit(pe, r["id"], approvers=[_uid(pe, "td.menon")])
    assert _go(pe, r["id"], "UNDER_ANALYSIS").json()["error"]["code"] == "REASON_REQUIRED"
    d = _go(pe, r["id"], "UNDER_ANALYSIS", comment="Needs more work").json()
    assert d["reviews"][0]["status"] == "CANCELLED"
    assert _decide(client_factory("td.menon"), r["id"]).status_code == 400


def test_baseline_is_immutable_and_change_opens_a_new_revision(pe, client_factory):
    project = _amca(pe)
    r = _approved(pe, client_factory, project, title="Baseline me please")
    draft = _new(pe, project, title="Still a draft")
    res = pe.post(f"{API}/projects/{project}/requirement-baselines", json={"label": "Mixed", "reason": "Should fail", "requirement_ids": [r["id"], draft["id"]]})
    assert res.status_code == 400 and draft["key"] in res.text
    b = pe.post(f"{API}/projects/{project}/requirement-baselines", json={"label": "Release 1", "reason": "Agreed at review", "requirement_ids": [r["id"]]}).json()
    assert b["items"] == 1 and len(b["sha256"]) == 64
    d = pe.get(f"{API}/requirements/{r['id']}").json()
    assert d["status"] == "BASELINED" and d["baselines"][0]["seq"] == b["seq"]
    # changing it needs a reason, opens revision 2, voids approval, and leaves the baseline untouched
    body = {"title": "Baseline me please, changed", "source_id": d["source"]["id"], **GOOD}
    assert pe.put(f"{API}/requirements/{r['id']}", json=body).json()["error"]["code"] == "REASON_REQUIRED"
    d = pe.put(f"{API}/requirements/{r['id']}", json={**body, "change_reason": "Customer change"}).json()
    assert d["revision"] == 2 and d["status"] == "UNDER_ANALYSIS"
    assert [x["revision"] for x in d["revisions"]] == [2, 1]
    assert d["revisions"][1]["title"] == "Baseline me please"
    snap = pe.get(f"{API}/requirement-baselines/{b['id']}").json()
    assert snap["integrity_ok"] is True and snap["items"][0]["title"] == "Baseline me please" and snap["items"][0]["revision"] == 1
    cmp = pe.get(f"{API}/requirement-baselines/{b['id']}/compare").json()
    assert [x["key"] for x in cmp["changed"]] == [r["key"]] and cmp["changed"][0]["to_revision"] == 2
    # an unchanged edit is not a new revision
    same = pe.put(f"{API}/requirements/{r['id']}", json={**body, "change_reason": None}).json()
    assert same["revision"] == 2


def test_baseline_needs_permission(pe, client_factory):
    project = _amca(pe)
    priya = client_factory("eng.priya")
    assert priya.post(f"{API}/projects/{project}/requirement-baselines", json={"label": "Nope", "reason": "Not allowed"}).status_code == 403


def test_links_impact_and_loops(pe, client_factory):
    project = _amca(pe)
    a = _new(pe, project, title="Top requirement")
    b = _new(pe, project, title="Depends on the top one")
    c = _new(pe, project, title="Child of the second", parent_id=b["id"])
    assert pe.post(f"{API}/requirements/{b['id']}/links", json={"to_id": a["id"], "link_type": "depends_on"}).status_code == 200
    assert pe.post(f"{API}/requirements/{b['id']}/links", json={"to_id": a["id"], "link_type": "nonsense"}).status_code == 400
    assert pe.post(f"{API}/requirements/{b['id']}/links", json={"to_id": a["id"], "link_type": "depends_on"}).status_code == 409
    assert pe.post(f"{API}/requirements/{a['id']}/links", json={"to_id": a["id"], "link_type": "related_to"}).json()["error"]["code"] == "CYCLE"
    assert pe.post(f"{API}/requirements/{a['id']}/links", json={"to_id": b["id"], "link_type": "derived_from"}).json()["error"]["code"] == "CYCLE"
    assert pe.put(f"{API}/requirements/{b['id']}", json={"title": b["title"], "source_id": b["source"]["id"], "parent_id": c["id"], **GOOD}).json()["error"]["code"] == "CYCLE"
    task = pe.post(f"{API}/work-items", json={"title": "Implement the child", "project_id": project}).json()
    assert pe.post(f"{API}/requirements/{c['id']}/tasks", json={"work_item_id": task["id"]}).status_code == 200
    reach = pe.get(f"{API}/requirements/{a['id']}/impact").json()
    assert {x["key"] for x in reach["requirements"]} == {b["key"], c["key"]}
    assert [t["key"] for t in reach["tasks"]] == [task["key"]]
    made = pe.post(f"{API}/requirements/{a['id']}/impact-task").json()
    assert made["items"] == 3
    w = pe.get(f"{API}/work-items/{made['id']}").json()
    assert w["kind"] == "CHANGE_REQUEST" and len(w["checklist"]) == 3
    assert pe.get(f"{API}/requirements/{a['id']}").json()["status"] == "DRAFT", "impact analysis alters nothing"


def test_rtm_reports_real_coverage_and_csv_is_formula_safe(pe):
    project = _amca(pe)
    r = _new(pe, project, title="=CMD() traced requirement")
    data = pe.get(f"{API}/projects/{project}/rtm").json()
    assert data["summary"]["total"] >= 5 and data["summary"]["with_tasks"] >= 1 and data["not_yet_available"]
    assert next(x for x in data["rows"] if x["key"] == r["key"])["tasks"] == []
    text = pe.get(f"{API}/projects/{project}/rtm.csv").text
    assert "'=CMD() traced requirement" in text


def test_scope_isolation(pe, client_factory):
    project = _amca(pe)
    adm = client_factory("adm.babu")
    r = _new(pe, project)
    assert adm.get(f"{API}/projects/{project}/requirements").status_code == 403
    assert adm.get(f"{API}/projects/{project}/rtm").status_code == 403
    assert adm.get(f"{API}/projects/{project}/rtm.csv").status_code == 403
    assert adm.get(f"{API}/requirements/{r['id']}").status_code == 403
    assert adm.get(f"{API}/requirements/{r['id']}/impact").status_code == 403
    assert adm.post(f"{API}/projects/{project}/requirements", json={"title": "Not allowed here"}).status_code == 403
    assert _go(adm, r["id"], "UNDER_ANALYSIS").status_code == 403
    baselines = pe.get(f"{API}/projects/{project}/requirement-baselines").json()
    assert adm.get(f"{API}/requirement-baselines/{baselines[-1]['id']}").status_code == 403


def test_assigned_reviewer_outside_the_project_can_read_and_decide(pe, client_factory):
    project = _amca(pe)
    adm = client_factory("adm.head")
    r = _new(pe, project)
    _submit(pe, r["id"], approvers=[_uid(pe, "adm.head")])
    assert adm.get(f"{API}/requirements/{r['id']}").json()["can_decide"] is True
    assert _decide(adm, r["id"]).json()["status"] == "APPROVED"


def test_csv_import_previews_and_never_overwrites_approved(pe, client_factory):
    project = _amca(pe)
    src = pe.post(f"{API}/projects/{project}/requirement-sources", json={"name": "DOORS export", "source_system": "DOORS", "key_prefix": "DRS"}).json()["id"]

    def send(text, dry=True):
        return pe.post(f"{API}/projects/{project}/requirements/import", files={"file": ("r.csv", text, "text/csv")}, data={"source_id": src, "external_version": "v1"}, params={"dry_run": str(dry).lower()}).json()

    first = "external_id,title,description,acceptance_criteria,type,priority\nD1,Requirement one,Text,AC,FUNCTIONAL,HIGH\nD2,Requirement two,Text,AC,FUNCTIONAL,LOW\nD3,Requirement three,Text,AC,FUNCTIONAL,LOW\n"
    bad = send("external_id,title\nD1,x\nD1,Duplicate here\n")
    assert bad["committed"] is False and len(bad["errors"]) == 2
    assert send("title\nNo id column here\n")["error"]["code"] == "BAD_REQUEST"
    dry = send(first)
    assert dry["dry_run"] is True and len(dry["new"]) == 3
    assert pe.get(f"{API}/projects/{project}/requirements", params={"source_id": src}).json()["items"] == []
    done = send(first, dry=False)
    assert done["committed"] is True
    items = {x["external_id"]: x for x in pe.get(f"{API}/projects/{project}/requirements", params={"source_id": src}).json()["items"]}
    assert items["D1"]["key"].startswith("DRS-")
    # approve D1, then a new export changes D1 and D2 and drops D3
    d1 = items["D1"]["id"]
    _submit(pe, d1, approvers=[_uid(pe, "td.menon")])
    _decide(client_factory("td.menon"), d1)
    second = "external_id,title,description,acceptance_criteria,type,priority\nD1,Requirement one edited,Text,AC,FUNCTIONAL,HIGH\nD2,Requirement two edited,Text,AC,FUNCTIONAL,LOW\nD4,Requirement four,Text,AC,FUNCTIONAL,LOW\n"
    res = send(second, dry=False)
    assert [x["external_id"] for x in res["conflicts"]] == ["D1"]
    assert [x["external_id"] for x in res["changed"]] == ["D2"]
    assert [x["external_id"] for x in res["new"]] == ["D4"]
    assert [x["external_id"] for x in res["removed"]] == ["D3"]
    now = {x["external_id"]: x for x in pe.get(f"{API}/projects/{project}/requirements", params={"source_id": src}).json()["items"]}
    assert now["D1"]["title"] == "Requirement one" and now["D1"]["status"] == "APPROVED"
    assert now["D2"]["title"] == "Requirement two edited" and "D3" in now, "removed records are reported, not deleted"


def test_lifecycle_config_is_validated(client_factory):
    proc = client_factory("proc.krishnan")
    pe = client_factory("pe.kumar")
    base = proc.get(f"{API}/requirement-lifecycle").json()
    good = {"states": base["states"], "transitions": base["transitions"]}
    assert pe.put(f"{API}/requirement-lifecycle", json=good).status_code == 403
    no_core = {"states": [s for s in base["states"] if s["code"] != "APPROVED"], "transitions": [t for t in base["transitions"] if "APPROVED" not in (t["from"], t["to"])]}
    r = proc.put(f"{API}/requirement-lifecycle", json=no_core)
    assert r.status_code == 400 and "required" in r.text
    assert proc.put(f"{API}/requirement-lifecycle", json={**good, "mandatory_fields": ["bogus"]}).status_code == 400
    assert proc.put(f"{API}/requirement-lifecycle", json={**good, "mandatory_fields": base["mandatory_fields"]}).status_code == 200


def test_task_shows_its_requirements(pe):
    project = _amca(pe)
    r = _new(pe, project, title="Shown on the task")
    t = pe.post(f"{API}/work-items", json={"title": "Task with a requirement", "project_id": project}).json()
    pe.post(f"{API}/requirements/{r['id']}/tasks", json={"work_item_id": t["id"]})
    assert pe.get(f"{API}/work-items/{t['id']}").json()["requirements"][0]["key"] == r["key"]


def test_ids_sort_as_numbers():
    from app.services.requirements import natural_key

    keys = ["REQ10", "REQ2", "REQ1.10", "REQ1.2", "REQ1", "REQ9~78"]
    assert sorted(keys, key=natural_key) == ["REQ1", "REQ1.2", "REQ1.10", "REQ2", "REQ9~78", "REQ10"]
