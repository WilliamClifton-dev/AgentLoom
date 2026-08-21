"""Boundary contract submodule: grant."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import (
    Field,
    model_validator,
)

from agentloom.contracts._base import (
    ContractModel,
    RiskLevel,
    Sha256Digest,
)
from agentloom.contracts.tool import (  # noqa: F401  (forward refs)
    ToolExecutionRequest,
    ToolExecutionResult,
)


class SkillExecutionGrant(ContractModel):
    schema_version: Literal["agentloom.grant/v1alpha1"] = "agentloom.grant/v1alpha1"
    grant_id: str = Field(alias="grantId", min_length=1)
    task_id: str = Field(alias="taskId", min_length=1)
    step_id: str = Field(alias="stepId", min_length=1)
    agent_name: str = Field(alias="agentName", min_length=1)
    skill_name: str = Field(alias="skillName", min_length=1)
    skill_version: str = Field(alias="skillVersion", min_length=1)
    skill_content_hash: str | None = Field(
        default=None,
        alias="skillContentHash",
        pattern=r"^sha256:[a-f0-9]{64}$",
    )
    tool_name: str = Field(alias="toolName", min_length=1)
    action: str = Field(min_length=1)
    route_id: str | None = Field(default=None, alias="routeId", min_length=1)
    rollback_plan_hash: Sha256Digest | None = Field(
        default=None,
        alias="rollbackPlanHash",
        pattern=r"^[a-f0-9]{64}$",
    )
    parameter_digest: Sha256Digest = Field(
        alias="parameterDigest", pattern=r"^[a-f0-9]{64}$"
    )
    authorized_paths: list[str] = Field(alias="authorizedPaths", min_length=1)
    risk_level: RiskLevel = Field(alias="riskLevel")
    approval_ref: str | None = Field(default=None, alias="approvalRef")
    nonce: str = Field(min_length=8)
    issued_at: datetime = Field(alias="issuedAt")
    expires_at: datetime = Field(alias="expiresAt")

    @model_validator(mode="after")
    def validate_time_window(self) -> SkillExecutionGrant:
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("grant timestamps must be timezone-aware")
        if self.expires_at <= self.issued_at:
            raise ValueError("grant expiry must follow issue time")
        if self.expires_at - self.issued_at > timedelta(minutes=15):
            raise ValueError("grant lifetime cannot exceed 15 minutes")
        return self
class SignedSkillExecutionGrant(ContractModel):
    grant: SkillExecutionGrant
    signature: str = Field(pattern=r"^[a-f0-9]{64}$")
class GrantIssuanceRequest(ContractModel):
    """Caller-controlled fields for one server-derived execution Grant."""

    task_id: str = Field(alias="taskId", min_length=1)
    step_id: str = Field(alias="stepId", min_length=1)
    skill_name: str = Field(alias="skillName", min_length=1)
    skill_version: str = Field(alias="skillVersion", min_length=1)
    tool_name: str = Field(alias="toolName", min_length=1)
    action: str = Field(min_length=1)
    parameter_digest: Sha256Digest = Field(
        alias="parameterDigest",
        pattern=r"^[a-f0-9]{64}$",
    )
    requested_paths: list[str] = Field(alias="requestedPaths", min_length=1)
class ToolExecutionEnvelope(ContractModel):
    """Policy-bound tool request passed from the MCP boundary to a provider."""

    signed_grant: SignedSkillExecutionGrant = Field(alias="signedGrant")
    tool_request: ToolExecutionRequest = Field(alias="toolRequest")

    @model_validator(mode="after")
    def request_matches_grant(self) -> ToolExecutionEnvelope:
        grant = self.signed_grant.grant
        request = self.tool_request
        matching_fields = (
            (request.task_id, grant.task_id),
            (request.step_id, grant.step_id),
            (request.agent_name, grant.agent_name),
            (request.skill_name, grant.skill_name),
            (request.skill_version, grant.skill_version),
            (request.tool_name, grant.tool_name),
            (request.action, grant.action),
            (request.parameter_digest, grant.parameter_digest),
        )
        if any(requested != authorized for requested, authorized in matching_fields):
            raise ValueError("toolRequest does not match signed grant")
        return self
class GrantVerificationRequest(ContractModel):
    signed_grant: SignedSkillExecutionGrant = Field(alias="signedGrant")
    parameter_digest: Sha256Digest = Field(
        alias="parameterDigest", pattern=r"^[a-f0-9]{64}$"
    )
