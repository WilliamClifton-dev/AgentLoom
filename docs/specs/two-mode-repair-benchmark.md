# Two-mode repair benchmark specification

## Objective

Produce one versioned, replayable comparison across three fixed repair cases
without relabelling deterministic fixtures or historical Provider runs as live
AgentTeams evidence.

## Modes

`LOCAL_DETERMINISTIC` is the model-free reproducibility control. It runs the
manifest-defined expected patch through the normal AgentLoom task workflow,
Implementer checks, independent Verifier workspace, hidden tests, static checks,
and three-layer Evidence. It is not an AgentTeams or model-quality claim.

`AGENTTEAMS_GOVERNED` is a live repair run. MiniMax drives the real AgentTeams
Manager, Investigator, Implementer, and Verifier identities. A passing record
requires all of the following, bound to the same fixed Case:

1. strict Matrix handoff events and role-owned repair artifacts;
2. independent host revalidation of the submitted patch, including hidden tests;
3. a final Verifier ToolCall through Higress, Policy Broker, and the pinned
   Docker sandbox on the patched workspace.

The final governed ToolCall may be dispatched deterministically from the real
Verifier Worker after the model-generated repair. This preserves the security
boundary while avoiding a second model decision that adds no repair evidence.

## Dataset

The suite contains exactly three team-owned Apache-2.0 synthetic defects:

- `severity-normalization`;
- `pagination-boundary`;
- `retry-delay-cap`.

The suite manifest is versioned and records a SHA-256 Case fingerprint covering
the manifest, provenance, issue, source snapshot, expected patch, and hidden
tests. Any fixture change creates a different benchmark identity.

## Result contract

Every mode/Case cell records:

- suite ID/version/digest and Case ID/fingerprint;
- exact mode and `PASSED`, `FAILED`, or `NOT_RUN` status;
- Provider/model only when a model was actually used;
- start/end timestamps and measured elapsed time when executed;
- token, cost, LLM latency, and tool latency only when the runtime supplied a
  real measurement;
- immutable evidence references and SHA-256 digests for every passing claim;
- a bounded reason for `FAILED` or `NOT_RUN`.

The matrix contains six cells. `NOT_RUN` is data, not success. A suite is
complete only when all six cells were executed; only then may the architecture
checklist item be checked.

### AgentTeams v1.1.2 transport boundary

The live runner must use commands that are actually present in the pinned
Worker image. Cross-room assignments use CoPaw's `copaw channels send` command
with the exact Team Room, target user, and UTF-8/Base64-bound message body.
Shared artifacts use the Worker image's configured MinIO alias and `mc cp` for
allowlisted objects. The unpinned `filesync` command is not part of the
AgentTeams v1.1.2 image and must not appear in a live prompt or evidence claim.

The Worker image is not the test authority and does not include the repository's
pytest environment. Investigator and Implementer may report analysis, patch,
and static checks only. Verifier may return `UNCERTAIN` when Worker-local test
execution is unavailable, with all unrun test checks set to false. The final
`PASSED` verdict is then produced by the independent host verifier and bound to
the pinned Docker ToolCall; the original Agent `UNCERTAIN` result is preserved
as a separate artifact and is never overwritten.

## Provider boundary

Maintainer-paid live runs use only `minimax-cn` / `MiniMax-M2.5`. Qwen,
DeepSeek, and StepFun evidence remains historical and is forbidden as input to
this benchmark. Downstream administrators may run a separate suite with their
own approved Provider Profile, but those results must use a distinct benchmark
run ID and cannot be merged into the maintainer matrix.

## Acceptance criteria

- The suite loader rejects fewer than three or more than five cases, duplicate
  cases, fingerprint drift, unsafe paths, and unknown fields.
- Result contracts reject model metadata on local runs, missing MiniMax metadata
  on executed governed runs, fabricated metrics, passing cells without evidence,
  duplicate mode/Case cells, and mixed suites.
- The live repair runner is manifest-driven; it contains no pagination-specific
  source path, issue, command, or patch header.
- The governed sandbox fixture uses the Case working directory, test command,
  allowlisted paths, and workspace digest rather than a fixed target file.
- Three local runs and three MiniMax AgentTeams governed runs produce a complete
  six-cell report, or incomplete cells remain explicitly `NOT_RUN`.
- Focused tests, full pytest, Ruff, strict mypy, dependency audit, Alembic
  single-head check, script parsing, diff check, and secret scan pass.
