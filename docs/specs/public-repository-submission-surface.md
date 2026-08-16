# Public repository submission surface specification

## Purpose

Make the Chinese-default `README.md` and English `README.en.md` truthful,
concise entry points for competition reviewers and downstream deployers after
Tasks 17 and 18.

## Current facts

- Runtime: AgentTeams v1.1.2.
- Current live path: Administrator -> Manager -> Investigator -> Verifier ->
  authenticated Higress -> Policy Broker -> immutable Docker pytest sandbox.
- Current paid evidence Provider: `minimax-cn / MiniMax-M2.5`.
- Result: Task 24 completed all six local/governed cells; Task 17 separately
  proves exactly one delegated governed `SUCCEEDED` ToolCall.
- Current public-main gate: 379 pytest passed, 0 skipped, with the immutable
  Docker sandbox tests enabled. The frozen `v0.1.0` gate is 375 passed with
  3 opt-in Docker tests skipped; clean-clone Lite evidence is 339 passed,
  0 failed, 3 skipped. Ruff, strict mypy, pip-audit, syntax, migration, diff,
  and secret checks passed.
- Skill catalog: `code-review-and-quality` and team-original
  `patch-scope-validator` v1.0.1 are `PUBLISHED`; four upstream Skills are
  `QUARANTINED`; three original-Skill invocations strictly reopen.
- Human L2 approval is `APPROVED`; PR #1141 remains `OPEN`.
- The final P0 package, real recording, anonymous public playback, annotated
  tag, and formal Release are verified. Competition-page submission remains
  Human-owned; second-host Full reproduction remains a separate checkpoint.

## Structure

Both READMEs must present, in this order:

1. Product definition and current status.
2. Competition scope and evidence baseline.
3. Architecture and trust boundaries.
4. Quick start for model-free local verification.
5. Full AgentTeams deployment and Provider Profile links.
6. Implemented capabilities and evidence.
7. Historical evidence and reproduction paths, clearly labelled.
8. Remaining roadmap, provenance, and security.

## Provider boundary

The public surface must distinguish validation, configuration, connection
testing, and strict AgentTeams E2E. A secret-free Provider Profile validates
only configuration shape. It cannot prove that every OpenAI-compatible model
supports role messages, streaming, tool calling, reasoning parameters, context
limits, or repair workflows.

## Acceptance checks

- English and Chinese current-state facts are equivalent.
- No first-party current-run claim names Qwen, DeepSeek, or StepFun.
- Historical provider evidence is retained and explicitly labelled historical.
- No stale 146/175/182 test count or all-five-Skills-quarantined claim remains
  outside an explicitly quoted historical record.
- Model-free commands make no paid calls; paid probes require explicit opt-in.
- Relative links resolve in the worktree.
- Completed publication facts and the remaining Human/external checkpoints are
  distinguished explicitly.
