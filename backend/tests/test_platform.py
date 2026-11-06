"""End-to-end API tests: auth, scope isolation, workflow (SoD, hash binding), signatures, release, audit chain."""
import json


def _doc_by_title(c, text):
    r = c.get("/api/v1/documents", params={"q": text, "page_size": 50})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    return items[0] if items else None


def test_login_and_me(client_factory):
    anon = client_factory()
    assert anon.get("/api/v1/auth/me").status_code == 401
    bad = anon.post("/api/v1/auth/login", json={"username": "pe.kumar", "password": "wrong"})
    assert bad.status_code == 401 and "Invalid username or password" in bad.text
    c = client_factory("pe.kumar")
    me = c.get("/api/v1/auth/me").json()
    assert me["user"]["username"] == "pe.kumar"
    assert "doc.create" in me["permissions"]
    assert any(p["code"] == "ALPHA" for p in me["projects"])


def test_csrf_required(client_factory):
    c = client_factory("pe.kumar")
    c.headers.pop("X-CSRF-Token")
    r = c.post("/api/v1/auth/logout")
    assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF"


def test_seeded_release_and_signatures(client_factory):
    c = client_factory("cm.sharma")
    reg = c.get("/api/v1/release-register").json()
    assert reg["total"] >= 2  # CPU spec + auto-released office order
    cpu = _doc_by_title(c, "Central Processing Unit — Equipment")
    d = c.get(f"/api/v1/documents/{cpu['id']}").json()
    assert d["status"] == "RELEASED"
    assert len(d["signatures"]) == 4
    v = c.get(f"/api/v1/documents/{cpu['id']}/signatures/{d['signatures'][0]['id']}/verify").json()
    assert v["valid"] is True


def test_scope_isolation(client_factory):
    adm = client_factory("adm.babu")
    titles = [x["title"] for x in adm.get("/api/v1/documents", params={"page_size": 100}).json()["items"]]
    assert titles and not any("Processing Unit" in t for t in titles)
    eng = client_factory("pe.kumar")
    cpu = _doc_by_title(eng, "Central Processing Unit — Equipment")
    assert adm.get(f"/api/v1/documents/{cpu['id']}").status_code == 403
    assert adm.get(f"/api/v1/documents/{cpu['id']}/revisions/{cpu['current_revision']['id']}/file").status_code == 403


