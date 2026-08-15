# AgentLoom model handoff

Updated: 2026-08-16 +08:00

This is the entry point for another coding model continuing AgentLoom. Treat
the current worktree, `.codex/plan-runs/agentloom-mvp/state.md`, and immutable
evidence as authoritative. Older chat summaries and task reports are historical
context, not the current completion state.

## Objective

Preserve the completed preliminary-stage engineering audit and finish only the
remaining Human/external delivery actions with direct proof.

Engineering Tasks 1-28 are complete. Recording/upload,
public accessibility at a frozen commit, tag/Release, and competition-page
submission remain Human-owned.

## Read first

1. `CLAUDE.md`
2. `.codex/plan-runs/agentloom-mvp/state.md`
3. `.codex/plan-runs/agentloom-mvp/task-24-report.md`
4. `.codex/plan-runs/agentloom-mvp/task-25-report.md`
5. `.codex/plan-runs/agentloom-mvp/task-26-report.md`
6. `.codex/plan-runs/agentloom-mvp/task-27-brief.md`
7. `.codex/plan-runs/agentloom-mvp/task-27-audit-report.md`
8. `docs/architecture/agentloom-architecture.md`

## Non-negotiable boundaries

- AgentTeams remains pinned to `v1.1.2`.
- MiniMax and StepFun subscription calls are authorized and may be selected by
  task fit. Every live run must use an independent run ID and bind the actual
  Provider/model. The accepted Task 24 report remains immutable historical
  `minimax-cn / MiniMax-M2.5` evidence; that history does not restrict future
  diagnostics to MiniMax.
- Do not call Qwen or DeepSeek because those accounts have no balance.
- Prefer model-free deterministic checks unless live Agent behavior is required.
- Do not expose Matrix message bodies, Worker logs, credentials, tokens, API
  keys, gateway assertions, Signed Grants, or MinIO session content.
- Preserve ignored local historical evidence. Do not reset, clean, rewrite the
  frozen candidate, tag, publish, or change repository visibility without
  explicit user authorization.
- A Worker-local unexecuted test remains `UNCERTAIN`; only independent host or
  governed sandbox evidence can support the final `PASSED` verdict.
- Never mark recording, upload, public accessibility, PR merge, Release, or
  competition submission complete without direct external proof.

## Repository state

- Root: resolve with `git rev-parse --show-toplevel`.
- Branch: `main`
- Frozen candidate: the commit containing this file; resolve with
  `git rev-parse HEAD` and verify it against public `origin/main`.
- Worktree expectation: clean apart from intentionally ignored local historical
  diagnostics and immutable failed-run evidence.
- Durable ledger: `.codex/plan-runs/agentloom-mvp/state.md`

## Verified engineering state

### Task 24: complete

- Three fixed Cases: `severity-normalization`, `pagination-boundary`, and
  `retry-delay-cap`.
- Each Case passed `LOCAL_DETERMINISTIC` and `AGENTTEAMS_GOVERNED`.
- Final report: `6 PASSED / 0 NOT_RUN`, `complete=true`.
- Report:
  `artifacts/benchmarks/task24/task24-governed-20260815-final/benchmark-report.json`
- SHA-256:
  `3A73D0881D7CC3943936E299B37726C724979F710917218459ACFECD4CADC8AF`
- The accepted Task 24 run used `minimax-cn / MiniMax-M2.5`. Old A/B/C and
  other failed namespaces are preserved as diagnostic evidence and must not be
  deleted or rewritten. Future diagnostics may use MiniMax or StepFun, but must
  use a new run ID and report the Provider/model actually used.

### Task 25: engineering complete, external Full proof pending

- A clean clone with no initial `.venv` or reproduction artifacts passed the
  Lite one-command runner.
- Result: `339 passed / 0 failed / 0 errors / 3 skipped`, plus Ruff, strict mypy,
  pip-audit, pip check, and Alembic head.
- Evidence SHA-256:
  `8B71C65C3EFD391B5668F5DB112637630769F61FE64DE0549AFA8EF9A1CD3C5A`
- Full mode is implemented but still needs proof on a second clean Docker host.

### Task 26: complete

