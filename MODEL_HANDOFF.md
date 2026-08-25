# AgentLoom model handoff

Updated: 2026-08-25 +08:00

This is the public handoff for another coding model. Repository files and
immutable Evidence are authoritative; chat summaries and ignored local files are
not.

## Current state

- Public branch: `main`. Last 12 commits (since the previous handoff on
  2026-08-16) follow `chore(repo): remove obsolete demo artifacts`
  (`2aa4d04`) and are listed in `git log --oneline 2aa4d04..HEAD`.
- Product direction: Agent Tool Policy Gateway prototype; AgentTeams `v1.1.2`
  is the reference integration.
- Latest public-main gate: `380 passed / 0 skipped` with Docker tests
  enabled.
- Current worktree Lite gate: `377 passed / 3 skipped / 0 failed` from 380
  collected tests. The 3 skips are
  `tests/test_docker_sandbox_live.py`; with a live Docker daemon the
  same three tests are expected to pass, taking the current tree to 380/0/0.
- Frozen `v0.1.0` gate: `375 passed / 3 skipped` (historical).
- Task 24: three cases, two modes, `6 PASSED / 0 NOT_RUN`.
- Skill catalog: `2 PUBLISHED / 4 QUARANTINED`. Exit criteria for the four
  QUARANTINED Skills are documented in
  `docs/skills/quarantine-evaluation-criteria.md`.
- Human L2 approval: `APPROVED`.
- AgentTeams PR #1141: `OPEN`, not merged.
- Release: <https://github.com/WilliamClifton-dev/AgentLoom/releases/tag/v0.1.0>
- Demo: <https://williamclifton-dev.github.io/AgentLoom/demo.html>
- Final Demo SHA-256:
  `EBADF02C634EB5F26116792E8B96B9F50ECEE6382DD010A48C918F7EAA54A8EB`.
- Submission ZIP SHA-256:
  `0C5DFEB0BA6665609A14129A76CC1C239AED882A17E930C144AA5D3B88F6C306`.
- `test-results.txt` is the committed local Lite snapshot. CI writes its
  Docker-enabled Full snapshot to the runner temp directory and does not
  compare the Full result with the local 377/3 file.

The resume-grade prototype is complete and feature-frozen. A second-host
Full bootstrap remains an optional historical validation item. The Release
package uses a maintainer-published SHA-256 integrity check; no signed tag
or cosign attestation is claimed.

## What changed since the 2026-08-16 handoff

### P0: evidence-baseline alignment

- `test-results.txt` is tracked as the local Lite snapshot. The CI workflow
  writes its Docker-enabled Full snapshot to the runner temp directory and
  does not compare the Full result with the local 377/3 file.
- `tool_provider_from_env` in `agentloom.policy_mcp` was audited
  manually for the three fail-closed paths (missing
  `AGENTLOOM_SANDBOX_BACKEND`, `local-development` without
  `AGENTLOOM_ALLOW_HOST_TEST_EXECUTION=true`, bogus backend values)
  and the five existing rejection tests in
  `tests/test_policy_tool_e2e.py` all pass on the current tree.

### P1: package splits (zero regression)

Three large files became multi-module packages. Every existing
`from agentloom.<name> import X` call site continues to work
through a thin re-export shim; the public surface is unchanged.

- `src/agentloom/contracts.py` (1331 lines) →
  `src/agentloom/contracts/` (10 modules: `_base`, `identity`,
  `skill`, `tool`, `evidence`, `grant`, `risk`, `repair`, `approval`,
  `task`).
- `src/agentloom/live_repair.py` (690 lines) →
  `src/agentloom/live_repair/` (7 modules: `_types`, `models`,
  `result`, `verifier`, `case`, `cli`, `__main__`).
- `src/agentloom/live_rollback.py` (569 lines) →
  `src/agentloom/live_rollback/` (3 modules: `models`, `operations`,
  `__init__`).

The methodology that produced these splits (AST walk, class-block
slicing, cycle break via model.py, Pydantic `model_rebuild`) is
preserved in `scripts/dev/historical-splits/` so a future operator
can re-apply it to a new file.

### P2: Linux Lite + Skill evaluation criteria

