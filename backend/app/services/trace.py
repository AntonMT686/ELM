"""End-to-end traceability (architecture §19.1): from any record, follow every kind of link ELM keeps.

    document ─ specifies ─ requirement ─ derived / depends ─ requirement
                              │ satisfies        │ implements          │ verifies
                            design          task / development      test case ── run ── defect
                              │ code             │ code (branch/commit/MR)              │ fix task
                            GitLab             GitLab                                 deployment (includes tasks, uses runs)

The walk is breadth-first up to a depth and a node limit, and only shows records the viewer may open.
"""
from __future__ import annotations

import uuid
from collections import deque

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    Document,
    Requirement,
    RequirementDocument,
    RequirementLink,
    RequirementWorkItem,
    TaskDeliverable,
    WorkItem,
)
from app.models.artifacts import ArtifactLink
from app.models.deployment import Deployment
from app.models.design import DesignRecord
from app.models.scm import ScmLink
from app.models.testing import Defect, TestCase, TestExecution, TestRun, TestRunCase
from app.services.authz import Principal, can_view_document
from app.services.planning import can_view_project, can_view_task

MODELS = {"DOCUMENT": Document, "REQUIREMENT": Requirement, "DESIGN": DesignRecord, "TASK": WorkItem, "TEST_CASE": TestCase, "TEST_RUN": TestRun, "DEFECT": Defect, "DEPLOYMENT": Deployment, "CODE": ScmLink}
ORDER = ["DOCUMENT", "REQUIREMENT", "DESIGN", "TASK", "CODE", "TEST_CASE", "TEST_RUN", "DEFECT", "DEPLOYMENT"]


def _route(t: str, o) -> str | None:
    pid = getattr(o, "project_id", None)
    return {"DOCUMENT": f"/documents/{o.id}", "REQUIREMENT": f"/requirements/{pid}?open={o.id}", "DESIGN": f"/design/{pid}?open={o.id}", "TASK": f"/tasks?open={o.id}",
            "TEST_CASE": f"/testing/{pid}?case={o.id}", "TEST_RUN": f"/testing/{pid}?run={o.id}", "DEFECT": f"/testing/{pid}?defect={o.id}", "DEPLOYMENT": f"/deployments/{pid}?open={o.id}"}.get(t)


def node(t: str, o) -> dict:
    if t == "CODE":
        label = {"BRANCH": "branch", "COMMIT": "commit", "MERGE_REQUEST": "MR"}[o.kind]
        ref = f"!{o.ref}" if o.kind == "MERGE_REQUEST" else (o.ref[:10] if o.kind == "COMMIT" else o.ref)
        return {"id": f"CODE:{o.id}", "type": "CODE", "ref_id": str(o.id), "key": f"{label} {ref}", "title": o.title or "", "status": o.state or "", "url": o.url}
    key = getattr(o, "key", None) or getattr(o, "number", None)
    title = getattr(o, "title", "") or ""
    return {"id": f"{t}:{o.id}", "type": t, "ref_id": str(o.id), "key": key, "title": title, "status": getattr(o, "status", ""), "route": _route(t, o)}


