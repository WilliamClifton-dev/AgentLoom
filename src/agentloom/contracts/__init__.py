"""AgentLoom boundary contracts, split by responsibility."""

from __future__ import annotations

import sys

from agentloom.contracts._base import (  # noqa: F401  (re-export
    ApprovalStatus,
    ContractModel,
    CoordinationAgentName,
    CoordinationPhase,
    DetectionStageName,
    EscalatedRiskLevel,
    ExperienceOutcome,
    RiskLevel,
    Severity,
    Sha256Digest,
    SkillLifecycleState,
    TaskDetectionProducer,
    TaskStatus,
    VerificationVerdict,
)
from agentloom.contracts.approval import (  # noqa: F401  (re-export
    ApprovalCreate,
    ApprovalDecisionRequest,
    ApprovalRecord,
)
from agentloom.contracts.evidence import (  # noqa: F401  (re-export
    SKILL_INVOCATION_SCHEMA_VERSION,
    EvidenceRecord,
    PatchArtifact,
    RootCauseReport,
    SkillInvocationEvidenceRecord,
    TaskEvidenceBundle,
    VerificationChecks,
    VerificationRequest,
    VerificationResult,
    skill_invocation_payload_digest,
)
from agentloom.contracts.grant import (  # noqa: F401  (re-export
    GrantIssuanceRequest,
    GrantVerificationRequest,
    SignedSkillExecutionGrant,
    SkillExecutionGrant,
    ToolExecutionEnvelope,
)
from agentloom.contracts.identity import (  # noqa: F401  (re-export
    AgentIdentity,
    CoordinationEvent,
    CoordinationTrace,
)
from agentloom.contracts.repair import (  # noqa: F401  (re-export
    DetectionReport,
    DetectionResult,
    ExperienceRecord,
    RepairArtifactBundle,
    TaskDetectionRecord,
)
from agentloom.contracts.risk import (  # noqa: F401  (re-export
    Finding,
    RiskReport,
)
from agentloom.contracts.skill import (  # noqa: F401  (re-export
    SkillCatalog,
    SkillEvaluation,
    SkillManifest,
    SkillResolutionRequest,
    SkillSource,
)
from agentloom.contracts.task import (  # noqa: F401  (re-export
    TASK_EVENT_SCHEMA_VERSION,
    TASK_EVENT_TYPE,
    Pagination,
    TaskCreate,
    TaskEventRecord,
    TaskPage,
    TaskRecord,
    TaskTransition,
    WorkflowCompletionOutcome,
    WorkflowVerificationOutcome,
    task_event_payload_digest,
)
from agentloom.contracts.tool import (  # noqa: F401  (re-export
    TOOL_CALL_EVENT_SCHEMA_VERSION,
    TOOL_CALL_EVENT_TYPE,
    SandboxExecutionRequest,
    SandboxExecutionResult,
    ToolCallEventRecord,
    ToolExecutionRequest,
    ToolExecutionResult,
    tool_call_payload_digest,
    tool_parameter_digest,
)

