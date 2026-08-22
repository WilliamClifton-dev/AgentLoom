"""Split src/agentloom/live_repair.py (690 lines) into a live_repair/ package,
v3: per-module imports are computed from each class/function body's Name usage.
"""
import ast
import pathlib

SRC = pathlib.Path(r'D:\Projects\Agent-Infra\src\agentloom\live_repair.py')
text = SRC.read_text(encoding='utf-8')
tree = ast.parse(text)
lines = text.splitlines()

class_to_target = {
    "LiveRepairError":         "models.py",
    "AgentRoleEvent":          "models.py",
    "LiveRepairSourceFile":    "models.py",
    "LiveRepairCaseContext":   "models.py",
    "LiveRepairSubmission":    "models.py",
    "LiveRepairResult":        "result.py",
    "LiveRepairVerifier":      "verifier.py",
}
def_to_target = {
    "prepare_live_repair_case_context": "case.py",
    "_load_submission":                 "case.py",
    "_patch_paths":                     "case.py",
    "_safe_patch_path":                 "case.py",
    "_apply_patch":                     "case.py",
    "_write_evidence":                  "case.py",
    "_write_case_context":              "case.py",
    "main":                             "cli.py",
}

# Collect the module-level imports (for the new __init__ re-exports).
top_imports: list[ast.AST] = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]

# Find first class line.
first_class_line = next(n.lineno for n in tree.body if isinstance(n, ast.ClassDef))
header_lines = lines[0:first_class_line - 1]
header_text = "\n".join(header_lines)

# Get the source for each class/function.
def source_for(node: ast.AST) -> str:
    seg = ast.get_source_segment(text, node) or ast.unparse(node)
    return seg.rstrip() + "\n"

# Per-module body collector.
bodies: dict[str, list[str]] = {f: [] for f in set(class_to_target.values()) | set(def_to_target.values())}

# We need to know which top-level name references each class/function makes,
# so we can import the right cross-module names. Walk each function/class
# body and collect Name uses that are not builtins and not the class's own
# name or its method's parameters.
BUILTINS = {
    "Path", "PurePosixPath",  # actually imported, not builtins, but harmless
    "print", "len", "range", "open", "isinstance", "hasattr", "getattr",
    "setattr", "delattr", "type", "super", "object", "int", "str", "bool",
    "float", "list", "dict", "set", "tuple", "frozenset", "bytes", "bytearray",
    "None", "True", "False", "Exception", "RuntimeError", "ValueError",
    "TypeError", "NotImplementedError", "StopIteration", "OSError",
    "IOError", "FileNotFoundError", "PermissionError", "UnicodeDecodeError",
    "dataclass", "field", "asdict",
    "ConfigDict", "Field", "ValidationError", "field_validator", "model_validator",
    "ContractModel", "RepairArtifactBundle", "VerificationChecks", "VerificationResult",
    "CoordinationTrace",
    "argparse", "json", "shlex", "shutil", "subprocess", "sys", "sha256", "Literal",
    "DemoCase", "demo_case_fingerprint", "load_demo_case", "workspace_tree_digest",
    "MockRepairError", "_changed_paths", "_combine_results", "_file_hash",
    "_run_case_command", "_target_command", "_test_results", "_write_model",
    "dataclass",
}

# Collect all imported names (so we don't try to re-import them).
imported_names: set[str] = set()
for n in top_imports:
    for alias in n.names:
        imported_names.add(alias.asname or alias.name.split(".")[0])
# Also include the class names and function names defined at top level.
for n in tree.body:
    if isinstance(n, ast.ClassDef):
        imported_names.add(n.name)
    elif isinstance(n, ast.FunctionDef):
        imported_names.add(n.name)
    elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
        imported_names.add(n.target.id)
    elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
        imported_names.add(n.targets[0].id)

# Also include the Literal aliases we are about to move to _types.
imported_names.update({"AgentName", "ModelName", "ProviderName"})

# Walk each class/function and collect referenced Name nodes that are NOT
# builtins / NOT imported.
def collect_names(node: ast.AST) -> set[str]:
    used: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            used.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            # Only the root Name counts; ignore attribute chains.
            pass
    return used

