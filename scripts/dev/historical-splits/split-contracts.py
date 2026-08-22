"""Split src/agentloom/contracts.py into a contracts/ package, v3.

Approach:
  1. Parse the file with `ast` to enumerate top-level ClassDef, FunctionDef,
     AnnAssign, Import, and ImportFrom nodes in order.
  2. For each ClassDef, collect the type/function/const nodes that appear
     BEFORE it in the source and are not already claimed by an earlier class
     whose source range they sit within.
  3. Group by the planned target module.
  4. Emit each module with a uniform header + cross-module imports.
  5. Emit a __init__ that re-exports every public name and a shim contracts.py
     that keeps `from agentloom.contracts import X` working.
"""
import ast
import pathlib

SRC = pathlib.Path(r'D:\Projects\Agent-Infra\src\agentloom\contracts.py')
text = SRC.read_text(encoding='utf-8')
tree = ast.parse(text)
# Map each ClassDef to its end line (1-based, inclusive)
class_to_end: dict[str, int] = {}
for node in tree.body:
    if isinstance(node, ast.ClassDef):
        class_to_end[node.name] = node.end_lineno

# Walk in source order. For each non-class top-level node, assign it to the
# FIRST ClassDef whose start line is GREATER than the node's end line.
nodes_in_order: list[tuple[int, int, ast.AST]] = []
for node in tree.body:
    nodes_in_order.append((node.lineno, node.end_lineno or node.lineno, node))

class_starts_sorted = sorted(((n.lineno, n.name) for n in tree.body if isinstance(n, ast.ClassDef)))

def owner_of(start_line: int) -> str:
    # First class whose lineno > start_line
    for cls_line, cls_name in class_starts_sorted:
        if cls_line > start_line:
            return cls_name
    return ""  # after the last class

# Collect helpers/constants/aliases per owner class.
class_owners: dict[str, list[ast.AST]] = {name: [] for _, name in class_starts_sorted}
class_owners["__pre__"] = []  # top-level aliases and imports that sit before the first class
for node in tree.body:
    if isinstance(node, ast.ClassDef):
        continue
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        continue  # imports go to _base.py
    owner = owner_of(node.lineno)
    if owner:
        class_owners[owner].append(node)
    else:
        class_owners["__pre__"].append(node)

# ---- Slice the source: for each class, get [cls.lineno, next_cls.lineno) ----
class_blocks: dict[str, str] = {}
sorted_class_nodes = sorted(
    (n for n in tree.body if isinstance(n, ast.ClassDef)),
    key=lambda n: n.lineno,
)
lines = text.splitlines()
for i, node in enumerate(sorted_class_nodes):
    # End at the class's own end_lineno. Helpers between this class and the
    # next one are handled via class_owners and prepended to the next class.
    start = node.lineno - 1
    end = (node.end_lineno or node.lineno)
    block = "\n".join(lines[start:end])
    # Prepend any helpers that belong to this class, with a blank line between
    # each helper and the class definition.
    helpers = class_owners.get(node.name, [])
    if helpers:
        helper_src_parts = []
        for h in helpers:
            seg = ast.get_source_segment(text, h) or ast.unparse(h)
            helper_src_parts.append(seg)
        helper_src = "\n\n".join(helper_src_parts) + "\n\n"
        block = helper_src + block
    # Ensure block ends with a single trailing newline so concatenation with the
    # next block creates a blank line between them.
    if not block.endswith("\n"):
        block = block + "\n"
    class_blocks[node.name] = block

# Helpers before the first class (e.g. the Literal aliases). We use
# `ast.get_source_segment` to preserve the original multi-line layout of
# Literal declarations and the surrounding formatting.
pre_helpers = class_owners.get("__pre__", [])
pre_src = "\n".join(ast.get_source_segment(text, h) or ast.unparse(h) for h in pre_helpers) + "\n\n" if pre_helpers else ""

# ---- assignment ----------------------------------------------------------
assignment = {
    "ContractModel": "_base.py",
    "AgentIdentity": "identity.py", "CoordinationEvent": "identity.py", "CoordinationTrace": "identity.py",
    "SkillSource": "skill.py", "SkillEvaluation": "skill.py", "SkillManifest": "skill.py",
    "SkillCatalog": "skill.py", "SkillResolutionRequest": "skill.py",
    "ToolExecutionRequest": "tool.py", "ToolExecutionResult": "tool.py",
    "SandboxExecutionRequest": "tool.py", "SandboxExecutionResult": "tool.py",
    "ToolCallEventRecord": "tool.py",
    "RootCauseReport": "evidence.py", "PatchArtifact": "evidence.py",
    "VerificationRequest": "evidence.py", "EvidenceRecord": "evidence.py",
    "VerificationChecks": "evidence.py", "VerificationResult": "evidence.py",
    "SkillInvocationEvidenceRecord": "evidence.py", "TaskEvidenceBundle": "evidence.py",
    "SkillExecutionGrant": "grant.py", "SignedSkillExecutionGrant": "grant.py",
    "GrantIssuanceRequest": "grant.py", "ToolExecutionEnvelope": "grant.py",
    "GrantVerificationRequest": "grant.py",
    "Finding": "risk.py", "RiskReport": "risk.py",
    "RepairArtifactBundle": "repair.py", "DetectionResult": "repair.py",
    "DetectionReport": "repair.py", "TaskDetectionRecord": "repair.py",
    "ExperienceRecord": "repair.py",
    "ApprovalCreate": "approval.py", "ApprovalRecord": "approval.py",
    "ApprovalDecisionRequest": "approval.py",
    "TaskCreate": "task.py", "TaskRecord": "task.py", "TaskTransition": "task.py",
    "TaskEventRecord": "task.py", "Pagination": "task.py", "TaskPage": "task.py",
}

