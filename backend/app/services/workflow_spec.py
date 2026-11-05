"""Workflow specification schema + publish-time validation."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

StageType = Literal["prepare", "review", "approval", "signature", "acknowledge"]


class Condition(BaseModel):
    field: Literal["classification", "doc_type", "domain", "level", "category"]
    op: Literal["eq", "ne", "in", "not_in"] = "eq"
    value: str | list[str]

    def matches(self, facts: dict[str, str | None]) -> bool:
        v = facts.get(self.field)
        vals = self.value if isinstance(self.value, list) else [self.value]
        if self.op == "eq":
            return v == vals[0]
        if self.op == "ne":
            return v != vals[0]
        if self.op == "in":
            return v in vals
        return v not in vals


class AssigneeRule(BaseModel):
    kind: Literal["initiator", "pick", "role", "users"] = "pick"
    role_code: str | None = None  # eligibility filter for "pick", source for "role"
    user_ids: list[str] = Field(default_factory=list)
    min: int = 1
    max: int | None = None


class Stage(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    name: str = Field(min_length=2, max_length=80)
    type: StageType
    assignee: AssigneeRule = Field(default_factory=AssigneeRule)
    mode: Literal["any", "all", "quorum"] = "all"
    quorum: int | None = None
    sla_hours: int | None = 72
    sod_exclude: list[str] = Field(default_factory=list)  # actors of these stages may not act here
    allow_reject: bool = True
    checklist: list[str] = Field(default_factory=list)
    weight: int = Field(default=0, ge=0, le=100)  # progress contribution when stage completes
    signers_from: list[str] = Field(default_factory=list)  # signature stage: sign as actors of these stages
    skip_if: Condition | None = None
    instructions: str | None = None
    ui: dict | None = None  # designer layout hints


class WorkflowSpec(BaseModel):
    stages: list[Stage]
    on_complete: Literal["approve", "release"] = "approve"
    signature_required: bool | None = None  # None → follow document type setting

    @field_validator("stages")
    @classmethod
    def _non_empty(cls, v):
        if len(v) < 2:
            raise ValueError("A workflow needs at least a Prepare stage and one review/approval stage.")
        return v


def validate_spec(spec: WorkflowSpec, known_roles: set[str] | None = None) -> list[str]:
    """Returns list of human-readable problems. Empty list == publishable."""
    errs: list[str] = []
    keys = [s.key for s in spec.stages]
    if len(set(keys)) != len(keys):
        errs.append("Stage keys must be unique.")
    if spec.stages[0].type != "prepare":
        errs.append("The first stage must be a 'prepare' stage (author submits the revision).")
    if sum(1 for s in spec.stages if s.type == "prepare") > 1:
        errs.append("Only one 'prepare' stage is allowed.")
    if not any(s.type in ("review", "approval") for s in spec.stages):
        errs.append("At least one review or approval stage is required.")
    seen: set[str] = set()
    for i, s in enumerate(spec.stages):
        label = f"Stage '{s.name}'"
        if s.type == "prepare" and s.assignee.kind != "initiator":
            errs.append(f"{label}: prepare stage is always performed by the initiator.")
        if s.mode == "quorum" and (not s.quorum or s.quorum < 1):
            errs.append(f"{label}: quorum mode requires a quorum of at least 1.")
        if s.assignee.kind == "users" and not s.assignee.user_ids:
            errs.append(f"{label}: no named users configured.")
        if s.assignee.kind == "role" and not s.assignee.role_code:
            errs.append(f"{label}: role-based assignment needs a role.")
        if known_roles is not None and s.assignee.role_code and s.assignee.role_code not in known_roles:
            errs.append(f"{label}: role '{s.assignee.role_code}' does not exist.")
        for k in s.sod_exclude:
            if k not in seen:
                errs.append(f"{label}: separation-of-duties refers to '{k}', which is not an earlier stage.")
        if s.type == "signature":
            if not s.signers_from:
                errs.append(f"{label}: choose which earlier stages' actors must sign.")
            for k in s.signers_from:
                if k not in seen:
                    errs.append(f"{label}: signers_from refers to '{k}', which is not an earlier stage.")
        if s.assignee.max is not None and s.assignee.max < s.assignee.min:
            errs.append(f"{label}: max assignees is less than min.")
        if i > 0 and s.type == "prepare":
            errs.append(f"{label}: prepare must be first.")
        seen.add(s.key)
    if spec.on_complete == "release" and not any(s.type == "approval" for s in spec.stages):
        errs.append("Auto-release requires a formal approval stage.")
    return errs


DEFAULT_WEIGHTS = {"DRAFT": 10, "IN_REVIEW": 40, "CHANGES_REQUESTED": 25, "REJECTED": 10, "APPROVED": 85, "RELEASED": 100}