- Team-original Skill: `patch-scope-validator` v1.0.1, `PUBLISHED`.
- Source snapshot:
  `sha256:a036e6defc49907366769df0a1371b296ef4adc06f4d64d5d4f821055ca63797`
- Catalog: `2 PUBLISHED / 4 QUARANTINED`.
- Three independent Policy Broker -> ToolProvider calls bind SkillVersion,
  Agent, Grant, ToolCall, and Provider Evidence.
- Bundle:
  `artifacts/skills/patch-scope-validator-20260815-233912/skill-invocation-bundle.json`
- Bundle SHA-256:
  `CC14F2180918DB332B35D4C1E043B5B2D5F241A51CE134151A35ACCE1CC863C5`
- Strict reopen command:

```powershell
.\.venv\Scripts\python.exe -m agentloom.skill_evidence `
  --verify-bundle artifacts\skills\patch-scope-validator-20260815-233912\skill-invocation-bundle.json `
  --catalog skills\catalog.json
```

### Current quality gate

The final Task 27 worktree gate collected 378 tests and completed with
`375 passed / 3 skipped`; the skips are the existing opt-in live Docker tests.
The untracked root `test-results.txt` is a superseded 323/2 diagnostic snapshot,
not the current gate.
Ruff, strict mypy for 73 source files, pip-audit, Alembic `0006` single head,
22/22 candidate repository PowerShell parses, and `git diff --check` passed.

Do not replace the Task 25 clean-clone count of 339 with 375. They prove
different states: 339 is immutable clean-clone Lite evidence; 375 is the final
dirty-worktree gate after Task 27.

## Task 27: complete

The final audit reconciled architecture, specs, READMEs, source, tests,
PPT/PDF/ZIP, release draft, provenance, hashes, privacy, and submission claims.
Four security/correctness blocker groups were fixed and regression-tested.

- Architecture ADR-024 records why `patch-scope-validator` v1.0.0 was
  superseded by v1.0.1 while old evidence remains immutable.
- Architecture SHA-256:
  `6149373BAD22398DEA580D80722C1484DEF3FAC2FE018E00F70680821CEC148E`.
- Final audit report:
  `.codex/plan-runs/agentloom-mvp/task-27-audit-report.md`.

The accepted desktop deliverables are under:

`%USERPROFILE%\Desktop\零号工位-AgentLoom`

The accepted deck mapping is `02-AgentLoom-初赛方案.pptx` plus
`03-AgentLoom-初赛方案.pdf`, both 19 pages. The ZIP contains exactly eight
entries; 8/8 member hashes match the desktop originals. ZIP SHA-256:
`7278E6D36D038F87B1F4E722312D917B1335818D190952F02CDB000AC0E99BA8`.

## Task 28: pre-freeze release verification complete

- The pre-freeze worktree built one `agentloom-0.1.0` sdist and wheel.
- A fresh Python 3.12 environment passed installed version/import, CLI,
  `compileall`, and `pip check` smoke checks.
- Extracted archives contain 121 files and passed repository-metadata,
  credential, private-key, environment-file, and private-host-path scans.
- Full evidence and artifact hashes are in
  `.codex/plan-runs/agentloom-mvp/task-28-report.md`.
- `CHANGELOG.md` now reflects Tasks 20-27 and the current MiniMax/StepFun policy.
- This section records pre-freeze evidence. The commit containing this file must
  pass the gates and package rebuild below before push; any later commit requires
  another commit-bound run.

## Verification gates

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe src tests
.\.venv\Scripts\pip-audit.exe
.\.venv\Scripts\alembic.exe heads
git diff --check
```

Also parse repository PowerShell scripts, strictly reopen JSON/PPTX/PDF/ZIP
artifacts, and run a scoped high-confidence secret/private-path scan without
printing suspected secret values.

## Human checkpoint

The user or another authorized Human still must:

1. Prove Full reproduction on a second clean Docker host.
2. Record and inspect the real Demo.
3. Upload the video and verify its public URL.
4. Verify the public repository at a frozen commit.
5. Create the release tag/Release when ready.
6. Upload the final package and submit on the competition page.
