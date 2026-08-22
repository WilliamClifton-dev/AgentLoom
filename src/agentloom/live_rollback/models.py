"""Independent execution and verification of a role-traced live rollback."""

from __future__ import annotations

from dataclasses import dataclass

import hmac
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from agentloom.contracts import ContractModel
from agentloom.live_repair import (
    ModelName,
    ProviderName,
)

_MAX_SUBMISSION_BYTES = 1_048_576
_MAX_PATCH_BYTES = 131_072
_HIDDEN_WORKSPACE = ".agentloom-hidden-tests"
_PROVIDER_MODELS: dict[ProviderName, ModelName] = {
    "dashscope": "qwen3.7-plus",
    "deepseek": "deepseek-v4-pro",
    "stepfun": "step-3.7-flash",
}

RollbackPhase = Literal[
    "VERIFICATION_FAILED",
    "ROLLBACK_REQUESTED",
    "ROLLBACK_EXECUTED",
    "ROLLBACK_VERIFIED",
]
RollbackAgentName = Literal[
    "agentloom-manager",
    "agentloom-implementer",
    "agentloom-verifier",
]
_EXPECTED_EVENT_FLOW: tuple[tuple[RollbackPhase, RollbackAgentName], ...] = (
    ("VERIFICATION_FAILED", "agentloom-verifier"),
    ("ROLLBACK_REQUESTED", "agentloom-manager"),
    ("ROLLBACK_EXECUTED", "agentloom-implementer"),
    ("ROLLBACK_VERIFIED", "agentloom-verifier"),
)




class LiveRollbackError(RuntimeError):
    """Raised when a rollback cannot be independently proven."""

class RollbackRoleEvent(ContractModel):
    phase: RollbackPhase
    agent_name: RollbackAgentName = Field(alias="agentName")
    matrix_user_id: str = Field(
        alias="matrixUserId", pattern=r"^@[^\s:]+:[^\s]+$"
    )
    room_id: str = Field(alias="roomId", pattern=r"^![^\s]+$")
    event_id: str = Field(alias="eventId", pattern=r"^\$[^\s]+$")
    origin_server_timestamp: int = Field(alias="originServerTimestamp", ge=1)
    binding_sha256: str = Field(alias="bindingSha256", pattern=r"^[a-f0-9]{64}$")

class RollbackPlan(ContractModel):
    strategy: Literal["RESTORE_APPROVED_SNAPSHOT"]
    allowed_changed_paths: list[str] = Field(
        alias="allowedChangedPaths", min_length=1, max_length=32
    )
    reason: str = Field(min_length=1, max_length=500)

