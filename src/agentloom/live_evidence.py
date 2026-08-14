"""Strict projection of redacted evidence for the live AgentTeams TUI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from agentloom.contracts import ContractModel, CoordinationTrace
from agentloom.live_repair import AgentName, ModelName, ProviderName

_MAX_EVIDENCE_BYTES = 1_048_576
_EXPECTED_AGENTS: tuple[AgentName, ...] = (
    "agentloom-investigator",
    "agentloom-implementer",
    "agentloom-verifier",
)
_REQUIRED_HEALTH_CHECKS = {
    "docker",
    "controller",
    "manager",
    "team",
    "workers",
    "human",
    "matrix-rooms",
}
_PROVIDER_MODELS: dict[ProviderName, ModelName] = {
    "dashscope": "qwen3.7-plus",
    "deepseek": "deepseek-v4-pro",
    "stepfun": "step-3.7-flash",
    "minimax-cn": "MiniMax-M2.5",
}


class LiveEvidenceError(RuntimeError):
    """Raised when live evidence cannot be projected without trusting it."""


class AgentTeamsIdentity(ContractModel):
    tag: Literal["v1.1.2"]
    commit: Literal["a99457830fafb99c991bdb666aa8a1eef2f83b12"]


class HealthCheck(ContractModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    passed: bool
    detail: str = Field(min_length=1, max_length=500)


class DeploymentHealthEvidence(ContractModel):
    schema_version: Literal["agentloom.deployment-health/v1alpha1"] = Field(
        alias="schemaVersion"
    )
    checked_at: datetime = Field(alias="checkedAt")
    status: Literal["PASS"]
    agent_teams: AgentTeamsIdentity = Field(alias="agentTeams")
    failure_code: Literal[""] = Field(alias="failureCode")
    checks: list[HealthCheck] = Field(min_length=1, max_length=32)


class StrictRunCriteria(ContractModel):
    sender_must_match_role: Literal[True] = Field(alias="senderMustMatchRole")
    event_must_follow_task_start: Literal[True] = Field(
        alias="eventMustFollowTaskStart"
    )
    marker_must_be_independent_trimmed_line: Literal[True] = Field(
        alias="markerMustBeIndependentTrimmedLine"
    )
    result_objects_must_follow_task_start: Literal[True] = Field(
        alias="resultObjectsMustFollowTaskStart"
    )
    hidden_and_expected_objects_forbidden: Literal[True] = Field(
        alias="hiddenAndExpectedObjectsForbidden"
    )
    result_objects_must_be_allowlisted: Literal[True] = Field(
        alias="resultObjectsMustBeAllowlisted"
    )
    input_objects_remain_unchanged: Literal[True] = Field(
        alias="inputObjectsRemainUnchanged"
    )
    completion_event_must_follow_artifacts: Literal[True] = Field(
        alias="completionEventMustFollowArtifacts"
    )
    coordination_events_must_match_mentions: Literal[True] | None = Field(
        default=None,
        alias="coordinationEventsMustMatchMentions",
    )


class EvidenceRoleEvent(ContractModel):
    agent_name: AgentName = Field(alias="agentName")
    matrix_user_id: str = Field(
        alias="matrixUserId",
        min_length=3,
        max_length=256,
        pattern=r"^@[^\s:]+:[^\s]+$",
    )
    room_id: str = Field(
        alias="roomId", min_length=2, max_length=256, pattern=r"^![^\s]+$"
    )
    event_id: str = Field(
        alias="eventId", min_length=2, max_length=256, pattern=r"^\$[^\s]+$"
    )
    origin_server_timestamp: int = Field(alias="originServerTimestamp", ge=1)


class RunRoleEvent(ContractModel):
    key: Literal["investigator", "implementer", "verifier"]
    agent_name: AgentName = Field(alias="agentName")
    sender: str = Field(pattern=r"^@[^\s:]+:[^\s]+$")
    event_id: str = Field(alias="eventId", pattern=r"^\$[^\s]+$")
    room_id: str = Field(alias="roomId", pattern=r"^![^\s]+$")
    origin_server_timestamp: int = Field(alias="originServerTimestamp", ge=1)

    @model_validator(mode="after")
    def key_matches_agent(self) -> RunRoleEvent:
        if self.agent_name != f"agentloom-{self.key}":
            raise ValueError("role event key does not match agentName")
        return self


class LiveRunEvidence(ContractModel):
    schema_version: Literal["agentloom.live-repair-run/v1alpha1"] = Field(
        alias="schemaVersion"
    )
    task_id: str = Field(
        alias="taskId", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    provider: ProviderName
    model: ModelName
    started_at: datetime = Field(alias="startedAt")
    verified_at: datetime = Field(alias="verifiedAt")
    status: Literal["SUBMISSION_READY"]
    strict: Literal[True]
    criteria: StrictRunCriteria
    input_objects: list[dict[str, str | int]] = Field(
        alias="inputObjects", max_length=64
    )
    role_events: list[RunRoleEvent] = Field(
        alias="roleEvents", min_length=3, max_length=3
    )
    objects: list[dict[str, str | int]] = Field(max_length=64)
    submission_sha256: str = Field(
        alias="submissionSha256", pattern=r"^[a-f0-9]{64}$"
    )
    coordination_trace: CoordinationTrace | None = Field(
        default=None,
        alias="coordinationTrace",
    )

    @model_validator(mode="after")
    def roles_are_complete_and_ordered(self) -> LiveRunEvidence:
        if tuple(event.agent_name for event in self.role_events) != _EXPECTED_AGENTS:
            raise ValueError("run evidence must contain all business Agent roles")
        if len({event.event_id for event in self.role_events}) != 3:
            raise ValueError("run evidence must contain distinct Matrix events")
        if self.coordination_trace is not None:
            if self.criteria.coordination_events_must_match_mentions is not True:
                raise ValueError("coordination trace requires strict mention verification")
            if self.coordination_trace.task_id != self.task_id:
                raise ValueError("coordination trace must match run taskId")
            _validate_handoff_order(self.coordination_trace, self.role_events)
        return self


class IndependentVerification(ContractModel):
    original_failure_reproduced: Literal[True] = Field(
        alias="originalFailureReproduced"
    )
    target_tests_passed: Literal[True] = Field(alias="targetTestsPassed")
    regression_tests_passed: Literal[True] = Field(alias="regressionTestsPassed")
    hidden_tests_passed: Literal[True] = Field(alias="hiddenTestsPassed")
    static_checks_passed: Literal[True] = Field(alias="staticChecksPassed")
    unauthorized_changes: Literal[False] = Field(alias="unauthorizedChanges")


class VerifiedLiveEvidence(ContractModel):
    schema_version: Literal["agentloom.live-repair-evidence/v1alpha1"] = Field(
        alias="schemaVersion"
    )
    status: Literal["PASS"]
    task_id: str = Field(
        alias="taskId", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    case_id: str = Field(alias="caseId", pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    case_snapshot_sha256: str = Field(
        alias="caseSnapshotSha256", pattern=r"^sha256:[a-f0-9]{64}$"
    )
    provider: ProviderName
    model: ModelName
    submission_sha256: str = Field(
        alias="submissionSha256", pattern=r"^[a-f0-9]{64}$"
    )
    patch_sha256: str = Field(alias="patchSha256", pattern=r"^[a-f0-9]{64}$")
    test_results_sha256: str = Field(
        alias="testResultsSha256", pattern=r"^[a-f0-9]{64}$"
    )
    role_events: list[EvidenceRoleEvent] = Field(
        alias="roleEvents", min_length=3, max_length=3
    )
    coordination_trace: CoordinationTrace | None = Field(
        default=None,
        alias="coordinationTrace",
    )
    independent_verification: IndependentVerification = Field(
        alias="independentVerification"
    )

    @model_validator(mode="after")
    def roles_are_complete_and_ordered(self) -> VerifiedLiveEvidence:
        if tuple(event.agent_name for event in self.role_events) != _EXPECTED_AGENTS:
            raise ValueError("verified evidence must contain all business Agent roles")
        if len({event.event_id for event in self.role_events}) != 3:
            raise ValueError("verified evidence must contain distinct Matrix events")
        if self.coordination_trace is not None:
            if self.coordination_trace.task_id != self.task_id:
                raise ValueError("coordination trace must match verified taskId")
            _validate_handoff_order(self.coordination_trace, self.role_events)
        return self


@dataclass(frozen=True)
class LiveEvidenceSummary:
    task_id: str
    case_id: str
    provider: ProviderName
    model: ModelName
    patch_sha256: str
    manager_status: Literal["HEALTHY"]
    role_events: tuple[EvidenceRoleEvent, ...]
    hidden_tests_passed: bool
    artifacts_dir: Path
    coordination_verified: bool = False


class LiveEvidenceService:
    """Bind three redacted evidence layers into one display-only summary."""

    def load(
        self,
        *,
        health_path: Path,
        run_path: Path,
        verified_path: Path,
    ) -> LiveEvidenceSummary:
        health = _load_model(health_path, DeploymentHealthEvidence, "deployment health")
        run = _load_model(run_path, LiveRunEvidence, "AgentTeams run")
        verified = _load_model(verified_path, VerifiedLiveEvidence, "host verification")

        health_checks = {check.name for check in health.checks if check.passed}
        if (
            any(not check.passed for check in health.checks)
            or not _REQUIRED_HEALTH_CHECKS <= health_checks
        ):
            raise LiveEvidenceError("deployment health evidence is incomplete")
        if (
            run.task_id != verified.task_id
            or run.provider != verified.provider
            or run.model != verified.model
            or run.submission_sha256 != verified.submission_sha256
        ):
            raise LiveEvidenceError("run and verification evidence do not match")
        if verified.model != _PROVIDER_MODELS[verified.provider]:
            raise LiveEvidenceError("provider and model are not an approved pair")

        run_events = tuple(
            (
                event.agent_name,
                event.sender,
                event.room_id,
                event.event_id,
                event.origin_server_timestamp,
            )
            for event in run.role_events
        )
        verified_events = tuple(
            (
                event.agent_name,
                event.matrix_user_id,
                event.room_id,
                event.event_id,
                event.origin_server_timestamp,
            )
            for event in verified.role_events
        )
        if run_events != verified_events:
            raise LiveEvidenceError("run and verification role events do not match")
        run_coordination = (
            run.coordination_trace.model_dump(mode="json", by_alias=True)
            if run.coordination_trace is not None
            else None
        )
        verified_coordination = (
            verified.coordination_trace.model_dump(mode="json", by_alias=True)
            if verified.coordination_trace is not None
            else None
        )
        if run_coordination != verified_coordination:
            raise LiveEvidenceError("run and verification coordination traces do not match")

        return LiveEvidenceSummary(
            task_id=verified.task_id,
            case_id=verified.case_id,
            provider=verified.provider,
            model=verified.model,
            patch_sha256=verified.patch_sha256,
            manager_status="HEALTHY",
            role_events=tuple(verified.role_events),
            hidden_tests_passed=verified.independent_verification.hidden_tests_passed,
            coordination_verified=run.coordination_trace is not None,
            artifacts_dir=verified_path.resolve().parent,
        )


def _validate_handoff_order(
    coordination: CoordinationTrace,
    roles: list[RunRoleEvent] | list[EvidenceRoleEvent],
) -> None:
    timestamps = [
        coordination.events[0].origin_server_timestamp,
        roles[0].origin_server_timestamp,
        coordination.events[1].origin_server_timestamp,
        roles[1].origin_server_timestamp,
        coordination.events[2].origin_server_timestamp,
        roles[2].origin_server_timestamp,
    ]
    if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
        raise ValueError("coordination and role events must follow the handoff order")


def _load_model[ModelT: ContractModel](
    path: Path,
    model_type: type[ModelT],
    label: str,
) -> ModelT:
    try:
        if path.stat().st_size > _MAX_EVIDENCE_BYTES:
            raise LiveEvidenceError(f"{label} evidence exceeds the size limit")
        payload = path.read_bytes().decode("utf-8", errors="strict")
        return model_type.model_validate_json(payload)
    except LiveEvidenceError:
        raise
    except (OSError, UnicodeError, ValidationError) as exc:
        raise LiveEvidenceError(f"invalid {label} evidence") from exc
