# AgentLoom model handoff

Updated: 2026-08-16 +08:00

This is the public handoff for another coding model. Repository files and
immutable Evidence are authoritative; chat summaries and ignored local files are
not.

## Current state

- Public branch: `main`.
- Runtime: AgentTeams `v1.1.2`.
- Current public-main gate: `379 passed / 0 skipped` with Docker tests enabled.
- Frozen `v0.1.0` gate: `375 passed / 3 skipped`.
- Task 24: three cases, two modes, `6 PASSED / 0 NOT_RUN`.
- Skill catalog: `2 PUBLISHED / 4 QUARANTINED`.
- Human L2 approval: `APPROVED`.
- AgentTeams PR #1141: `OPEN`, not merged.
- Release: <https://github.com/WilliamClifton-dev/AgentLoom/releases/tag/v0.1.0>
- Demo: <https://williamclifton-dev.github.io/AgentLoom/demo.html>
- Final Demo SHA-256:
  `EBADF02C634EB5F26116792E8B96B9F50ECEE6382DD010A48C918F7EAA54A8EB`.
- Submission ZIP SHA-256:
  `0C5DFEB0BA6665609A14129A76CC1C239AED882A17E930C144AA5D3B88F6C306`.

The remaining Human checkpoints are competition-page submission and optional
Full/Docker reproduction on a second clean host.

## Read first

1. `README.md` or `README.en.md`
2. `docs/architecture/agentloom-architecture.md`
3. `docs/deployment/quickstart.md`
4. `docs/competition/agentloom-preliminary-submission.md`
5. `docs/competition/submission-package-manifest.json`

## Non-negotiable boundaries

- Keep Investigator, Implementer, Verifier, and Human approval identities
  separate. An Agent cannot approve or verify its own work.
- Only independent host or governed sandbox Evidence can support final `PASSED`.
- Preserve Provider, model, event, Grant, ToolCall, artifact, and digest bindings.
- Never expose credentials, tokens, Matrix passwords, raw Worker logs, Signed
  Grants, or private MinIO content.
- MiniMax and StepFun subscriptions are authorized when a live call is necessary.
  Do not call Qwen or DeepSeek because those accounts have no balance.
- Prefer deterministic replay for diagnostics. Every new live run needs a unique
  run ID and must record the actual Provider and model.
- Do not claim PR #1141 is merged, second-host Full reproduction is complete, or
  competition submission is complete without direct external proof.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe src tests
.\.venv\Scripts\pip-audit.exe
.\.venv\Scripts\alembic.exe heads
git diff --check
```

For a model-free governed replay on the prepared Windows host, run
`START_COMPETITION_REPLAY.cmd`. For a fresh local setup, follow
`docs/deployment/quickstart.md`.
