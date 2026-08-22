# scripts/dev

One-off operator scripts that are not part of the runtime, the test
suite, or the deployment flow. Each script under this directory has a
short lifespan (one or two release cycles) and exists because the work
it does is not worth automating into the public surface.

## historical-splits/

The four scripts in `historical-splits/` are the **methodology record**
for the package splits done in the P1 follow-up. They are **not
runnable** as-is:

- `split-contracts.py` and `split-live-repair.py` and
  `split-live-rollback.py` each take a hardcoded `pathlib.Path`
  pointing at the original file. By the time they were committed the
  original file had already been replaced with a 9-line re-export
  shim, so re-running them would either fail or wipe the package
  back to a duplicate of itself.
- `rewrite-test-results.py` is a historical snapshot of how
  `scripts/refresh-test-results.ps1` was generated. The PowerShell
  script is the canonical source of truth now; this Python file is
  only here so a future operator can see what the
  timing / platform / pytest-version normalization rules are supposed
  to do.

The value of these scripts is **not** "run them again". It is
"read them to learn the methodology". The four lessons encoded in
them are:

### 1. AST-walk before you slice

Every successful split started with a full `ast.parse` of the source
file and an enumeration of:

- `ast.ClassDef` nodes (one per public model / class)
- `ast.FunctionDef` nodes (one per top-level helper)
- `ast.AnnAssign` and `ast.Assign` nodes that bind module-level
  constants (e.g. `AgentName = Literal[...]`, `_MAX_PATCH_BYTES = 131072`)

Without the AST pass you cannot reason about cross-module
references; with it you can see exactly which class lives where and
which helper is "owned" by which class (because it is referenced
from a `@model_validator` body).

### 2. Class-block slicing must preserve the trailing newline

A subtle bug in the first iteration of the contracts split came from
slicing the source as `lines[node.lineno:next_class.lineno]`. That
range **includes** the helper functions that sit between two
classes, which led to the helper being emitted twice (once at the
end of the previous class, once at the start of the next). The fix
was to use `node.end_lineno` for the class body and have the AST
walker prepend any helpers explicitly, with a blank line between
helper and class.

### 3. Cycles need a structural break, not a hack

`live_rollback.py` had a true cycle: `models.py` needs
`_validate_role_event_chain` and `_rollback_binding` inside
`@model_validator` bodies, while `operations.py` needs
`LiveRollbackError`, `LiveRollbackResult`, `VerifiedRollbackEvidence`
at runtime (to instantiate them). The fix was **not** a
`TYPE_CHECKING` band-aid; it was to move the two model-coupled
helpers into `models.py`, where they belong architecturally. The
result: `operations.py` can import the model types at runtime
without a cycle.

### 4. Forward references in Pydantic v2 need a model_rebuild pass

When `from __future__ import annotations` is in effect (it is, in
every file), every Pydantic annotation is a string. Pydantic
resolves the strings lazily, and the resolution uses the model's
`__module__` namespace — which is the submodule, not the package.
`evidence.TaskEvidenceBundle.detections: list[TaskDetectionRecord]`
fails at first use because the submodule does not contain
`TaskDetectionRecord`. The fix is a single pass at the bottom of
`agentloom/contracts/__init__.py`:

```python
for _cls in ("TaskEvidenceBundle", "SkillInvocationEvidenceRecord", ...):
    _ns = vars(sys.modules[__name__])
    try:
        _cls.model_rebuild(_types_namespace=_ns)
    except (NameError, AttributeError):
        pass
```

`_types_namespace=vars(sys.modules[__name__])` gives Pydantic the
full package namespace to resolve cross-module forward references,
so the rebuild is the only place that needs to know about the
package layout. Submodules stay clean.

## What lives in the parent directory

- `scripts/refresh-test-results.ps1` — the canonical PowerShell
  implementation of the `test-results.txt` regenerator. The Python
  script in `historical-splits/` is its lineage, not its
  replacement.
- `scripts/bootstrap.ps1`, `scripts/verify-clean-reproduction.ps1`,
  `scripts/health-check.ps1` — AgentTeams Full-mode bootstrap
  scripts (Windows PowerShell). They predate this directory.

## When to add a new script here

Add a new file under `scripts/dev/` only if it is:

- A throwaway operator tool that exists to support a single
  refactor, doc sweep, or audit.
- Something the maintainer wants preserved in git history but
  not exposed to the runtime, the test suite, or the public
  deployment scripts.

Anything an end user (downstream package, evaluator, second-host
operator) might run should live at the `scripts/` root or under a
`scripts/<role>/` subdirectory. If a `scripts/dev/` script is
needed again, graduate it.

## When to delete a script here

Delete a script under `scripts/dev/` when:

- The work it supported has been released and the script is no
  longer needed even as a methodology record.
- The methodology has been folded into a real, runnable tool
  (e.g. a CLI subcommand under `python -m agentloom.cli`).
- The script references a file or path that no longer exists in
  the public-main tree, so reading it would mislead a future
  reader.

At the time of writing the four `historical-splits/` scripts are
the canonical methodology record. A future refactor that splits
another large file can either re-use them (after generalising the
hardcoded paths) or replace them with a single smaller helper.
