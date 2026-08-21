"""Boundary contract submodule: approval."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import (
    Field,
    field_validator,
    model_validator,
)

from agentloom.contracts._base import (
    ApprovalStatus,
    ContractModel,
    EscalatedRiskLevel,
    Sha256Digest,
)


class ApprovalCreate(ContractModel):
    schema_version: Literal["agentloom.approval/v1alpha1"] = Field(
        default="agentloom.approval/v1alpha1",
        alias="schemaVersion",
    )
    task_id: str = Field(alias="taskId", min_length=1)
    grant_id: str = Field(alias="grantId", min_length=1)
    parameter_digest: Sha256Digest = Field(
        alias="parameterDigest", pattern=r"^[a-f0-9]{64}$"
    )
    risk_level: EscalatedRiskLevel = Field(alias="riskLevel")
    route_id: str = Field(alias="routeId", min_length=1, max_length=200)
    rollback_plan_hash: Sha256Digest = Field(
        alias="rollbackPlanHash", pattern=r"^[a-f0-9]{64}$"
    )
    action_summary: str = Field(alias="actionSummary", min_length=1, max_length=500)
    requested_by: str = Field(alias="requestedBy", min_length=1, max_length=200)
    expires_at: datetime = Field(alias="expiresAt")

    @field_validator("expires_at")
    @classmethod
    def expiry_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("approval expiry must be timezone-aware")
        return value
class ApprovalRecord(ApprovalCreate):
    approval_id: str = Field(alias="approvalId", min_length=1)
    status: ApprovalStatus = "PENDING"
    approval_version: int = Field(default=0, alias="approvalVersion", ge=0)
    created_at: datetime = Field(alias="createdAt")
    decided_by: str | None = Field(default=None, alias="decidedBy")
    decision_reason: str | None = Field(default=None, alias="decisionReason")
    decided_at: datetime | None = Field(default=None, alias="decidedAt")

    @model_validator(mode="after")
    def approval_state_is_bound_and_short_lived(self) -> ApprovalRecord:
        if self.created_at.tzinfo is None:
            raise ValueError("approval creation time must be timezone-aware")
        if self.expires_at <= self.created_at:
            raise ValueError("approval expiry must follow creation time")
        if self.expires_at - self.created_at > timedelta(minutes=15):
            raise ValueError("approval lifetime cannot exceed 15 minutes")
        decision_present = (
            self.decided_by is not None
            or self.decision_reason is not None
            or self.decided_at is not None
        )
        if self.status == "PENDING":
            if decision_present or self.approval_version != 0:
                raise ValueError("pending approval cannot contain a decision")
            return self
        if self.status in {"APPROVED", "REJECTED"}:
            if (
                not self.decided_by
                or not self.decision_reason
                or self.decided_at is None
                or self.decided_at.tzinfo is None
                or self.approval_version < 1
            ):
                raise ValueError(
                    "approved or rejected approval requires actor, reason, and timestamp"
                )
            return self
        if decision_present:
            raise ValueError("expired approval cannot contain a decision")
        return self
class ApprovalDecisionRequest(ContractModel):
    expected_approval_version: int = Field(alias="expectedApprovalVersion", ge=0)
    status: Literal["APPROVED", "REJECTED"]
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=500)
