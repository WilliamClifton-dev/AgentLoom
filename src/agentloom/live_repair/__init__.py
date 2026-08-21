"""Live repair package split out of the legacy live_repair.py monolith."""
from __future__ import annotations

from agentloom.live_repair._types import (  # noqa: F401  (re-export)
    AgentName,
    ModelName,
    ProviderName,
)
from agentloom.live_repair.case import (  # noqa: F401  (re-export)
    _apply_patch,
    _patch_paths,
    _write_case_context,
    _write_evidence,
    prepare_live_repair_case_context,
)
from agentloom.live_repair.cli import main  # noqa: F401  (re-export)
from agentloom.live_repair.models import (  # noqa: F401  (re-export)
    AgentRoleEvent,
    LiveRepairCaseContext,
    LiveRepairError,
    LiveRepairSourceFile,
    LiveRepairSubmission,
)
from agentloom.live_repair.result import LiveRepairResult  # noqa: F401  (re-export)
from agentloom.live_repair.verifier import LiveRepairVerifier  # noqa: F401  (re-export)

__all__ = [
    "AgentName",
    "ModelName",
    "ProviderName",
    "AgentRoleEvent",
    "LiveRepairCaseContext",
    "LiveRepairError",
    "LiveRepairResult",
    "LiveRepairSourceFile",
    "LiveRepairSubmission",
    "LiveRepairVerifier",
    "_apply_patch",
    "_patch_paths",
    "_write_case_context",
    "_write_evidence",
    "main",
    "prepare_live_repair_case_context",
]