def test_full_document_lifecycle(client_factory):
    priya = client_factory("eng.priya")
    me = priya.get("/api/v1/auth/me").json()
    types = {t["code"]: t for t in priya.get("/api/v1/document-types").json()}
    tree = priya.get(f"/api/v1/projects/{me['projects'][0]['id']}/tree").json()
    cpu = next(i for i in tree["items"] if i["code"] == "CTL-CPU")
    meta = {"type_id": types["DDD"]["id"], "title": "CPU Software Design Description (test)", "item_id": cpu["id"], "from_template": True}
    r = priya.post("/api/v1/documents", data={"meta": json.dumps(meta)})
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["number"].startswith("ALPHA-CTL-CPU-DDD-")
    assert doc["current_revision"]["iteration"] == 1

    plan = priya.get(f"/api/v1/documents/{doc['id']}/workflow-plan").json()
    assert [s["key"] for s in plan["stages"]] == ["prepare", "check", "review", "approve", "sign"]
    users = {u["username"]: u["id"] for u in client_factory("admin").get("/api/v1/users").json()}

    # SoD: author cannot pick herself as checker (also not eligible: lacks CHECKER role)
    bad = priya.post(f"/api/v1/documents/{doc['id']}/submit", json={"picks": {"check": [users["eng.priya"]], "review": [users["rev.joshi"]], "approve": [users["td.menon"]]}})
    assert bad.status_code in (400, 403)

    picks = {"picks": {"check": [users["chk.das"]], "review": [users["rev.joshi"]], "approve": [users["td.menon"]]}}
    no_list = priya.post(f"/api/v1/documents/{doc['id']}/submit", json=picks)
    assert no_list.json()["error"]["code"] == "CHECKLIST_REQUIRED", "engineering documents need the preparer's checklist"
    assert priya.put(f"/api/v1/documents/{doc['id']}/review-checklist", json={"items": [{"text": "Block diagram included", "guidance": "Section 3"},
                                                                                       {"text": "Interfaces listed", "stages": ["review"]}]}).status_code == 200
    ok = priya.post(f"/api/v1/documents/{doc['id']}/submit", json=picks)
    assert ok.status_code == 200, ok.text
    frozen = priya.put(f"/api/v1/documents/{doc['id']}/review-checklist", json={"items": [{"text": "Changed while in review"}]})
    assert frozen.json()["error"]["code"] == "LOCKED"
    # Locked: cannot upload content while in review
    up = priya.post(f"/api/v1/documents/{doc['id']}/content", files={"file": ("x.docx", b"PK\x03\x04junk", "application/octet-stream")})
    assert up.status_code == 409

    das = client_factory("chk.das")
    task = next(t for t in das.get("/api/v1/inbox").json()["pending"] if t["document"]["id"] == doc["id"])
    mine = task["doc_checklist"]["items"]
    assert [i["text"] for i in mine] == ["Block diagram included"], "the checker answers only the items for the check stage"
    # checklist enforced (fixed workflow checklist and preparer's checklist)
    r = das.post(f"/api/v1/tasks/{task['id']}/decide", json={"decision": "approve"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "CHECKLIST"
    fixed = {c: True for c in task["stage"]["checklist"]}
    r = das.post(f"/api/v1/tasks/{task['id']}/decide", json={"decision": "approve", "checklist": fixed, "item_results": {mine[0]["id"]: {"result": "NOT_OK"}}})
    assert "remark" in " ".join(r.json()["error"]["details"]["errors"])
    r = das.post(f"/api/v1/tasks/{task['id']}/decide", json={"decision": "approve", "checklist": fixed, "item_results": {mine[0]["id"]: {"result": "NOT_OK", "remark": "missing"}}})
    assert "cannot be approved" in " ".join(r.json()["error"]["details"]["errors"]), "a not-OK item leads to request changes"
    # request changes requires comment
    r = das.post(f"/api/v1/tasks/{task['id']}/decide", json={"decision": "request_changes"})
    assert r.json()["error"]["code"] == "COMMENT_REQUIRED"
    r = das.post(f"/api/v1/tasks/{task['id']}/decide", json={"decision": "request_changes", "comment": "Add block diagram", "item_results": {mine[0]["id"]: {"result": "NOT_OK", "remark": "No block diagram in section 3"}}})
    assert r.status_code == 200
    assert priya.get(f"/api/v1/documents/{doc['id']}").json()["status"] == "CHANGES_REQUESTED"
    hist = priya.get(f"/api/v1/documents/{doc['id']}/workflow").json()[0]
    answers = [a for st in hist["stages"] for t in st["tasks"] for a in t["checklist_results"]]
    assert answers == [{**answers[0], "text": "Block diagram included", "result": "NOT_OK", "remark": "No block diagram in section 3"}], "the author sees which item failed and why"

    # rework → new iteration → resubmit (cycle 2)
    from app.services.documents import stamp_template

    data = stamp_template("docx", {"TITLE": "updated"})
    r = priya.post(f"/api/v1/documents/{doc['id']}/content", files={"file": ("ddd.docx", data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert r.status_code == 200, r.text
    assert priya.post(f"/api/v1/documents/{doc['id']}/submit", json={"picks": {"check": [users["chk.das"]], "review": [users["rev.joshi"]], "approve": [users["td.menon"]]}}).status_code == 200
    checklist = {c: True for c in task["stage"]["checklist"]}
    for who in ("chk.das", "rev.joshi", "td.menon"):
        c = client_factory(who)
        t = next(t for t in c.get("/api/v1/inbox").json()["pending"] if t["document"]["id"] == doc["id"])
        answers = {i["id"]: {"result": "OK"} for i in t["doc_checklist"]["items"]}
        r = c.post(f"/api/v1/tasks/{t['id']}/decide", json={"decision": "approve", "comment": "ok", "checklist": checklist, "item_results": answers})
        assert r.status_code == 200, r.text
    # signatures: wrong password rejected
    t = next(t for t in priya.get("/api/v1/inbox").json()["pending"] if t["document"]["id"] == doc["id"])
    assert t["stage"]["type"] == "signature"
    assert priya.post(f"/api/v1/tasks/{t['id']}/sign", json={"password": "nope"}).status_code == 403
    for who in ("eng.priya", "chk.das", "rev.joshi", "td.menon"):
        c = client_factory(who)
        t = next(t for t in c.get("/api/v1/inbox").json()["pending"] if t["document"]["id"] == doc["id"])
        r = c.post(f"/api/v1/tasks/{t['id']}/sign", json={"password": "Elm@12345"})
        assert r.status_code == 200, r.text
    d = priya.get(f"/api/v1/documents/{doc['id']}").json()
    assert d["status"] == "APPROVED"
    # author cannot release; release authority can
    assert priya.post(f"/api/v1/documents/{doc['id']}/release", json={}).status_code == 403
    cm = client_factory("cm.sharma")
    checks = cm.get(f"/api/v1/documents/{doc['id']}/release-checks").json()
    assert all(c["ok"] for c in checks), checks
    r = cm.post(f"/api/v1/documents/{doc['id']}/release", json={"note": "test"})
    assert r.status_code == 200 and r.json()["release_no"].startswith("REL-")
    # revise → rev B draft
    r = priya.post(f"/api/v1/documents/{doc['id']}/revise", json={"change_summary": "Incorporate CDR comments"})
    assert r.status_code == 200 and r.json()["label"] == "B"


def test_audit_chain_intact(client_factory):
    qa = client_factory("qa.verma")
    v = qa.get("/api/v1/audit/verify").json()
    assert v["valid"] is True and v["checked"] > 10
    assert client_factory("eng.priya").get("/api/v1/audit/verify").status_code == 403


def test_dashboard_and_tree(client_factory):
    c = client_factory("pgd.rao")
    d = c.get("/api/v1/dashboard").json()
    assert d["kpis"]["total_docs"] > 5 and d["projects"]
    me = c.get("/api/v1/auth/me").json()
    assert me["perspective"] == "OVERSIGHT"
    alpha = next(p for p in me["projects"] if p["code"] == "ALPHA")
    tree = c.get(f"/api/v1/projects/{alpha['id']}/tree").json()
    root = next(i for i in tree["items"] if i["parent_id"] is None)
    assert root["rollup"]["total"] >= 8


def test_onlyoffice_config_and_callback_guard(client_factory):
    c = client_factory("eng.priya")
    doc = _doc_by_title(c, "Hardware Design Description")
    rid = doc["current_revision"]["id"]
    cfg = c.get(f"/api/v1/onlyoffice/config/{rid}").json()
    assert cfg["config"]["editorConfig"]["mode"] in ("edit", "view") and "token" in cfg["config"]
    anon = client_factory()
    r = anon.post(f"/api/v1/onlyoffice/callback/{rid}?t=bogus", json={"status": 2, "url": "http://evil/x"})
    assert r.status_code == 403
