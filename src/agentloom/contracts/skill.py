"""Boundary contract submodule: skill."""
from __future__ import annotations

from typing import Literal

from pydantic import (
    Field,
    model_validator,
)

from agentloom.contracts._base import (
    ContractModel,
    RiskLevel,
    SkillLifecycleState,
)


class SkillSource(ContractModel):
    repository: str = Field(min_length=1)
    path: str = Field(min_length=1)
    commit: str | None = Field(
        default=None,
        pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$",
    )
    workspace_snapshot: str | None = Field(
        default=None,
        alias="workspaceSnapshot",
        pattern=r"^sha256:[a-f0-9]{64}$",
    )
    license: str = Field(min_length=1)
    content_hash: str = Field(
        alias="contentHash",
        pattern=r"^sha256:[a-f0-9]{64}$",
    )

    @model_validator(mode="after")
    def revision_is_unambiguous_and_content_bound(self) -> SkillSource:
        if (self.commit is None) == (self.workspace_snapshot is None):
            raise ValueError("Skill source requires exactly one revision binding")
        if (
            self.workspace_snapshot is not None
            and self.workspace_snapshot != self.content_hash
        ):
            raise ValueError("workspace snapshot must equal the Skill content hash")
        return self
class SkillEvaluation(ContractModel):
    upstream_evidence_refs: list[str] = Field(
        alias="upstreamEvidenceRefs",
        min_length=1,
    )
    agentloom_bench_evidence_refs: list[str] = Field(
        alias="agentloomBenchEvidenceRefs",
        min_length=1,
    )
class SkillManifest(ContractModel):
    schema_version: Literal["agentloom.skill/v1alpha1"] = "agentloom.skill/v1alpha1"
    name: str = Field(min_length=1)
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
    skill_type: str = Field(min_length=1)
    scenarios: list[str] = Field(min_length=1)
    input_schema: str = Field(min_length=1)
    output_schema: str = Field(min_length=1)
    invocation_conditions: list[str] = Field(min_length=1)
    dependencies: list[str]
    failure_modes: list[str] = Field(min_length=1)
    permissions: list[str]
    security_boundary: str = Field(min_length=1)
    reuse_value: str = Field(min_length=1)
    source: SkillSource | None = None
    compatible_agents: list[str] | None = Field(
        default=None,
        alias="compatibleAgents",
        min_length=1,
    )
    allowed_tools: list[str] | None = Field(
        default=None,
        alias="allowedTools",
        min_length=1,
    )
    allowed_paths: list[str] | None = Field(default=None, alias="allowedPaths")
    risk_level: RiskLevel | None = Field(default=None, alias="riskLevel")
    evaluation: SkillEvaluation | None = None
    lifecycle_state: SkillLifecycleState = Field(
        default="DISCOVERED",
        alias="lifecycleState",
    )

    @model_validator(mode="after")
    def published_skill_requires_governance_metadata(self) -> SkillManifest:
        governed_states = {"APPROVED", "PUBLISHED", "DEPRECATED", "BLOCKED"}
        if self.lifecycle_state not in governed_states:
            return self
        required = {
            "source": self.source,
            "compatibleAgents": self.compatible_agents,
            "allowedTools": self.allowed_tools,
            "allowedPaths": self.allowed_paths,
            "riskLevel": self.risk_level,
            "evaluation": self.evaluation,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(
                "approved or published Skill requires governance metadata: "
                + ", ".join(missing)
            )
        return self
class SkillCatalog(ContractModel):
    schema_version: Literal["agentloom.skill-catalog/v1alpha1"] = (
        "agentloom.skill-catalog/v1alpha1"
    )
    skills: list[SkillManifest] = Field(min_length=1)

    @model_validator(mode="after")
    def skill_versions_are_unique(self) -> SkillCatalog:
        identities = [(skill.name, skill.version) for skill in self.skills]
        if len(identities) != len(set(identities)):
            raise ValueError("Skill catalog contains a duplicate name and version")
        return self
class SkillResolutionRequest(ContractModel):
    """Request for one immutable Skill manifest from a provider."""

    name: str = Field(min_length=1)
    version: str | None = Field(default=None, min_length=1)
