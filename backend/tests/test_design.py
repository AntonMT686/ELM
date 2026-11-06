"""Architecture §11: design records, immutable versions, optimistic diagram saves, controlled restore, hash-bound
review with separation of duties, baseline, reason-required change after baseline, links, PDF report, access."""
from __future__ import annotations

import pytest

API = "/api/v1"
XML = '<mxfile><diagram id="x"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel></diagram></mxfile>'
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'


@pytest.fixture(scope="module")
def pe(client_factory):
    return client_factory("pe.kumar")


@pytest.fixture(scope="module")
def project(pe):
    return next(p for p in pe.get(f"{API}/projects").json() if p["code"] == "ALPHA")["id"]


@pytest.fixture(scope="module")
def types(pe):
    return {t["code"]: t for t in pe.get(f"{API}/design-types").json()}


def _uid(c):
    return c.get(f"{API}/auth/me").json()["user"]["id"]


def _new(pe, project, types, title="Health monitor sequence", code="SEQUENCE", **kw):
    r = pe.post(f"{API}/projects/{project}/designs", json={"type_id": types[code]["id"], "title": title, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_seeded_design_and_types(pe, project, types):
    assert {"ARCH", "SEQUENCE", "INTERFACE", "DRAWING", "CALC"} <= set(types)
    rows = pe.get(f"{API}/projects/{project}/designs").json()["items"]
    seeded = next(d for d in rows if d["key"] == "ALPHA-DES-0001")
    det = pe.get(f"{API}/designs/{seeded['id']}").json()
    assert det["versions"][0]["kind"] == "DIAGRAM" and det["versions"][0]["preview"]["extension"] == "svg"
    assert any(x["target"]["key"] == "ALPHA-CPU-0001" and x["section"] for x in det["links"])
    svg = pe.get(f"{API}/designs/{seeded['id']}/versions/1/preview")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml") and "default-src 'none'" in svg.headers["content-security-policy"]


def test_required_widget_fields(pe, project, types):
    r = pe.post(f"{API}/projects/{project}/designs", json={"type_id": types["INTERFACE"]["id"], "title": "CPU to drive unit interface"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "FIELD_REQUIRED"
    ok = _new(pe, project, types, "CPU to drive unit interface", "INTERFACE", attributes={"interface_id": "IF-001"})
    assert ok["attributes"]["interface_id"] == "IF-001" and ok["key"].startswith("ALPHA-DES-")


def test_full_design_lifecycle(pe, project, types, client_factory):
    d = _new(pe, project, types)
    assert d["status"] == "DRAFT" and d["current_version"] == 0
    did = d["id"]
    assert pe.post(f"{API}/designs/{did}/diagram", json={"xml": XML, "svg": SVG.replace("<rect", "<script>alert(1)</script><rect"), "base_version": 0}).json()["error"]["code"] == "FILE_SIGNATURE"
    assert pe.post(f"{API}/designs/{did}/diagram", json={"xml": '<!DOCTYPE x [<!ENTITY a "b">]><mxfile/>', "base_version": 0}).json()["error"]["code"] == "FILE_SIGNATURE"
    v1 = pe.post(f"{API}/designs/{did}/diagram", json={"xml": XML, "svg": SVG, "base_version": 0, "note": "first"}).json()
    assert v1["status"] == "IN_PROGRESS" and v1["current_version"] == 1
    stale = pe.post(f"{API}/designs/{did}/diagram", json={"xml": XML.replace('id="x"', 'id="y"'), "base_version": 0})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "VERSION_CONFLICT", "a save based on an old version is refused, the newer one stays"
    assert pe.get(f"{API}/designs/{did}").json()["current_version"] == 1

    joshi, td, priya = client_factory("rev.joshi"), client_factory("td.menon"), client_factory("eng.priya")
    own = pe.post(f"{API}/designs/{did}/submit", json={"approvers": [_uid(pe)]})
    assert own.status_code == 403 and own.json()["error"]["code"] == "SOD_VIOLATION"
    sub = pe.post(f"{API}/designs/{did}/submit", json={"reviewers": [_uid(joshi)], "approvers": [_uid(td)]})
    assert sub.status_code == 200 and sub.json()["status"] == "SUBMITTED"
    assert pe.post(f"{API}/designs/{did}/diagram", json={"xml": XML + " ", "base_version": 1}).json()["error"]["code"] == "LOCKED"

    rev = {r["role"]: r for r in td.get(f"{API}/designs/{did}").json()["reviews"]}
    early = td.post(f"{API}/designs/{did}/reviews/{rev['APPROVER']['id']}/decide", json={"decision": "approve"})
    assert early.json()["error"]["code"] == "NOT_YET", "approvers wait for reviewers"
    assert joshi.post(f"{API}/designs/{did}/reviews/{rev['REVIEWER']['id']}/decide", json={"decision": "approve", "comment": "ok"}).json()["status"] == "UNDER_REVIEW"
    approved = td.post(f"{API}/designs/{did}/reviews/{rev['APPROVER']['id']}/decide", json={"decision": "approve"}).json()
    assert approved["status"] == "APPROVED"

    no = priya.post(f"{API}/designs/{did}/baseline", json={"reason": "CDR"})
    assert no.status_code == 403 and no.json()["error"]["details"]["permission"] == "design.baseline"
    base = pe.post(f"{API}/designs/{did}/baseline", json={"reason": "Agreed at CDR"}).json()
    assert base["status"] == "BASELINED" and base["baselined_version"] == 1 and base["baseline_sha256"] == base["versions"][0]["sha256"]

    need = pe.post(f"{API}/designs/{did}/diagram", json={"xml": XML.replace('id="x"', 'id="z"'), "base_version": 1})
    assert need.json()["error"]["code"] == "REASON_REQUIRED"
    v2 = pe.post(f"{API}/designs/{did}/diagram", json={"xml": XML.replace('id="x"', 'id="z"'), "base_version": 1, "reason": "ECR-12 adds a watchdog"}).json()
    assert v2["status"] == "IN_PROGRESS" and v2["current_version"] == 2 and v2["baselined_version"] == 1, "the baseline is not moved by later edits"

    restored = pe.post(f"{API}/designs/{did}/versions/1/restore", json={"reason": "ECR-12 withdrawn"}).json()
    assert restored["current_version"] == 3 and restored["versions"][0]["restored_from"] == 1 and restored["versions"][0]["sha256"] == restored["versions"][2]["sha256"]
    assert len(restored["versions"]) == 3, "restore never deletes"

    req = next(r for r in pe.get(f"{API}/projects/{project}/requirements").json()["items"] if r["key"] == "ALPHA-CPU-0002")
    linked = pe.post(f"{API}/designs/{did}/links", json={"to_type": "REQUIREMENT", "to_id": req["id"], "link_type": "satisfies", "section": "4.2 Detection"}).json()
    assert any(x["target"]["key"] == "ALPHA-CPU-0002" for x in linked["links"])
    assert pe.post(f"{API}/designs/{did}/links", json={"to_type": "REQUIREMENT", "to_id": req["id"], "link_type": "satisfies"}).json()["error"]["code"] == "DUPLICATE"
    pdf = pe.get(f"{API}/designs/{did}/report.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    kinds = [h["kind"] for h in pe.get(f"{API}/designs/{did}").json()["history"]]
    assert {"CREATED", "VERSION", "STATUS", "DECISION", "RESTORE", "LINK"} <= set(kinds)


def test_changes_requested_cycle_and_stale_review(pe, project, types, client_factory):
    d = _new(pe, project, types, "Data flow")
    did = d["id"]
    pe.post(f"{API}/designs/{did}/diagram", json={"xml": XML, "base_version": 0})
    td = client_factory("td.menon")
    pe.post(f"{API}/designs/{did}/submit", json={"approvers": [_uid(td)]})
    rid = td.get(f"{API}/designs/{did}").json()["reviews"][0]["id"]
    assert td.post(f"{API}/designs/{did}/reviews/{rid}/decide", json={"decision": "request_changes"}).json()["error"]["code"] == "REASON_REQUIRED"
    assert td.post(f"{API}/designs/{did}/reviews/{rid}/decide", json={"decision": "request_changes", "comment": "Add the error path"}).json()["status"] == "CHANGES_REQUESTED"
    assert pe.post(f"{API}/designs/{did}/submit", json={"approvers": [_uid(td)]}).json()["error"]["code"] == "INVALID_STATE", "a new version is needed first"
    v2 = pe.post(f"{API}/designs/{did}/diagram", json={"xml": XML.replace('id="x"', 'id="e"'), "base_version": 1}).json()
    assert v2["status"] == "IN_PROGRESS"
    again = pe.post(f"{API}/designs/{did}/submit", json={"approvers": [_uid(td)]}).json()
    assert {r["cycle"] for r in again["reviews"]} == {1, 2}
    assert td.post(f"{API}/designs/{did}/reviews/{rid}/decide", json={"decision": "approve"}).status_code == 409, "decisions from cycle 1 cannot be reused"


def test_upload_versions_and_access(pe, project, types, client_factory):
    d = _new(pe, project, types, "Bracket drawing", "DRAWING")
    bad = pe.post(f"{API}/designs/{d['id']}/versions", files={"file": ("x.docx", b"PK\x03\x04data", "application/octet-stream")})
    assert bad.json()["error"]["code"] == "FILE_TYPE"
    fake = pe.post(f"{API}/designs/{d['id']}/versions", files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    assert fake.json()["error"]["code"] == "FILE_SIGNATURE"
    ok = pe.post(f"{API}/designs/{d['id']}/versions", files={"file": ("bracket.pdf", b"%PDF-1.4 demo", "application/pdf")}, data={"note": "Sheet 1", "base_version": "0"})
    assert ok.status_code == 200 and ok.json()["versions"][0]["kind"] == "FILE"
    link = pe.post(f"{API}/designs/{d['id']}/link-version", json={"url": "https://cad.intranet.local/model/42", "base_version": 1}).json()
    assert link["versions"][0]["kind"] == "LINK"
    adm = client_factory("adm.babu")
    assert adm.get(f"{API}/designs/{d['id']}").status_code == 403
    assert adm.get(f"{API}/projects/{project}/designs").status_code == 403
    assert adm.post(f"{API}/projects/{project}/designs", json={"type_id": types["ARCH"]["id"], "title": "Not allowed"}).status_code == 403
