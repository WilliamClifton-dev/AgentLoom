"""Boundary contract submodule: tool."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import (
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from agentloom.contracts._base import (
    ContractModel,
    Sha256Digest,
)


def tool_parameter_digest(parameters: Mapping[str, object]) -> str:
    """Return the canonical digest bound into a governed tool request."""

    encoded = json.dumps(
        dict(parameters),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

class ToolExecutionRequest(ContractModel):
    """Provider-neutral identity for one authorized tool execution."""

    task_id: str = Field(alias="taskId", min_length=1)
    step_id: str = Field(alias="stepId", min_length=1)
    agent_name: str = Field(alias="agentName", min_length=1)
    skill_name: str = Field(alias="skillName", min_length=1)
    skill_version: str = Field(alias="skillVersion", min_length=1)
    tool_name: str = Field(alias="toolName", min_length=1)
    action: str = Field(min_length=1)
    parameter_digest: Sha256Digest = Field(
        alias="parameterDigest", pattern=r"^[a-f0-9]{64}$"
    )
    parameters: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def parameters_match_digest(self) -> ToolExecutionRequest:
        if self.parameter_digest != tool_parameter_digest(self.parameters):
            raise ValueError("parameters do not match parameterDigest")
        return self
class ToolExecutionResult(ContractModel):
    """Canonical result returned by every tool provider."""

    status: Literal["SUCCEEDED", "FAILED", "DENIED"]
    evidence_refs: list[str] = Field(alias="evidenceRefs", min_length=1)
    output_digest: Sha256Digest | None = Field(
        default=None,
        alias="outputDigest",
        pattern=r"^[a-f0-9]{64}$",
    )
    error_code: str | None = Field(default=None, alias="errorCode", min_length=1)

    @model_validator(mode="after")
    def result_fields_match_status(self) -> ToolExecutionResult:
        if self.status == "SUCCEEDED" and self.error_code is not None:
            raise ValueError("successful tool execution cannot contain an error code")
        if self.status != "SUCCEEDED" and self.error_code is None:
            raise ValueError("failed or denied tool execution requires an error code")
        return self
class SandboxExecutionRequest(ContractModel):
    """Immutable snapshot and limits for one isolated process execution."""

    schema_version: Literal["agentloom.sandbox-execution/v1alpha1"] = Field(
        default="agentloom.sandbox-execution/v1alpha1",
        alias="schemaVersion",
    )
    execution_id: str = Field(
        alias="executionId",
        pattern=r"^sandbox-[a-f0-9]{16,64}$",
    )
    snapshot_uri: str = Field(alias="snapshotUri", min_length=1, max_length=4096)
    snapshot_digest: Sha256Digest = Field(
        alias="snapshotDigest",
        pattern=r"^[a-f0-9]{64}$",
    )
    command: list[str] = Field(min_length=1, max_length=64)
    working_directory: str = Field(
        alias="workingDirectory",
        min_length=1,
        max_length=1024,
    )
    timeout_seconds: int = Field(alias="timeoutSeconds", ge=1, le=120)
    output_limit_bytes: int = Field(
        alias="outputLimitBytes",
        ge=1024,
        le=1_048_576,
    )

    @field_validator("command")
    @classmethod
    def command_has_bounded_arguments(cls, value: list[str]) -> list[str]:
        if any(not argument or len(argument) > 4096 or "\x00" in argument for argument in value):
            raise ValueError("sandbox command contains an invalid argument")
        return value

    @field_validator("working_directory")
    @classmethod
    def working_directory_is_normalized(cls, value: str) -> str:
        if value == ".":
            return value
        if "\\" in value or "\x00" in value:
            raise ValueError("workingDirectory must use safe POSIX syntax")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
            raise ValueError("workingDirectory must be a normalized relative path")
        return value
class SandboxExecutionResult(ContractModel):
    """Canonical output returned by every isolated execution backend."""

    schema_version: Literal["agentloom.sandbox-result/v1alpha1"] = Field(
        default="agentloom.sandbox-result/v1alpha1",
        alias="schemaVersion",
    )
    execution_id: str = Field(
        alias="executionId",
        pattern=r"^sandbox-[a-f0-9]{16,64}$",
    )
    provider_id: str = Field(alias="providerId", min_length=1, max_length=128)
    image_ref: str = Field(
        alias="imageRef",
        pattern=(
            r"^(?:sha256:[a-f0-9]{64}|"
            r"[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64})$"
        ),
    )
    snapshot_digest: Sha256Digest = Field(
        alias="snapshotDigest",
        pattern=r"^[a-f0-9]{64}$",
    )
    exit_code: int = Field(alias="exitCode", ge=0, le=255)
    stdout: str = Field(max_length=1_048_576)
    stderr: str = Field(max_length=1_048_576)
TOOL_CALL_EVENT_SCHEMA_VERSION: Literal["agentloom.tool-call/v1alpha1"] = (
    "agentloom.tool-call/v1alpha1"
)

TOOL_CALL_EVENT_TYPE: Literal["TOOL_CALL"] = "TOOL_CALL"

def tool_call_payload_digest(payload: Mapping[str, object]) -> str:
    """Return the stable digest for one immutable tool call event payload."""

    encoded = json.dumps(
        dict(payload),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

class ToolCallEventRecord(ContractModel):
    """Replayable record of one provider-bound tool request and its result."""

    schema_version: Literal["agentloom.tool-call/v1alpha1"] = Field(
        default=TOOL_CALL_EVENT_SCHEMA_VERSION,
        alias="schemaVersion",
    )
    event_type: Literal["TOOL_CALL"] = Field(
        default=TOOL_CALL_EVENT_TYPE,
        alias="eventType",
    )
    event_id: str = Field(alias="eventId", min_length=1)
    task_id: str = Field(alias="taskId", min_length=1)
    step_id: str = Field(alias="stepId", min_length=1)
    actor: str = Field(min_length=1)
    provider_id: str = Field(alias="providerId", min_length=1)
    grant_id: str = Field(alias="grantId", min_length=1)
    tool_name: str = Field(alias="toolName", min_length=1)
    action: str = Field(min_length=1)
    parameter_digest: Sha256Digest = Field(
        alias="parameterDigest", pattern=r"^[a-f0-9]{64}$"
    )
    status: Literal["SUCCEEDED", "FAILED", "DENIED"]
    evidence_refs: list[str] = Field(alias="evidenceRefs", min_length=1)
    output_digest: Sha256Digest | None = Field(
        default=None,
        alias="outputDigest",
        pattern=r"^[a-f0-9]{64}$",
    )
    error_code: str | None = Field(default=None, alias="errorCode", min_length=1)
    causation_id: str | None = Field(default=None, alias="causationId", min_length=1)
    correlation_id: str = Field(alias="correlationId", min_length=1)
    payload_digest: Sha256Digest = Field(
        alias="payloadDigest", pattern=r"^[a-f0-9]{64}$"
    )
    created_at: datetime = Field(alias="createdAt")

    @classmethod
    def from_execution(
        cls,
        *,
        event_id: str,
        request: ToolExecutionRequest,
        result: ToolExecutionResult,
        provider_id: str,
        grant_id: str,
        actor: str,
        created_at: datetime,
    ) -> ToolCallEventRecord:
        payload = cls._payload(
            task_id=request.task_id,
            step_id=request.step_id,
            actor=actor,
            provider_id=provider_id,
            grant_id=grant_id,
            tool_name=request.tool_name,
            action=request.action,
            parameter_digest=request.parameter_digest,
            status=result.status,
            evidence_refs=result.evidence_refs,
            output_digest=result.output_digest,
            error_code=result.error_code,
            causation_id=grant_id,
            correlation_id=request.task_id,
        )
        return cls(
            event_id=event_id,
            task_id=request.task_id,
            step_id=request.step_id,
            actor=actor,
            provider_id=provider_id,
            grant_id=grant_id,
            tool_name=request.tool_name,
            action=request.action,
            parameter_digest=request.parameter_digest,
            status=result.status,
            evidence_refs=result.evidence_refs,
            output_digest=result.output_digest,
            error_code=result.error_code,
            causation_id=grant_id,
            correlation_id=request.task_id,
            payload_digest=tool_call_payload_digest(payload),
            created_at=created_at,
        )

    @staticmethod
    def _payload(
        *,
        task_id: str,
        step_id: str,
        actor: str,
        provider_id: str,
        grant_id: str,
        tool_name: str,
        action: str,
        parameter_digest: str,
        status: str,
        evidence_refs: list[str],
        output_digest: str | None,
        error_code: str | None,
        causation_id: str | None,
        correlation_id: str,
    ) -> dict[str, object]:
        return {
            "schemaVersion": TOOL_CALL_EVENT_SCHEMA_VERSION,
            "eventType": TOOL_CALL_EVENT_TYPE,
            "taskId": task_id,
            "stepId": step_id,
            "actor": actor,
            "providerId": provider_id,
            "grantId": grant_id,
            "toolName": tool_name,
            "action": action,
            "parameterDigest": parameter_digest,
            "status": status,
            "evidenceRefs": evidence_refs,
            "outputDigest": output_digest,
            "errorCode": error_code,
            "causationId": causation_id,
            "correlationId": correlation_id,
        }

    def has_valid_payload_digest(self) -> bool:
        """Check that replayed request and result fields match the stored digest."""

        payload = self._payload(
            task_id=self.task_id,
            step_id=self.step_id,
            actor=self.actor,
            provider_id=self.provider_id,
            grant_id=self.grant_id,
            tool_name=self.tool_name,
            action=self.action,
            parameter_digest=self.parameter_digest,
            status=self.status,
            evidence_refs=self.evidence_refs,
            output_digest=self.output_digest,
            error_code=self.error_code,
            causation_id=self.causation_id,
            correlation_id=self.correlation_id,
        )
        return self.payload_digest == tool_call_payload_digest(payload)