needs: dict[str, set[str]] = {f: set() for f in bodies}
# Names that come from sibling submodules.
sibling_names: dict[str, str] = {
    "LiveRepairError":          "agentloom.live_repair.models",
    "AgentRoleEvent":           "agentloom.live_repair.models",
    "LiveRepairSourceFile":     "agentloom.live_repair.models",
    "LiveRepairCaseContext":    "agentloom.live_repair.models",
    "LiveRepairSubmission":     "agentloom.live_repair.models",
    "LiveRepairResult":         "agentloom.live_repair.result",
    "LiveRepairVerifier":       "agentloom.live_repair.verifier",
    "prepare_live_repair_case_context": "agentloom.live_repair.case",
    "_load_submission":         "agentloom.live_repair.case",
    "_patch_paths":             "agentloom.live_repair.case",
    "_safe_patch_path":         "agentloom.live_repair.case",
    "_apply_patch":             "agentloom.live_repair.case",
    "_write_evidence":          "agentloom.live_repair.case",
    "_write_case_context":      "agentloom.live_repair.case",
    "main":                     "agentloom.live_repair.cli",
}

for n in tree.body:
    if isinstance(n, ast.ClassDef) and n.name in class_to_target:
        target = class_to_target[n.name]
        used = collect_names(n)
        for name in used - imported_names - BUILTINS:
            if name in sibling_names and sibling_names[name] != f"agentloom.live_repair.{target}":
                needs[target].add(name)
    elif isinstance(n, ast.FunctionDef) and n.name in def_to_target:
        target = def_to_target[n.name]
        used = collect_names(n)
        for name in used - imported_names - BUILTINS:
            if name in sibling_names and sibling_names[name] != f"agentloom.live_repair.{target}":
                needs[target].add(name)

# Group sibling imports by target module.
cross_by_target: dict[str, dict[str, set[str]]] = {f: {} for f in bodies}
for target, names in needs.items():
    for name in names:
        mod = sibling_names[name]
        cross_by_target[target].setdefault(mod, set()).add(name)

# Also: each module that uses AgentName / ModelName / ProviderName (in body
# strings) needs them from _types. But the original header (with the Literal
# block) was at the top of every module — we stripped it. So add _types
# imports for every module that has those names in their text.
for module_name in bodies:
    full_body = "\n".join(bodies[module_name])
    for name in ("AgentName", "ModelName", "ProviderName"):
        if name in full_body:
            cross_by_target[module_name].setdefault("agentloom.live_repair._types", set()).add(name)

# Write modules.
PKG = pathlib.Path(r'D:\Projects\Agent-Infra\src/agentloom/live_repair')
PKG.mkdir(parents=True, exist_ok=True)

# Build the import block for each target module.
def build_imports(target: str) -> str:
    parts = [header_text, ""]
    # Sibling imports, grouped by module.
    for mod, names in sorted(cross_by_target[target].items()):
        names = sorted(names)
        if len(names) == 1:
            parts.append(f"from {mod} import {names[0]}  # noqa: F401  (cross-module)")
        else:
            parts.append(f"from {mod} import (  # noqa: F401  (cross-module)")
            for n in names:
                parts.append(f"    {n},")
            parts.append(")")
            parts.append("")
    return "\n".join(parts) + "\n"

# Assign bodies.
for n in tree.body:
    if isinstance(n, ast.ClassDef) and n.name in class_to_target:
        bodies[class_to_target[n.name]].append(source_for(n))
    elif isinstance(n, ast.FunctionDef) and n.name in def_to_target:
        bodies[def_to_target[n.name]].append(source_for(n))

for module_name, parts in bodies.items():
    imports = build_imports(module_name)
    body = "\n".join(parts)
    full = imports + "\n" + body
    (PKG / module_name).write_text(full, encoding="utf-8", newline="\n")

# _types.py
types_text = '''"""Public type aliases for the live repair package."""
from __future__ import annotations

from typing import Literal

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
'''
(PKG / "_types.py").write_text(types_text, encoding="utf-8", newline="\n")

# __init__.py
init = '''"""Live repair package split out of the legacy live_repair.py monolith."""
from __future__ import annotations

from agentloom.live_repair._types import AgentName, ModelName, ProviderName  # noqa: F401  (re-export)
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
    "main",
    "prepare_live_repair_case_context",
]
'''
(PKG / "__init__.py").write_text(init, encoding="utf-8", newline="\n")

# Shim
shim = '''"""Backward-compat re-export shim.

The live_repair module was split into a package on 2026-08-22. Prefer
importing from `agentloom.live_repair` (the package) or from the specific
submodule. This shim keeps every existing `from agentloom.live_repair
import X` call site working without churn.
"""
from agentloom.live_repair import *  # noqa: F401,F403
from agentloom.live_repair import __all__  # noqa: F401
'''
SRC.write_text(shim, encoding="utf-8", newline="\n")

print("OK")
for p in sorted(PKG.iterdir()):
    print("  ", p.name, len(p.read_text(encoding="utf-8").splitlines()), "lines")
print("  shim:", SRC.name, len(SRC.read_text(encoding="utf-8").splitlines()), "lines")
