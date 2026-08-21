"""Fail-closed verification for model-generated AgentTeams repair submissions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agentloom.contracts import (
    RepairArtifactBundle,
    VerificationResult,
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




@dataclass(frozen=True)
class LiveRepairResult:
    task_id: str
    provider: ProviderName
    model: ModelName
    bundle: RepairArtifactBundle
    role_verification: VerificationResult
    artifacts_dir: Path
