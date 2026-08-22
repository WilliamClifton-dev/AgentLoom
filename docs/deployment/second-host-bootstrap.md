# Second-Host Full Bootstrap

> Status: **script path documented, first execution pending**. The
> public-main gate in `.github/workflows/ci.yml` already builds the
> immutable Docker sandbox image and runs the Full pytest job on
> `ubuntu-latest`. The P3 follow-up here is the **operator-side**
> reproduction on a second Windows + Docker host, which proves the
> Full mode is not tied to the maintainer's primary machine.

## What "Full" proves that "Lite" does not

The Lite gate runs the deterministic test fixtures in
`demo/cases/` and the replayable contract tests under
`tests/`. It does not exercise the AgentTeams Manager, the three
AgentTeams Workers, the Higress gateway, or the live policy broker
HTTP server. Those are wired together by the
`deploy/agentteams/*.ps1` family and exercised by
`tests/test_agentteams_deployment.py`.

A second-host bootstrap of the Full gate catches:

- A regression in the AgentTeams resource files (`manager.json`,
  `team.json`, `worker.json`, `human.json`) that only triggers
  when the resource is actually applied against a running
  AgentTeams API.
- A breakage in the Higress → Broker Streamable HTTP wiring that
  only triggers when the gateway is real.
- A platform-specific assumption in
  `deploy/agentteams/*.ps1` that happens to compile on the
  maintainer's machine but fails elsewhere (line endings, path
  length, hidden PowerShell module dependencies).

## Reproduce the Full bootstrap on a second host

### 1. Prerequisites

- Windows 11 with PowerShell 5.1+ or PowerShell Core 7.x.
- Python 3.12 (the `pyproject.toml` excludes 3.13).
- Docker Desktop ≥ 4.20 with the WSL 2 backend.
- A working `kubectl` against a local AgentTeams/HiClaw cluster
  (`hiclaw cluster start` is the upstream entry point).
- The same `MINIMAX_API_KEY` (or alternative provider key) the
  maintainer used. Never commit it; keep it in the host's
  environment.

### 2. Clone the public-main checkout

```powershell
git clone https://github.com/WilliamClifton-dev/AgentLoom
cd AgentLoom
git checkout v0.1.0   # or the tag under review
```

### 3. Bootstrap the Lite gate

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\ruff.exe check .
.venv\Scripts\mypy.exe src tests
.venv\Scripts\pip-audit.exe
```

The local Lite gate is **376 passed / 3 skipped / 0 failed**. The
3 skips are the `test_docker_sandbox_live.py` cases that need the
local Docker daemon; with Docker Desktop running they become 379
passed / 0 skipped / 0 failed.

### 4. Build the Full bootstrap

The maintainer's `scripts/bootstrap.ps1 -Profile full` is the
authoritative entry point. The current implementation is
PowerShell-only and depends on:

- `hiclaw cluster start` (upstream AgentTeams CLI)
- `deploy/agentteams/deploy.ps1` (HiClaw resource application)
- `deploy/agentteams/configure-minimax-provider.ps1` (Worker
  model configuration)
- `deploy/agentteams/configure-policy-broker-gateway.sh` (Higress
  Console side; the only Linux-friendly shim in the directory)

The second-host operator runs the same sequence:

```powershell
pwsh -File scripts/bootstrap.ps1 -Profile full
pwsh -File deploy/agentteams/deploy.ps1
pwsh -File deploy/agentteams/configure-minimax-provider.ps1 `
    -Model "MiniMax-M2.5"
pwsh -File deploy/agentteams/run-live-repair.ps1 `
    -TaskId 'AL-SECONDHOST-01' `
    -CaseRoot ./demo/cases/severity-normalization `
    -Provider 'minimax-cn' `
    -Model 'MiniMax-M2.5' `
    -TimeoutSeconds 3600 `
    -SubmissionPath ./artifacts/benchmarks/AL-SECONDHOST-01/submission.json `
    -EvidencePath ./artifacts/benchmarks/AL-SECONDHOST-01/run-evidence.json
```

### 5. Record the result

Once the second host produces a clean
`run-evidence.json`, copy the produced artifact to
`docs/compatibility/<host-id>-full-bootstrap.json` and open a PR
that updates `docs/compatibility/README.md` with the new host.
The expected fields are:

```json
{
  "host_id": "secondhost-2026-08-21",
  "operator": "<your handle>",
  "tag": "v0.1.0",
  "python": "3.12.7",
  "docker": "Docker Desktop 4.32.0",
  "hiclaw": "v1.1.2",
  "test_counts": {
    "lite_passed": 376,
    "lite_skipped": 3,
    "full_passed": 379,
    "full_skipped": 0
  },
  "evidence_digest": "sha256:...",
  "rekor_entry": "https://rekor.sigstore.dev/?logIndex=..."
}
```

## What to do if the second host fails

The point of running on a second host is to surface failures the
maintainer cannot see. Open an issue with:

- The host's `run-evidence.json` and `verified/artifacts/` snapshot.
- The full `scripts/bootstrap.ps1 -Profile full` log.
- The failing test id (if any) and the first 50 lines of its
  failure output.

The maintainer is **not** expected to debug the failure on the
operator's behalf; the compatibility record is the artifact, not
the fix. The fix is then authored against `main` and the second
host reruns against the next tagged release.