# ---- headers -------------------------------------------------------------
def header(doc_topic: str) -> str:
    return f'''"""Boundary contract submodule: {doc_topic}."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from agentloom.contracts._base import (
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
'''

cross_imports: dict[str, str] = {
    "grant.py":    "from agentloom.contracts.tool import ToolExecutionRequest, ToolExecutionResult  # noqa: F401  (forward refs)\n",
    "evidence.py": (
        "from agentloom.contracts.tool import (\n"
        "    ToolExecutionRequest, ToolExecutionResult, ToolCallEventRecord,\n"
        ")\n"
        "from agentloom.contracts.grant import (\n"
        "    SkillExecutionGrant, SignedSkillExecutionGrant, ToolExecutionEnvelope,\n"
        "    GrantIssuanceRequest,\n"
        ")\n"
        # NOTE: do NOT import repair here; that would create a circular import. Forward
        # refs to TaskDetectionRecord/ExperienceRecord are resolved by the explicit
        # TaskEvidenceBundle.model_rebuild(_types_namespace=...) call at the bottom of
        # __init__.py, which uses the full contracts package namespace.\n
    ),
    "repair.py": (
        "from agentloom.contracts.evidence import (\n"
        "    RootCauseReport, PatchArtifact, VerificationResult,\n"
        "    EvidenceRecord, VerificationRequest,\n"
        ")\n"
        "from agentloom.contracts.risk import Finding, RiskReport  # noqa: F401  (forward refs)\n"
    ),
    "task.py": (
        "from agentloom.contracts.evidence import TaskEvidenceBundle, EvidenceRecord  # noqa: F401  (forward refs)\n"
    ),
    "approval.py": "",
    "skill.py": "",
    "identity.py": "",
    "risk.py": "",
    "tool.py": "",
}

PKG = pathlib.Path(r'D:\Projects\Agent-Infra\src\agentloom\contracts')
PKG.mkdir(parents=True, exist_ok=True)

# ---- _base ---------------------------------------------------------------
base_body = (
    '"""Boundary contract base types and Literal aliases."""\n'
    "from __future__ import annotations\n"
    "from typing import Literal\n"
    "from pydantic import BaseModel, ConfigDict\n\n"
    + pre_src
    + class_blocks["ContractModel"]
)
(PKG / "_base.py").write_text(base_body, encoding="utf-8", newline="\n")

# ---- other modules -------------------------------------------------------
public_names: dict[str, list[str]] = {}
# Accumulate bodies per target file. Header is emitted only on the first write.
file_bodies: dict[str, str] = {t: "" for t in set(assignment.values()) if t != "_base.py"}
import re
for cls_name, target in assignment.items():
    if cls_name == "ContractModel":
        continue
    body = class_blocks[cls_name]
    file_bodies[target] += body
    public_names.setdefault(target, [])
    public_names[target] += re.findall(r"^class (\w+)", body, re.MULTILINE)
    public_names[target] += re.findall(r"^def (\w+)", body, re.MULTILINE)
    public_names[target] += re.findall(r"^([A-Z]\w*)\s*=\s*Literal", body, re.MULTILINE)
    public_names[target] += re.findall(r"^([A-Z_][A-Z0-9_]+)\s*[:=]\s*", body, re.MULTILINE)
# Names that need explicit model_rebuild() because their forward references
# can be evaluated before a peer module is fully loaded.
rebuild_targets: dict[str, list[str]] = {
    "evidence.py": ["TaskEvidenceBundle", "SkillInvocationEvidenceRecord"],
    "grant.py":    ["ToolExecutionEnvelope", "GrantIssuanceRequest"],
    "repair.py":   ["RepairArtifactBundle", "DetectionReport", "TaskDetectionRecord"],
    "task.py":     ["TaskEventRecord", "TaskRecord", "TaskPage"],
    "tool.py":     ["ToolCallEventRecord", "SandboxExecutionRequest", "SandboxExecutionResult"],
}

for target, body in file_bodies.items():
    header_text = header(target.replace(".py", ""))
    cross = cross_imports.get(target, "")
    full = header_text + cross + body
    (PKG / target).write_text(full, encoding="utf-8", newline="\n")

