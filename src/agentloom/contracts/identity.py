"""Boundary contract submodule: identity."""
from __future__ import annotations

from typing import Literal

from pydantic import (
    Field,
    model_validator,
)

from agentloom.contracts._base import (
    ContractModel,
    CoordinationAgentName,
    CoordinationPhase,
)


class AgentIdentity(ContractModel):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    inputs: list[str] = Field(min_length=1)
    outputs: list[str] = Field(min_length=1)
    dependencies: list[str]
    decision_boundary: list[str] = Field(min_length=1)
    trace: list[str] = Field(min_length=1)
class CoordinationEvent(ContractModel):
    phase: CoordinationPhase
    agent_name: CoordinationAgentName = Field(alias="agentName")
    matrix_user_id: str = Field(
        alias="matrixUserId",
        pattern=r"^@[^\s:]+:[^\s]+$",
    )
    mentioned_agent: CoordinationAgentName = Field(alias="mentionedAgent")
    mentioned_user_id: str = Field(
        alias="mentionedUserId",
        pattern=r"^@[^\s:]+:[^\s]+$",
    )
    room_id: str = Field(alias="roomId", pattern=r"^![^\s]+$")
    event_id: str = Field(alias="eventId", pattern=r"^\$[^\s]+$")
    origin_server_timestamp: int = Field(alias="originServerTimestamp", ge=1)

    @model_validator(mode="after")
    def phase_matches_sender_and_target(self) -> CoordinationEvent:
        expected = {
            "MANAGER_DELEGATED": (
                "agentloom-manager",
                "agentloom-investigator",
            ),
            "IMPLEMENTER_ASSIGNED": (
                "agentloom-investigator",
                "agentloom-implementer",
            ),
            "VERIFIER_ASSIGNED": (
                "agentloom-investigator",
                "agentloom-verifier",
            ),
        }[self.phase]
        if (self.agent_name, self.mentioned_agent) != expected:
            raise ValueError("coordination phase does not match sender and target")
        expected_mention_prefix = f"@{self.mentioned_agent}:"
        if not self.mentioned_user_id.startswith(expected_mention_prefix):
            raise ValueError("mentioned user does not match mentioned Agent")
        if (
            self.agent_name != "agentloom-manager"
            and not self.matrix_user_id.startswith(f"@{self.agent_name}:")
        ):
            raise ValueError("sender user does not match coordination Agent")
        return self
class CoordinationTrace(ContractModel):
    schema_version: Literal["agentloom.coordination-trace/v1alpha1"] = Field(
        default="agentloom.coordination-trace/v1alpha1",
        alias="schemaVersion",
    )
    task_id: str = Field(
        alias="taskId",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    events: list[CoordinationEvent] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def events_form_one_strict_delegation_chain(self) -> CoordinationTrace:
        expected_phases: tuple[CoordinationPhase, ...] = (
            "MANAGER_DELEGATED",
            "IMPLEMENTER_ASSIGNED",
            "VERIFIER_ASSIGNED",
        )
        if tuple(event.phase for event in self.events) != expected_phases:
            raise ValueError("coordination phases must follow the required order")
        if len({event.event_id for event in self.events}) != len(self.events):
            raise ValueError("coordination events must have distinct event IDs")
        timestamps = [event.origin_server_timestamp for event in self.events]
        if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
            raise ValueError("coordination events must be strictly ordered")
        return self
