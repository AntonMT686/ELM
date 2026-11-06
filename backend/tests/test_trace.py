"""End-to-end traceability: activities derived from a requirement, the trace graph across documents, requirements,
designs, tasks, code, tests, runs, defects and deployments, GitLab links on design records and test cases, access."""
from __future__ import annotations

import json
import uuid

import pytest

from app.core.config import get_settings
from tests.fake_gitlab import TOKEN, FakeGitLab

API = "/api/v1"


@pytest.fixture(scope="module")
def pe(client_factory):
    return client_factory("pe.kumar")


@pytest.fixture(scope="module")
def project(pe):
    return next(p for p in pe.get(f"{API}/projects").json() if p["code"] == "ALPHA")["id"]


def _req(pe, project, key):
    return next(r for r in pe.get(f"{API}/projects/{project}/requirements").json()["items"] if r["key"] == key)


def test_seeded_trace_reaches_every_phase(pe, project):
    r1 = _req(pe, project, "ALPHA-CPU-0002")
    g = pe.get(f"{API}/trace", params={"type": "REQUIREMENT", "id": r1["id"], "depth": 4}).json()
    keys = {n["key"] for n in g["nodes"]}
    assert {"ALPHA-CPU-0002", "ALPHA-TC-0002", "ALPHA-RUN-0001", "ALPHA-DEF-0001"} <= keys, "requirement → test case → run → defect"
    assert "ALPHA-DEP-0003" in keys, "the run is the evidence of the UAT deployment"
    assert all(e["from"] in {n["id"] for n in g["nodes"]} and e["to"] in {n["id"] for n in g["nodes"]} for e in g["edges"])
    d = _req(pe, project, "ALPHA-CPU-0001")
    g2 = pe.get(f"{API}/trace", params={"type": "REQUIREMENT", "id": d["id"]}).json()
    assert {"ALPHA-DES-0001", "ALPHA-TC-0001", "ALPHA-12"} <= {n["key"] for n in g2["nodes"]}
    root = next(n for n in g2["nodes"] if n.get("root"))
    assert root["route"].startswith("/requirements/")


def test_derive_activities_from_a_requirement(pe, project):
    r = _req(pe, project, "ALPHA-CPU-0004")
    made = {}
    for kind in ("DESIGN", "DEVELOPMENT", "TEST_CASE", "TASK"):
        out = pe.post(f"{API}/requirements/{r['id']}/derive", json={"kind": kind})
        assert out.status_code == 200, out.text
        made[kind] = out.json()
    assert made["DESIGN"]["key"].startswith("ALPHA-DES-") and made["TEST_CASE"]["key"].startswith("ALPHA-TC-")
    dev = pe.get(f"{API}/work-items/{made['DEVELOPMENT']['id']}").json()
    assert dev["kind"] == "DEVELOPMENT" and dev["requirements"][0]["key"] == "ALPHA-CPU-0004"
    g = pe.get(f"{API}/trace", params={"type": "REQUIREMENT", "id": r["id"], "depth": 1}).json()
    assert {made[k]["key"] for k in made} <= {n["key"] for n in g["nodes"]}
    rtm = next(x for x in pe.get(f"{API}/projects/{project}/rtm").json()["rows"] if x["key"] == "ALPHA-CPU-0004")
    assert rtm["designs"] and rtm["tests"] and len(rtm["tasks"]) >= 2
    hist = pe.get(f"{API}/requirements/{r['id']}").json()["history"]
    assert any(h["kind"] == "DERIVED" for h in hist)


def test_git_links_on_design_and_test_case(pe, project, client_factory):
    fake = FakeGitLab()
    s = get_settings()
    saved = (s.gitlab_enabled, s.gitlab_url, s.gitlab_token, s.gitlab_webhook_secret)
    s.gitlab_enabled, s.gitlab_url, s.gitlab_token, s.gitlab_webhook_secret = True, fake.url, TOKEN, "trace-secret"
    try:
        repos = pe.get(f"{API}/projects/{project}/repositories").json()["items"]
        repo = repos[0] if repos else pe.post(f"{API}/projects/{project}/repositories", json={"path": "product-alpha/cpu-software"}).json()
        design = next(d for d in pe.get(f"{API}/projects/{project}/designs").json()["items"] if d["key"] == "ALPHA-DES-0001")
        case = next(c for c in pe.get(f"{API}/projects/{project}/test-cases").json()["items"] if c["key"] == "ALPHA-TC-0001")
        sha = uuid.uuid4().hex + "abcdabcd"
        payload = {"project": {"id": 42}, "ref": "refs/heads/main", "after": sha, "commits": [{"id": sha, "message": "ALPHA-DES-0001 diagram source and ALPHA-TC-0001 automation script", "timestamp": "2026-11-06T10:00:00+05:30", "author": {"name": "Dev"}}]}
        r = client_factory().post(f"{API}/scm/gitlab/webhook", content=json.dumps(payload), headers={"X-Gitlab-Token": "trace-secret", "X-Gitlab-Event": "Push Hook", "X-Gitlab-Event-UUID": str(uuid.uuid4()), "Content-Type": "application/json"})
        assert r.json()["links_created"] == 2
        dl = pe.get(f"{API}/artifacts/DESIGN/{design['id']}/scm").json()
        assert dl["links"][0]["ref"] == sha and "ALPHA-DES-0001" in dl["hint"]
        man = pe.post(f"{API}/artifacts/TEST_CASE/{case['id']}/scm", json={"repository_id": repo["id"], "kind": "MERGE_REQUEST", "ref": "7", "title": "Test script review"})
        assert man.status_code == 200 and len(man.json()["links"]) == 2
        g = pe.get(f"{API}/trace", params={"type": "DESIGN", "id": design["id"], "depth": 1}).json()
        assert any(n["type"] == "CODE" and n["key"].startswith("commit") for n in g["nodes"])
    finally:
        s.gitlab_enabled, s.gitlab_url, s.gitlab_token, s.gitlab_webhook_secret = saved
        fake.stop()


def test_trace_respects_access(pe, project, client_factory):
    r = _req(pe, project, "ALPHA-CPU-0001")
    assert client_factory("adm.babu").get(f"{API}/trace", params={"type": "REQUIREMENT", "id": r["id"]}).json()["nodes"] == []


def test_phase_reports_pdf_and_csv(pe, project, client_factory):
    kinds = [k["kind"] for k in pe.get(f"{API}/report-kinds").json()]
    assert kinds == ["documents", "requirements", "design", "development", "testing", "defects", "deployment", "traceability"]
    for k in kinds:
        pdf = pe.get(f"{API}/projects/{project}/reports/{k}.pdf")
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF", (k, pdf.text[:200])
        csvr = pe.get(f"{API}/projects/{project}/reports/{k}.csv")
        assert csvr.status_code == 200 and csvr.text.lstrip("﻿").strip(), k
    tr = pe.get(f"{API}/projects/{project}/reports/traceability.csv").text
    assert "ALPHA-CPU-0001" in tr and "ALPHA-DES-0001" in tr and "ALPHA-TC-0001" in tr
    assert "ALPHA-RUN-0001" in pe.get(f"{API}/projects/{project}/reports/testing.csv").text
    assert "ALPHA-DEF-0001" in pe.get(f"{API}/projects/{project}/reports/defects.csv").text
    assert "INT" in pe.get(f"{API}/projects/{project}/reports/deployment.csv").text
    assert client_factory("adm.babu").get(f"{API}/projects/{project}/reports/requirements.pdf").status_code == 403
    assert pe.get(f"{API}/projects/{project}/reports/nonsense.pdf").status_code == 404