class LiveRollbackSubmission(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=False,
    )

    schema_version: Literal[
        "agentloom.live-rollback-submission/v1alpha1"
    ] = Field(alias="schemaVersion")
    task_id: str = Field(
        alias="taskId", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    case_id: str = Field(alias="caseId", pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    provider: ProviderName
    model: ModelName
    failed_patch: str = Field(
        alias="failedPatch", min_length=1, max_length=_MAX_PATCH_BYTES
    )
    failed_patch_sha256: str = Field(
        alias="failedPatchSha256", pattern=r"^[a-f0-9]{64}$"
    )
    binding_sha256: str = Field(alias="bindingSha256", pattern=r"^[a-f0-9]{64}$")
    rollback_plan: RollbackPlan = Field(alias="rollbackPlan")
    role_events: list[RollbackRoleEvent] = Field(
        alias="roleEvents", min_length=4, max_length=4
    )

    @model_validator(mode="after")
    def evidence_chain_is_ordered_and_bound(self) -> LiveRollbackSubmission:
        if self.model != _PROVIDER_MODELS[self.provider]:
            raise ValueError("provider and model are not an approved live E2E pair")
        _validate_role_event_chain(self.role_events, self.binding_sha256)
        expected_binding = _rollback_binding(
            task_id=self.task_id,
            case_id=self.case_id,
            failed_patch_sha256=self.failed_patch_sha256,
            plan=self.rollback_plan,
        )
        if not hmac.compare_digest(self.binding_sha256, expected_binding):
            raise ValueError("rollback binding does not match the submitted plan")
        if "\x00" in self.failed_patch:
            raise ValueError("failedPatch must not contain NUL bytes")
        return self

@dataclass(frozen=True)
class LiveRollbackResult:
    task_id: str
    case_id: str
    provider: ProviderName
    model: ModelName
    failed_patch_sha256: str
    failed_snapshot_sha256: str
    approved_snapshot_sha256: str
    failure_reproduced: bool
    rollback_executed: bool
    post_rollback_tests_passed: bool
    role_event_ids: tuple[str, ...]
    workspace: Path
    artifacts_dir: Path

class RollbackFailureEvidence(ContractModel):
    reproduced: Literal[True]
    failed_snapshot_sha256: str = Field(
        alias="failedSnapshotSha256", pattern=r"^[a-f0-9]{64}$"
    )

class RollbackExecutionEvidence(ContractModel):
    executed: Literal[True]
    approved_snapshot_sha256: str = Field(
        alias="approvedSnapshotSha256", pattern=r"^[a-f0-9]{64}$"
    )
    approved_snapshot_restored: Literal[True] = Field(
        alias="approvedSnapshotRestored"
    )
    visible_tests_passed: Literal[True] = Field(alias="visibleTestsPassed")
    hidden_tests_passed: Literal[True] = Field(alias="hiddenTestsPassed")
    static_checks_passed: Literal[True] = Field(alias="staticChecksPassed")

class VerifiedRollbackEvidence(ContractModel):
    schema_version: Literal["agentloom.live-rollback-evidence/v1alpha1"] = Field(
        alias="schemaVersion"
    )
    evidence_kind: Literal["LIVE_AGENTTEAMS_HOST_VERIFIED_ROLLBACK"] = Field(
        alias="evidenceKind"
    )
    status: Literal["PASS"]
    task_id: str = Field(
        alias="taskId", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    case_id: str = Field(alias="caseId", pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    provider: ProviderName
    model: ModelName
    submission_sha256: str = Field(alias="submissionSha256", pattern=r"^[a-f0-9]{64}$")
    failed_patch_sha256: str = Field(
        alias="failedPatchSha256", pattern=r"^[a-f0-9]{64}$"
    )
    binding_sha256: str = Field(alias="bindingSha256", pattern=r"^[a-f0-9]{64}$")
    test_results_sha256: str = Field(alias="testResultsSha256", pattern=r"^[a-f0-9]{64}$")
    role_events: list[RollbackRoleEvent] = Field(alias="roleEvents", min_length=4, max_length=4)
    rollback_plan: RollbackPlan = Field(alias="rollbackPlan")
    failure: RollbackFailureEvidence
    rollback: RollbackExecutionEvidence

    @model_validator(mode="after")
    def rollback_is_proven(self) -> VerifiedRollbackEvidence:
        _validate_role_event_chain(self.role_events, self.binding_sha256)
        expected_binding = _rollback_binding(
            task_id=self.task_id,
            case_id=self.case_id,
            failed_patch_sha256=self.failed_patch_sha256,
            plan=self.rollback_plan,
        )
        if not hmac.compare_digest(self.binding_sha256, expected_binding):
            raise ValueError("rollback evidence binding does not match the plan")
        if self.failure.failed_snapshot_sha256 == self.rollback.approved_snapshot_sha256:
            raise ValueError("rollback evidence must distinguish failed and approved snapshots")
        return self

@dataclass(frozen=True)
class RollbackEvidenceSummary:
    task_id: str
    case_id: str
    provider: ProviderName
    model: ModelName
    failed_patch_sha256: str
    failed_snapshot_sha256: str
    approved_snapshot_sha256: str
    role_events: tuple[RollbackRoleEvent, ...]
    manager_status: Literal["HEALTHY"]
    artifacts_dir: Path

def _validate_role_event_chain(
    events: list[RollbackRoleEvent], binding_sha256: str
) -> None:
    flow = tuple((event.phase, event.agent_name) for event in events)
    if flow != _EXPECTED_EVENT_FLOW:
        raise ValueError("role events do not match the required rollback flow")
    if len({event.event_id for event in events}) != 4:
        raise ValueError("role events must use distinct Matrix event IDs")
    business_rooms = {
        event.room_id
        for event in events
        if event.agent_name != "agentloom-manager"
    }
    all_rooms = {event.room_id for event in events}
    if len(business_rooms) != 1 or len(all_rooms) > 2:
        raise ValueError(
            "role events must use one Team Room and at most one Manager Room"
        )
    timestamps = [event.origin_server_timestamp for event in events]
    if timestamps != sorted(timestamps) or len(set(timestamps)) != 4:
        raise ValueError("role events must be strictly chronological")
    verifier_ids = {
        event.matrix_user_id
        for event in events
        if event.agent_name == "agentloom-verifier"
    }
    if len(verifier_ids) != 1:
        raise ValueError("Verifier events must use one Matrix identity")
    if any(
        not hmac.compare_digest(event.binding_sha256, binding_sha256)
        for event in events
    ):
        raise ValueError("role events do not match the rollback binding")

def _rollback_binding(
    *,
    task_id: str,
    case_id: str,
    failed_patch_sha256: str,
    plan: RollbackPlan,
) -> str:
    payload = "\n".join(
        (
            task_id,
            case_id,
            failed_patch_sha256,
            plan.strategy,
            ",".join(sorted(plan.allowed_changed_paths)),
            plan.reason,
        )
    ).encode("utf-8")
    return sha256(payload).hexdigest()
