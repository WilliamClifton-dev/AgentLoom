"""Boundary contract submodule: task."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from pydantic import (
    Field,
)

from agentloom.contracts._base import (
    ContractModel,
    Sha256Digest,
    TaskStatus,
)
from agentloom.contracts.evidence import (  # noqa: F401  (forward refs)
    EvidenceRecord,
    TaskEvidenceBundle,
)


class TaskCreate(ContractModel):
    title: str = Field(min_length=1, max_length=200)
    repository_uri: str = Field(alias="repositoryUri", min_length=1)
    issue: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(alias="acceptanceCriteria", min_length=1)
    allowed_paths: list[str] = Field(alias="allowedPaths", min_length=1)
class TaskRecord(TaskCreate):
    task_id: str = Field(alias="taskId", min_length=1)
    status: TaskStatus = "RECEIVED"
    plan_version: int = Field(default=0, alias="planVersion", ge=0)
    created_at: datetime = Field(alias="createdAt")
class TaskTransition(ContractModel):
    expected_plan_version: int = Field(alias="expectedPlanVersion", ge=0)
    status: TaskStatus
    reason: str = Field(min_length=1)
WorkflowVerificationOutcome = Literal["PASSED", "FAILED", "UNSAFE", "UNCERTAIN"]

WorkflowCompletionOutcome = Literal["PASSED", "FAILED", "CANCELLED"]

TASK_EVENT_SCHEMA_VERSION: Literal["agentloom.task-event/v1alpha1"] = (
    "agentloom.task-event/v1alpha1"
)

TASK_EVENT_TYPE: Literal["TASK_STATUS_TRANSITION"] = "TASK_STATUS_TRANSITION"

def task_event_payload_digest(payload: Mapping[str, object]) -> str:
    """Return the stable digest for the non-volatile TaskEvent payload."""

    encoded = json.dumps(
        dict(payload),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

class TaskEventRecord(ContractModel):
    schema_version: Literal["agentloom.task-event/v1alpha1"] = Field(
        default=TASK_EVENT_SCHEMA_VERSION,
        alias="schemaVersion",
    )
    event_type: Literal["TASK_STATUS_TRANSITION"] = Field(
        default=TASK_EVENT_TYPE,
        alias="eventType",
    )
    event_id: str = Field(alias="eventId", min_length=1)
    task_id: str = Field(alias="taskId", min_length=1)
    from_status: TaskStatus = Field(alias="fromStatus")
    to_status: TaskStatus = Field(alias="toStatus")
    plan_version: int = Field(alias="planVersion", ge=1)
    reason: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    causation_id: str | None = Field(default=None, alias="causationId")
    correlation_id: str = Field(alias="correlationId", min_length=1)
    payload_digest: Sha256Digest = Field(
        alias="payloadDigest",
        pattern=r"^[a-f0-9]{64}$",
    )
    created_at: datetime = Field(alias="createdAt")

    @classmethod
    def from_transition(
        cls,
        *,
        event_id: str,
        task_id: str,
        from_status: TaskStatus,
        to_status: TaskStatus,
        plan_version: int,
        reason: str,
        actor: str,
        causation_id: str | None,
        created_at: datetime,
    ) -> TaskEventRecord:
        payload: dict[str, object] = {
            "schemaVersion": TASK_EVENT_SCHEMA_VERSION,
            "eventType": TASK_EVENT_TYPE,
            "taskId": task_id,
            "fromStatus": from_status,
            "toStatus": to_status,
            "planVersion": plan_version,
            "reason": reason,
            "actor": actor,
            "causationId": causation_id,
            "correlationId": task_id,
        }
        return cls(
            schema_version=TASK_EVENT_SCHEMA_VERSION,
            event_type=TASK_EVENT_TYPE,
            event_id=event_id,
            task_id=task_id,
            from_status=from_status,
            to_status=to_status,
            plan_version=plan_version,
            reason=reason,
            actor=actor,
            causation_id=causation_id,
            correlation_id=task_id,
            payload_digest=task_event_payload_digest(payload),
            created_at=created_at,
        )

    def has_valid_payload_digest(self) -> bool:
        """Check that replayed event fields match the stored payload digest."""

        payload: dict[str, object] = {
            "schemaVersion": self.schema_version,
            "eventType": self.event_type,
            "taskId": self.task_id,
            "fromStatus": self.from_status,
            "toStatus": self.to_status,
            "planVersion": self.plan_version,
            "reason": self.reason,
            "actor": self.actor,
            "causationId": self.causation_id,
            "correlationId": self.correlation_id,
        }
        return self.payload_digest == task_event_payload_digest(payload)
class Pagination(ContractModel):
    page: int = Field(ge=1)
    page_size: int = Field(alias="pageSize", ge=1, le=100)
    total_items: int = Field(alias="totalItems", ge=0)
    total_pages: int = Field(alias="totalPages", ge=0)
class TaskPage(ContractModel):
    data: list[TaskRecord]
    pagination: Pagination