__all__ = [
    "ContractModel",
    "Sha256Digest",
    "RiskLevel",
    "EscalatedRiskLevel",
    "ApprovalStatus",
    "SkillLifecycleState",
    "VerificationVerdict",
    "DetectionStageName",
    "TaskDetectionProducer",
    "ExperienceOutcome",
    "Severity",
    "TaskStatus",
    "CoordinationAgentName",
    "CoordinationPhase",
    "AgentIdentity",
    "CoordinationEvent",
    "CoordinationTrace",
    "SkillSource",
    "SkillEvaluation",
    "SkillManifest",
    "SkillCatalog",
    "SkillResolutionRequest",
    "ToolExecutionRequest",
    "ToolExecutionResult",
    "SandboxExecutionRequest",
    "SandboxExecutionResult",
    "ToolCallEventRecord",
    "tool_parameter_digest",
    "tool_call_payload_digest",
    "SandboxExecutionRequest",
    "SandboxExecutionResult",
    "RootCauseReport",
    "PatchArtifact",
    "VerificationRequest",
    "EvidenceRecord",
    "VerificationChecks",
    "VerificationResult",
    "SkillInvocationEvidenceRecord",
    "skill_invocation_payload_digest",
    "TaskEvidenceBundle",
    "SkillExecutionGrant",
    "SignedSkillExecutionGrant",
    "GrantIssuanceRequest",
    "ToolExecutionEnvelope",
    "GrantVerificationRequest",
    "Finding",
    "RiskReport",
    "RepairArtifactBundle",
    "DetectionResult",
    "DetectionReport",
    "TaskDetectionRecord",
    "ExperienceRecord",
    "RepairArtifactBundle",
    "DetectionResult",
    "DetectionReport",
    "ApprovalCreate",
    "ApprovalRecord",
    "ApprovalDecisionRequest",
    "TaskCreate",
    "TaskRecord",
    "TaskTransition",
    "TaskEventRecord",
    "task_event_payload_digest",
    "Pagination",
    "TaskPage",
    "WorkflowVerificationOutcome",
    "WorkflowCompletionOutcome",
    "TASK_EVENT_SCHEMA_VERSION",
    "TASK_EVENT_TYPE",
    "TOOL_CALL_EVENT_SCHEMA_VERSION",
    "TOOL_CALL_EVENT_TYPE",
    "SKILL_INVOCATION_SCHEMA_VERSION",
]

# Resolve cross-module forward references AFTER every peer submodule has
# been imported. Pydantic evaluates annotations lazily, so the forward
# refs to types defined in sibling modules are now safe to bind.
_ns = vars(sys.modules[__name__])
try:
    ContractModel.model_rebuild(_types_namespace=_ns)
except (NameError, AttributeError):
    pass
_ns = vars(sys.modules[__name__])
try:
    TaskEventRecord.model_rebuild(_types_namespace=_ns)
except (NameError, AttributeError):
    pass
_ns = vars(sys.modules[__name__])
try:
    TaskRecord.model_rebuild(_types_namespace=_ns)
except (NameError, AttributeError):
    pass
_ns = vars(sys.modules[__name__])
try:
    TaskPage.model_rebuild(_types_namespace=_ns)
except (NameError, AttributeError):
    pass
_ns = vars(sys.modules[__name__])
try:
    TaskEvidenceBundle.model_rebuild(_types_namespace=_ns)
except (NameError, AttributeError):
    pass
_ns = vars(sys.modules[__name__])
try:
    SkillInvocationEvidenceRecord.model_rebuild(_types_namespace=_ns)
except (NameError, AttributeError):
    pass
_ns = vars(sys.modules[__name__])
try:
    ToolExecutionEnvelope.model_rebuild(_types_namespace=_ns)
except (NameError, AttributeError):
    pass
_ns = vars(sys.modules[__name__])
try:
    GrantIssuanceRequest.model_rebuild(_types_namespace=_ns)
except (NameError, AttributeError):
    pass
_ns = vars(sys.modules[__name__])
try:
    RepairArtifactBundle.model_rebuild(_types_namespace=_ns)
except (NameError, AttributeError):
    pass
_ns = vars(sys.modules[__name__])
try:
    DetectionReport.model_rebuild(_types_namespace=_ns)
except (NameError, AttributeError):
    pass
_ns = vars(sys.modules[__name__])
try:
    TaskDetectionRecord.model_rebuild(_types_namespace=_ns)
except (NameError, AttributeError):
    pass
_ns = vars(sys.modules[__name__])
try:
    ToolCallEventRecord.model_rebuild(_types_namespace=_ns)
except (NameError, AttributeError):
    pass
_ns = vars(sys.modules[__name__])
try:
    SandboxExecutionRequest.model_rebuild(_types_namespace=_ns)
except (NameError, AttributeError):
    pass
_ns = vars(sys.modules[__name__])
try:
    SandboxExecutionResult.model_rebuild(_types_namespace=_ns)
except (NameError, AttributeError):
    pass