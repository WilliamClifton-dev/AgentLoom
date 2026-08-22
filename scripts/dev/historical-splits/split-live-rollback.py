"""v3: compute imported_names per-target, excluding names that moved to sibling submodules."""
import ast
import pathlib

SRC = pathlib.Path(r'D:\Projects\Agent-Infra\src\agentloom/live_rollback.py')
text = SRC.read_text(encoding='utf-8')
tree = ast.parse(text)
lines = text.splitlines()

class_to_target = {
    "LiveRollbackError":            "models.py",
    "RollbackRoleEvent":            "models.py",
    "RollbackPlan":                 "models.py",
    "LiveRollbackSubmission":       "models.py",
    "LiveRollbackResult":           "models.py",
    "RollbackFailureEvidence":      "models.py",
    "RollbackExecutionEvidence":    "models.py",
    "VerifiedRollbackEvidence":     "models.py",
    "RollbackEvidenceSummary":      "models.py",
    "RollbackEvidenceService":      "operations.py",
    "LiveRollbackVerifier":         "operations.py",
}
def_to_target = {
    "_validate_role_event_chain":   "models.py",
    "_rollback_binding":            "models.py",
    "_load_submission":             "operations.py",
    "_constant_hash_matches":       "operations.py",
    "_build_approved_snapshot":     "operations.py",
    "_run_target_checks":           "operations.py",
    "_run_approved_checks":         "operations.py",
    "_render_results":              "operations.py",
    "_write_evidence":              "operations.py",
}

first_class_line = next(n.lineno for n in tree.body if isinstance(n, ast.ClassDef))
header_text = "\n".join(lines[0:first_class_line - 1])

def source_for(node: ast.AST) -> str:
    seg = ast.get_source_segment(text, node) or ast.unparse(node)
    return seg.rstrip() + "\n"

# Per-target body.
bodies: dict[str, list[str]] = {f: [] for f in set(class_to_target.values()) | set(def_to_target.values())}
for n in tree.body:
    if isinstance(n, ast.ClassDef) and n.name in class_to_target:
        bodies[class_to_target[n.name]].append(source_for(n))
    elif isinstance(n, ast.FunctionDef) and n.name in def_to_target:
        bodies[def_to_target[n.name]].append(source_for(n))

# Names that are defined in the SAME target module (so don't need cross-import).
same_module_names: dict[str, set[str]] = {f: set() for f in bodies}
for class_name, target in class_to_target.items():
    same_module_names[target].add(class_name)
for func_name, target in def_to_target.items():
    same_module_names[target].add(func_name)

# Names that come from the original file's header (imports, module constants).
header_imports: set[str] = set()
for n in tree.body:
    if isinstance(n, ast.Import):
        for alias in n.names:
            header_imports.add(alias.asname or alias.name.split(".")[0])
    elif isinstance(n, ast.ImportFrom):
        for alias in n.names:
            header_imports.add(alias.asname or alias.name)
    elif n.lineno >= first_class_line:
        continue
    elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
        header_imports.add(n.targets[0].id)

# Compute cross-imports per target.
sibling_names = {
    "LiveRollbackError":            "agentloom.live_rollback.models",
    "RollbackRoleEvent":            "agentloom.live_rollback.models",
    "RollbackPlan":                 "agentloom.live_rollback.models",
    "LiveRollbackSubmission":       "agentloom.live_rollback.models",
    "LiveRollbackResult":           "agentloom.live_rollback.models",
    "RollbackFailureEvidence":      "agentloom.live_rollback.models",
    "RollbackExecutionEvidence":    "agentloom.live_rollback.models",
    "VerifiedRollbackEvidence":     "agentloom.live_rollback.models",
    "RollbackEvidenceSummary":      "agentloom.live_rollback.models",
    "RollbackEvidenceService":      "agentloom.live_rollback.operations",
    "LiveRollbackVerifier":         "agentloom.live_rollback.operations",
}

def collect_names(node: ast.AST) -> set[str]:
    used = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            used.add(sub.id)
    return used