class Tracer:
    def __init__(self, db: Session, p: Principal):
        self.db, self.p = db, p
        self._proj: dict = {}

    def visible(self, t: str, o) -> bool:
        if t == "DOCUMENT":
            return can_view_document(self.db, self.p, o)
        if t == "TASK":
            return can_view_task(self.db, self.p, o)
        if t == "CODE":
            return True  # reached only through a visible task or artefact
        pid = o.project_id
        if pid not in self._proj:
            self._proj[pid] = can_view_project(self.db, self.p, pid)
        return self._proj[pid]

    def _get(self, t: str, oid):
        return self.db.get(MODELS[t], oid) if oid else None

    def neighbours(self, t: str, o) -> list[tuple[str, object, str]]:
        db, out = self.db, []

        def add(tt, x, label):
            if x is not None:
                out.append((tt, x, label))

        # generic artefact links (design, test case, defect, deployment ↔ anything)
        if t in ("REQUIREMENT", "DOCUMENT", "TASK", "DESIGN", "TEST_CASE", "DEFECT", "DEPLOYMENT"):
            for x in db.execute(select(ArtifactLink).where(or_((ArtifactLink.from_type == t) & (ArtifactLink.from_id == o.id), (ArtifactLink.to_type == t) & (ArtifactLink.to_id == o.id)))).scalars():
                other_t, other_id = (x.to_type, x.to_id) if x.from_id == o.id and x.from_type == t else (x.from_type, x.from_id)
                if other_t in MODELS:
                    add(other_t, self._get(other_t, other_id), x.link_type + (f" § {x.section}" if x.section else ""))
        if t == "DOCUMENT":
            for rd in db.execute(select(RequirementDocument).where(RequirementDocument.document_id == o.id)).scalars():
                add("REQUIREMENT", db.get(Requirement, rd.requirement_id), "specifies" + (f" § {rd.section}" if rd.section else ""))
            for d in db.execute(select(TaskDeliverable).where(TaskDeliverable.document_id == o.id)).scalars():
                add("TASK", db.get(WorkItem, d.work_item_id), "deliverable of")
        if t == "REQUIREMENT":
            for rd in db.execute(select(RequirementDocument).where(RequirementDocument.requirement_id == o.id)).scalars():
                add("DOCUMENT", db.get(Document, rd.document_id), "specified in" + (f" § {rd.section}" if rd.section else ""))
            for lk in db.execute(select(RequirementLink).where(or_(RequirementLink.from_id == o.id, RequirementLink.to_id == o.id))).scalars():
                add("REQUIREMENT", db.get(Requirement, lk.to_id if lk.from_id == o.id else lk.from_id), lk.link_type.replace("_", " "))
            if o.parent_id:
                add("REQUIREMENT", db.get(Requirement, o.parent_id), "child of")
            for c in db.execute(select(Requirement).where(Requirement.parent_id == o.id)).scalars():
                add("REQUIREMENT", c, "parent of")
            for rw in db.execute(select(RequirementWorkItem).where(RequirementWorkItem.requirement_id == o.id)).scalars():
                add("TASK", db.get(WorkItem, rw.work_item_id), rw.link_type)
        if t == "TASK":
            for rw in db.execute(select(RequirementWorkItem).where(RequirementWorkItem.work_item_id == o.id)).scalars():
                add("REQUIREMENT", db.get(Requirement, rw.requirement_id), rw.link_type)
            for s in db.execute(select(ScmLink).where(ScmLink.work_item_id == o.id)).scalars():
                add("CODE", s, "code")
            for d in db.execute(select(Defect).where(Defect.work_item_id == o.id)).scalars():
                add("DEFECT", d, "fixes")
            for d in db.execute(select(TaskDeliverable).where(TaskDeliverable.work_item_id == o.id)).scalars():
                add("DOCUMENT", db.get(Document, d.document_id), "deliverable")
        if t in ("DESIGN", "TEST_CASE", "DEFECT"):
            for s in db.execute(select(ScmLink).where(ScmLink.artifact_type == t, ScmLink.artifact_id == o.id)).scalars():
                add("CODE", s, "code")
        if t == "TEST_CASE":
            for run in db.execute(select(TestRun).join(TestRunCase, TestRunCase.run_id == TestRun.id).where(TestRunCase.case_id == o.id).distinct()).scalars():
                add("TEST_RUN", run, "executed in")
        if t == "TEST_RUN":
            for c in db.execute(select(TestCase).join(TestRunCase, TestRunCase.case_id == TestCase.id).where(TestRunCase.run_id == o.id)).scalars():
                add("TEST_CASE", c, "executes")
            for d in db.execute(select(Defect).join(TestExecution, TestExecution.defect_id == Defect.id).join(TestRunCase, TestRunCase.id == TestExecution.run_case_id).where(TestRunCase.run_id == o.id).distinct()).scalars():
                add("DEFECT", d, "found")
            for dep in db.execute(select(Deployment).where(Deployment.test_run_id == o.id)).scalars():
                add("DEPLOYMENT", dep, "evidence for")
        if t == "DEFECT":
            if o.work_item_id:
                add("TASK", db.get(WorkItem, o.work_item_id), "fix task")
            for run in db.execute(select(TestRun).join(TestRunCase, TestRunCase.run_id == TestRun.id).join(TestExecution, TestExecution.run_case_id == TestRunCase.id).where(TestExecution.defect_id == o.id).distinct()).scalars():
                add("TEST_RUN", run, "found in")
        if t == "DEPLOYMENT":
            if o.test_run_id:
                add("TEST_RUN", db.get(TestRun, o.test_run_id), "test evidence")
            if o.rollback_of_id:
                add("DEPLOYMENT", db.get(Deployment, o.rollback_of_id), "rolls back")
        return out

    def walk(self, t: str, oid: uuid.UUID, depth: int = 4, limit: int = 250) -> dict:
        root = self._get(t, oid)
        if root is None or not self.visible(t, root):
            return {"nodes": [], "edges": [], "truncated": False}
        nodes = {f"{t}:{root.id}": {**node(t, root), "depth": 0, "root": True}}
        edges: dict[tuple, dict] = {}
        q = deque([(t, root, 0)])
        truncated = False
        while q:
            ct, co, d = q.popleft()
            if d >= depth or ct == "CODE":
                continue
            for nt, no, label in self.neighbours(ct, co):
                nid = f"{nt}:{no.id}"
                if nid not in nodes:
                    if not self.visible(nt, no):
                        continue
                    if len(nodes) >= limit:
                        truncated = True
                        continue
                    nodes[nid] = {**node(nt, no), "depth": d + 1}
                    q.append((nt, no, d + 1))
                a, b = f"{ct}:{co.id}", nid
                k = tuple(sorted((a, b)))
                edges.setdefault(k, {"from": a, "to": b, "label": label})
        ns = sorted(nodes.values(), key=lambda n: (ORDER.index(n["type"]), n["depth"], str(n["key"])))
        return {"nodes": ns, "edges": list(edges.values()), "truncated": truncated, "counts": {k: sum(1 for n in ns if n["type"] == k) for k in ORDER}}