# ---- __init__ ------------------------------------------------------------
init = ['"""AgentLoom boundary contracts, split by responsibility."""', ""]
init.append("from __future__ import annotations")
init.append("")
init.append("from agentloom.contracts._base import (  # noqa: F401  (re-export")
for n in [
    "ContractModel", "Sha256Digest", "RiskLevel", "EscalatedRiskLevel",
    "ApprovalStatus", "SkillLifecycleState", "VerificationVerdict",
    "DetectionStageName", "TaskDetectionProducer", "ExperienceOutcome",
    "Severity", "TaskStatus", "CoordinationAgentName", "CoordinationPhase",
]:
    init.append(f"    {n},")
init.append(")")
init.append("")
for module_name in ["identity", "skill", "tool", "evidence", "grant", "risk", "repair", "approval", "task"]:
    names = sorted(set(public_names.get(module_name + ".py", [])))
    if not names:
        continue
    init.append(f"from agentloom.contracts.{module_name} import (  # noqa: F401  (re-export")
    for n in names:
        init.append(f"    {n},")
    init.append(")")
    init.append("")
init.append("__all__ = [")
for n in [
    "ContractModel", "Sha256Digest", "RiskLevel", "EscalatedRiskLevel",
    "ApprovalStatus", "SkillLifecycleState", "VerificationVerdict",
    "DetectionStageName", "TaskDetectionProducer", "ExperienceOutcome",
    "Severity", "TaskStatus", "CoordinationAgentName", "CoordinationPhase",
    "AgentIdentity", "CoordinationEvent", "CoordinationTrace",
    "SkillSource", "SkillEvaluation", "SkillManifest", "SkillCatalog",
    "SkillResolutionRequest",
    "ToolExecutionRequest", "ToolExecutionResult",
    "SandboxExecutionRequest", "SandboxExecutionResult",
    "ToolCallEventRecord", "tool_parameter_digest", "tool_call_payload_digest", "SandboxExecutionRequest", "SandboxExecutionResult",
    "RootCauseReport", "PatchArtifact", "VerificationRequest",
    "EvidenceRecord", "VerificationChecks", "VerificationResult",
    "SkillInvocationEvidenceRecord", "skill_invocation_payload_digest",
    "TaskEvidenceBundle",
    "SkillExecutionGrant", "SignedSkillExecutionGrant",
    "GrantIssuanceRequest", "ToolExecutionEnvelope", "GrantVerificationRequest",
    "Finding", "RiskReport",
    "RepairArtifactBundle", "DetectionResult", "DetectionReport",
    "TaskDetectionRecord", "ExperienceRecord", "RepairArtifactBundle", "DetectionResult", "DetectionReport",
    "ApprovalCreate", "ApprovalRecord", "ApprovalDecisionRequest",
    "TaskCreate", "TaskRecord", "TaskTransition",
    "TaskEventRecord", "task_event_payload_digest", "Pagination", "TaskPage",
    "WorkflowVerificationOutcome", "WorkflowCompletionOutcome",
    "TASK_EVENT_SCHEMA_VERSION", "TASK_EVENT_TYPE",
    "TOOL_CALL_EVENT_SCHEMA_VERSION", "TOOL_CALL_EVENT_TYPE",
    "SKILL_INVOCATION_SCHEMA_VERSION",
]:
    init.append(f'    "{n}",')
init.append("]")
init.append("")
init.append("# Resolve cross-module forward references AFTER every peer submodule has")
init.append("# been imported. Pydantic evaluates annotations lazily, so the forward")
init.append("# refs to types defined in sibling modules are now safe to bind.")
for _cls in (
    "ContractModel",
    "TaskEventRecord", "TaskRecord", "TaskPage",
    "TaskEvidenceBundle", "SkillInvocationEvidenceRecord",
    "ToolExecutionEnvelope", "GrantIssuanceRequest",
    "RepairArtifactBundle", "DetectionReport", "TaskDetectionRecord",
    "ToolCallEventRecord", "SandboxExecutionRequest", "SandboxExecutionResult",
):
    init.append(f"_ns = vars(sys.modules[__name__])")
    init.append(f"try:")
    init.append(f"    {_cls}.model_rebuild(_types_namespace=_ns)")
    init.append(f"except (NameError, AttributeError):")
    init.append(f"    pass")
(PKG / "__init__.py").write_text("\n".join(init), encoding="utf-8", newline="\n")

shim = '''"""Backward-compat re-export shim.

The contracts package was split into per-responsibility submodules on 2026-08-21.
Prefer importing from `agentloom.contracts` (the package) or from the
specific submodule (`agentloom.contracts.tool`, `agentloom.contracts.grant`,
etc.). This shim keeps every existing `from agentloom.contracts import X`
call working without code churn at every call site.
"""
from agentloom.contracts import *  # noqa: F401,F403
from agentloom.contracts import __all__  # noqa: F401
'''
SRC.write_text(shim, encoding="utf-8", newline="\n")

print("OK")
for p in sorted(PKG.iterdir()):
    print("  ", p.name, len(p.read_text(encoding="utf-8").splitlines()), "lines")
print("  shim:", SRC.name, len(SRC.read_text(encoding="utf-8").splitlines()), "lines")