cross_by_target: dict[str, dict[str, set[str]]] = {f: {} for f in bodies}
for n in tree.body:
    if isinstance(n, ast.ClassDef) and n.name in class_to_target:
        target = class_to_target[n.name]
        used = collect_names(n)
        for name in used - header_imports - same_module_names[target]:
            if name in sibling_names and sibling_names[name] != f"agentloom.live_rollback.{target}":
                cross_by_target[target].setdefault(sibling_names[name], set()).add(name)
    elif isinstance(n, ast.FunctionDef) and n.name in def_to_target:
        target = def_to_target[n.name]
        used = collect_names(n)
        for name in used - header_imports - same_module_names[target]:
            if name in sibling_names and sibling_names[name] != f"agentloom.live_rollback.{target}":
                cross_by_target[target].setdefault(sibling_names[name], set()).add(name)

PKG = pathlib.Path(r'D:\Projects\Agent-Infra\src/agentloom/live_rollback')
PKG.mkdir(parents=True, exist_ok=True)

def build_imports(target: str) -> str:
    parts = [header_text, ""]
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

for module_name, parts in bodies.items():
    imports = build_imports(module_name)
    body = "\n".join(parts)
    full = imports + "\n" + body
    (PKG / module_name).write_text(full, encoding="utf-8", newline="\n")

# Re-add @dataclass decorators that get_source_segment skipped.
orig_class_decos: dict[str, list[ast.AST]] = {n.name: n.decorator_list for n in tree.body if isinstance(n, ast.ClassDef)}
for module_name in bodies:
    path = PKG / module_name
    src_text = path.read_text(encoding="utf-8")
    for class_name, decos in orig_class_decos.items():
        if not decos:
            continue
        if f"class {class_name}(" not in src_text:
            continue
        deco_text = "\n".join(f"@{ast.unparse(d)}" for d in decos) + "\n"
        if "@dataclass" in src_text.split(f"class {class_name}(")[0][-300:]:
            continue
        src_text = src_text.replace(f"class {class_name}(", deco_text + f"class {class_name}(", 1)
    path.write_text(src_text, encoding="utf-8", newline="\n")

# Ensure `from dataclasses import dataclass` is imported in models.py.
models_text = (PKG / "models.py").read_text(encoding="utf-8")
if "from dataclasses import dataclass" not in models_text:
    models_text = models_text.replace(
        "from __future__ import annotations\n",
        "from __future__ import annotations\n\nfrom dataclasses import dataclass\n",
        1,
    )
    (PKG / "models.py").write_text(models_text, encoding="utf-8", newline="\n")

# __init__.py
init = '''"""Live rollback package split out of the legacy live_rollback.py monolith."""
from __future__ import annotations

from agentloom.live_rollback.models import (  # noqa: F401  (re-export
    LiveRollbackError,
    LiveRollbackResult,
    LiveRollbackSubmission,
    RollbackEvidenceSummary,
    RollbackExecutionEvidence,
    RollbackFailureEvidence,
    RollbackPlan,
    RollbackRoleEvent,
    VerifiedRollbackEvidence,
)
from agentloom.live_rollback.operations import (  # noqa: F401  (re-export
    LiveRollbackVerifier,
    RollbackEvidenceService,
)

__all__ = [
    "LiveRollbackError",
    "LiveRollbackResult",
    "LiveRollbackSubmission",
    "LiveRollbackVerifier",
    "RollbackEvidenceService",
    "RollbackEvidenceSummary",
    "RollbackExecutionEvidence",
    "RollbackFailureEvidence",
    "RollbackPlan",
    "RollbackRoleEvent",
    "VerifiedRollbackEvidence",
]
'''
(PKG / "__init__.py").write_text(init, encoding="utf-8", newline="\n")

# Shim
shim = '''"""Backward-compat re-export shim.

The live_rollback module was split into a package on 2026-08-22. Prefer
importing from `agentloom.live_rollback` (the package) or from the
specific submodule. This shim keeps every existing
`from agentloom.live_rollback import X` call site working without churn.
"""
from agentloom.live_rollback import *  # noqa: F401,F403
from agentloom.live_rollback import __all__  # noqa: F401
'''
SRC.write_text(shim, encoding="utf-8", newline="\n")

print("OK")
for p in sorted(PKG.iterdir()):
    print("  ", p.name, len(p.read_text(encoding="utf-8").splitlines()), "lines")
print("  shim:", SRC.name, len(SRC.read_text(encoding="utf-8").splitlines()), "lines")