- `docs/deployment/linux-quickstart.md` records the steps to
  reproduce the Lite gate on a clean Linux host (Python 3.12, venv,
  pip, ruff, mypy, pip-audit, pytest) and the audit finding that
  `src/` and `tests/` contain zero hardcoded Windows paths,
  `os.name == "win32"` branches, or `os.sep` / `os.linesep` literals.
  The Full-mode `deploy/agentteams/*.ps1` scripts are explicitly
  out of Lite scope.
- `docs/skills/quarantine-evaluation-criteria.md` documents the
  seven admission gates a Skill must pass to move out of
  `QUARANTINED`, a state-machine diagram, and a per-Skill table for
  `debugging-and-error-recovery`, `test-driven-development`,
  `security-and-hardening`, and `using-agent-skills`. Each table
  lists upstream provenance, RiskLevel, required tool entries, the
  pytest fixtures that must pass, and the re-evaluation triggers.

### P3: second-host bootstrap + release integrity documentation

- `deploy/signing/sign-submission-package.ps1` wraps
  `cosign sign-blob` for the public submission ZIP, supports both
  the keyed and the `keyless://` flows, and fails closed on
  missing cosign, missing key, or a stub signature. The script
  refuses to use `Invoke-Expression` so a malicious filename
  cannot inject PowerShell syntax.
- `docs/security/signing-submission.md` documents the GitHub Release
  asset SHA-256 integrity check and explicitly does not claim identity
  attestation.
- `docs/deployment/second-host-bootstrap.md` is the operator
  runbook for a clean Windows + Docker host to reproduce the
  Full gate, including the expected
  `docs/compatibility/<host-id>-full-bootstrap.json` shape.

The actual second-host run remains pending operator action. The cosign
wrapper is deprecated and is not part of the public release path.

## Read first

1. `README.md` or `README.en.md`
2. `docs/architecture/agentloom-architecture.md`
3. `docs/deployment/quickstart.md`
4. `docs/deployment/linux-quickstart.md`
5. `docs/competition/agentloom-preliminary-submission.md`
6. `docs/competition/submission-package-manifest.json`
7. `docs/skills/quarantine-evaluation-criteria.md` (P2)
8. `docs/security/signing-submission.md` (P3)

## Non-negotiable boundaries

- Keep Investigator, Implementer, Verifier, and Human approval
  identities separate. An Agent cannot approve or verify its own
  work.
- Only independent host or governed sandbox Evidence can support
  final `PASSED`.
- Preserve Provider, model, event, Grant, ToolCall, artifact, and
  digest bindings.
- Never expose credentials, tokens, Matrix passwords, raw Worker
  logs, Signed Grants, or private MinIO content.
- MiniMax and StepFun subscriptions are authorized when a live call
  is necessary. Do not call Qwen or DeepSeek because those accounts
  have no balance.
- Prefer deterministic replay for diagnostics. Every new live run
  needs a unique run ID and must record the actual Provider and
  model.
- Do not claim PR #1141 is merged or second-host Full reproduction is
  complete without direct external proof. The release SHA-256 proves
  artifact integrity, not maintainer identity.
- Do not delete or rewrite the three `tests/test_*_l2_approval.py`
  / `tests/test_*.py` Suite without re-running the public-main
  gate; the Fail-closed paths in
  `tool_provider_from_env` are the boundary between this project
  and a hostile test execution.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m agentloom.cli refresh-test-results
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe src tests
.\.venv\Scripts\pip-audit.exe
.\.venv\Scripts\alembic.exe heads
git diff --check
.\.venv\Scripts\python.exe -m scripts.dev.historical_splits.split_contracts --help
```

The last command is a no-op example; the four `scripts/dev/historical-splits/`
scripts are the methodology record, not runnable tools.

For a model-free governed replay on the prepared Windows host, run
`START_COMPETITION_REPLAY.cmd`. For a fresh local setup, follow
`docs/deployment/quickstart.md`. For a fresh Linux setup, follow
`docs/deployment/linux-quickstart.md`. For a second-host Full
reproduction, follow `docs/deployment/second-host-bootstrap.md`. For
the Release asset integrity check, follow
`docs/security/signing-submission.md`.
