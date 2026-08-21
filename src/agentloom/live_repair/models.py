"""Fail-closed verification for model-generated AgentTeams repair submissions."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from agentloom.contracts import (
    ContractModel,
    CoordinationTrace,
    RepairArtifactBundle,
)

AgentName = Literal[
    "agentloom-investigator",
    "agentloom-implementer",
    "agentloom-verifier",
]
ProviderName = Literal["dashscope", "deepseek", "stepfun", "minimax-cn"]
ModelName = Literal[
    "qwen3.7-plus",
    "deepseek-v4-pro",
    "step-3.7-flash",
    "MiniMax-M2.5",
]

_EXPECTED_AGENTS: tuple[AgentName, ...] = (
    "agentloom-investigator",
    "agentloom-implementer",
    "agentloom-verifier",
)
_PROVIDER_MODELS: dict[ProviderName, ModelName] = {
    "dashscope": "qwen3.7-plus",
    "deepseek": "deepseek-v4-pro",
    "stepfun": "step-3.7-flash",
    "minimax-cn": "MiniMax-M2.5",
}
_HIDDEN_WORKSPACE = ".agentloom-hidden-tests"
_MAX_PATCH_BYTES = 131_072
_MAX_SOURCE_FILES = 64
_MAX_SOURCE_BYTES = 1_048_576




class LiveRepairError(RuntimeError):
    """Raised when a live AgentTeams repair cannot be independently proven."""

class AgentRoleEvent(ContractModel):
    agent_name: AgentName = Field(alias="agentName")
    matrix_user_id: str = Field(
        alias="matrixUserId",
        pattern=r"^@[^\s:]+:[^\s]+$",
    )
    room_id: str = Field(alias="roomId", pattern=r"^![^\s]+$")
    event_id: str = Field(alias="eventId", pattern=r"^\$[^\s]+$")
    origin_server_timestamp: int = Field(alias="originServerTimestamp", ge=1)

class LiveRepairSourceFile(ContractModel):
    source_path: str = Field(alias="sourcePath", min_length=1, max_length=300)
    object_name: str = Field(alias="objectName", min_length=1, max_length=305)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(alias="sizeBytes", ge=0, le=_MAX_SOURCE_BYTES)

    @field_validator("source_path", "object_name")
    @classmethod
    def paths_are_safe(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or value in {"", "."}
            or ".." in path.parts
            or "\\" in value
            or "\x00" in value
            or path.as_posix() != value
        ):
            raise ValueError("live repair source path is unsafe")
        return value

class LiveRepairCaseContext(ContractModel):
    schema_version: Literal["agentloom.live-repair-case/v1alpha1"] = Field(
        default="agentloom.live-repair-case/v1alpha1", alias="schemaVersion"
    )
    case_id: str = Field(alias="caseId", pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    case_fingerprint: str = Field(
        alias="caseFingerprint", pattern=r"^[a-f0-9]{64}$"
    )
    title: str = Field(min_length=1, max_length=200)
    issue: str = Field(min_length=1, max_length=20_000)
    acceptance_criteria: list[str] = Field(
        alias="acceptanceCriteria", min_length=1, max_length=20
    )
    source_files: list[LiveRepairSourceFile] = Field(
        alias="sourceFiles", min_length=1, max_length=_MAX_SOURCE_FILES
    )
    working_directory: str = Field(alias="workingDirectory")
    test_command: list[str] = Field(alias="testCommand", min_length=1)
    test_shell_command: str = Field(alias="testShellCommand", min_length=1)
    static_check_command: list[str] = Field(
        alias="staticCheckCommand", min_length=1
    )
    static_check_shell_command: str = Field(
        alias="staticCheckShellCommand", min_length=1
    )
    target_failing_tests: list[str] = Field(
        alias="targetFailingTests", min_length=1
    )
    allowed_changed_paths: list[str] = Field(
        alias="allowedChangedPaths", min_length=1
    )
    timeout_seconds: int = Field(alias="timeoutSeconds", ge=1, le=120)
    output_limit_bytes: int = Field(
        alias="outputLimitBytes", ge=1024, le=1_048_576
    )
    spec: str = Field(min_length=1, max_length=30_000)

class LiveRepairSubmission(ContractModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    schema_version: Literal["agentloom.live-repair-submission/v1alpha1"] = Field(
        alias="schemaVersion"
    )
    task_id: str = Field(
        alias="taskId",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    provider: ProviderName
    model: ModelName
    coordination_trace: CoordinationTrace = Field(alias="coordinationTrace")
    role_events: list[AgentRoleEvent] = Field(alias="roleEvents")
    repair_patch: str = Field(
        alias="repairPatch",
        min_length=1,
        max_length=_MAX_PATCH_BYTES,
    )
    bundle: RepairArtifactBundle

    @model_validator(mode="after")
    def submission_is_bound_to_agents_model_and_artifacts(
        self,
    ) -> LiveRepairSubmission:
        if self.model != _PROVIDER_MODELS[self.provider]:
            raise ValueError("provider and model are not an approved live E2E pair")
        if tuple(event.agent_name for event in self.role_events) != _EXPECTED_AGENTS:
            raise ValueError(
                "roleEvents must contain the three business Agent role events "
                "in Investigator, Implementer, Verifier order"
            )
        if len({event.event_id for event in self.role_events}) != 3:
            raise ValueError("roleEvents must use three distinct Matrix event IDs")
        if self.coordination_trace.task_id != self.task_id:
            raise ValueError("coordinationTrace must match submission taskId")
        all_event_ids = {
            event.event_id for event in self.coordination_trace.events
        } | {event.event_id for event in self.role_events}
        if len(all_event_ids) != 6:
            raise ValueError("coordination and role events must use distinct event IDs")
        ordered_timestamps = [
            self.coordination_trace.events[0].origin_server_timestamp,
            self.role_events[0].origin_server_timestamp,
            self.coordination_trace.events[1].origin_server_timestamp,
            self.role_events[1].origin_server_timestamp,
            self.coordination_trace.events[2].origin_server_timestamp,
            self.role_events[2].origin_server_timestamp,
        ]
        if ordered_timestamps != sorted(ordered_timestamps) or len(
            set(ordered_timestamps)
        ) != len(ordered_timestamps):
            raise ValueError(
                "coordination and role events must follow the repair handoff order"
            )
        if "\x00" in self.repair_patch:
            raise ValueError("repairPatch must not contain NUL bytes")

        artifact_task_ids = {
            self.bundle.root_cause.task_id,
            self.bundle.patch.task_id,
            self.bundle.verification.task_id,
            self.bundle.risk.task_id,
        }
        if artifact_task_ids != {self.task_id}:
            raise ValueError("all repair artifacts must match submission taskId")
        expected_uri = f"artifact://{self.task_id}/repair.patch"
        if self.bundle.patch.patch_uri != expected_uri:
            raise ValueError("PatchArtifact patchUri is not bound to the task")
        if self.bundle.verification.verifier_agent != "agentloom-verifier":
            raise ValueError("VerificationResult must be owned by agentloom-verifier")

        event_ids = {
            event.agent_name: event.event_id for event in self.role_events
        }
        if event_ids["agentloom-investigator"] not in (
            self.bundle.root_cause.evidence_refs
        ):
            raise ValueError("RootCauseReport is not bound to the Investigator event")
        if event_ids["agentloom-implementer"] not in self.bundle.patch.evidence_refs:
            raise ValueError("PatchArtifact is not bound to the Implementer event")
        verifier_event = event_ids["agentloom-verifier"]
        if verifier_event not in self.bundle.verification.evidence_refs:
            raise ValueError("VerificationResult is not bound to the Verifier event")
        if verifier_event not in self.bundle.risk.evidence_refs:
            raise ValueError("RiskReport is not bound to the Verifier event")
        return self
