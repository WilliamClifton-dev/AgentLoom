# Linux Lite Quickstart

> Status: **Lite mode is fully reproducible on Linux**. Full mode
> (AgentTeams `v1.1.2` Manager + Workers + Higress) is still Windows-
> scripted in the upstream tooling; this document records the gap and
> what a Linux operator can verify today.
>
> Last audit: 2026-08-21 against the public-main gate.

## What works on Linux today

A clean Ubuntu 22.04 (or any glibc 2.31+ / musl 1.2+) host with Python
3.12, Git, and (optionally) Docker Engine ≥ 24.0 can run the Lite
reproduction end to end:

| Step | Command | What it proves |
|---|---|---|
| 1. Clone | `git clone https://github.com/WilliamClifton-dev/AgentLoom && cd AgentLoom` | Repository fetches; the `codex/` branch prefix is honored. |
| 2. Create venv | `python3.12 -m venv .venv` | Python 3.12 is the only supported runtime (`pyproject.toml` pins `>=3.12,<3.13`). |
| 3. Install | `.venv/bin/pip install -e ".[dev]"` | Editable install of the `agentloom` package plus the dev extras (`ruff`, `mypy`, `pip-audit`, `pytest`, `pytest-asyncio`, `build`). |
| 4. Lint | `.venv/bin/ruff check .` | Ruff imports the `pyproject.toml` exclude list and skips `**/*.ps1` / `**/*.yml` automatically. |
| 5. Type-check | `.venv/bin/mypy src tests` | Strict mypy + `pydantic.mypy` plugin over the 93 source files. |
| 6. Audit | `.venv/bin/pip-audit` | Confirms no known vulnerabilities in the installed dep tree. |
| 7. Lite tests | `.venv/bin/pytest -q` | Local Lite gate: **376 passed / 3 skipped / 0 failed**. The 3 skips live in `tests/test_docker_sandbox_live.py` and require a live Docker daemon (see below). |
| 8. Refresh snapshot | `pwsh -File scripts/refresh-test-results.ps1` or `.venv/bin/python -m agentloom.cli refresh-test-results` | Regenerates `test-results.txt` with timing, platform, and pytest-version normalized so identical evidence is byte-identical. The committed file is byte-stable; CI uses the same script. |

Steps 4-8 are Linux-native. Step 3 works on Linux because the
`agentloom` wheel depends only on `alembic`, `fastapi`, `httpx`,
`jinja2`, `mcp`, `opentelemetry-*`, `pydantic`, `rich`, `sqlalchemy`,
`textual`, and `typer` — none of which need `pywin32`, `pyreadline`,
or any other Windows-only module.

## The three Docker skips

`pytest -q` reports `3 skipped` in Lite mode. The skipped tests live in
`tests/test_docker_sandbox_live.py` and they exercise the live Docker
sandbox backend:

```
tests/test_docker_sandbox_live.py sss
```

When Docker Engine is reachable (Linux Docker daemon, Docker Desktop,
or a remote daemon via `DOCKER_HOST`), the same three tests pass and
the local count becomes `379 passed / 0 skipped / 0 failed`. The CI
gate in `.github/workflows/ci.yml` already builds the immutable sandbox
image and exports `AGENTLOOM_TEST_SANDBOX_IMAGE` to exercise those
three tests, so the public-main GitHub Actions run reports the 379/0/0
number regardless of the operator host.

To opt in on Linux, install Docker Engine ≥ 24.0, ensure the user is
in the `docker` group, and run `.venv/bin/pytest -q` again. No extra
configuration is required: `src/agentloom/docker_sandbox.py` uses
`--network none --read-only --cap-drop ALL` and does not depend on any
host-side `host.docker.internal` magic for the sandbox itself. The
`host.docker.internal` reference is only used by AgentTeams'
`deploy/agentteams/configure-policy-broker-gateway.sh` to point
Higress at the host Broker; that script is not part of the Lite gate.

## Full mode on Linux

Full mode (Manager + three Workers + Higress + Policy Broker) is
shipped primarily as Windows PowerShell scripts in
`deploy/agentteams/`. The single Linux shim is
`deploy/agentteams/configure-policy-broker-gateway.sh`, which does
the Higress Console side of the configuration in `bash` with
`curl` and `jq`. Everything else in `deploy/agentteams/` ends in
`.ps1` and runs only on Windows PowerShell 5.1+ or PowerShell Core
7.x.

To reach Full-mode parity on Linux a future change will need to
port every `*.ps1` to either `bash` or a Python entry point under
`src/agentloom/cli.py`. Until then, the Linux operator can:

1. Run the Lite gate on Linux (above) to confirm the platform-agnostic
   half of the project still works.
2. If a Docker daemon is available, exercise the deterministic
   `mock_repair` path:

   ```bash
   .venv/bin/python -m agentloom.mock_repair \
     --case-root ./demo/cases/severity-normalization \
     --output-root ./artifacts/demo/severity-normalization
   ```

   The result must match the snapshot under
   `artifacts/demo/severity-normalization/` (verify with
   `git diff --exit-code artifacts/demo/severity-normalization`).
3. If a Docker daemon is available, exercise the governed Docker
   sandbox backend through `python -m agentloom.policy_mcp` with
   `AGENTLOOM_SANDBOX_BACKEND=docker` and a pinned
   `AGENTLOOM_TEST_SANDBOX_IMAGE`. The five existing rejection tests
   in `tests/test_policy_tool_e2e.py`
   (`requires_explicit_sandbox_backend`,
   `requires_immutable_docker_image`,
   `requires_host_execution_acknowledgement`,
   `rejects_partial_tool_configuration`,
   `rejects_unknown_mcp_transport`) all pass on Linux as well; the
   public-main CI gate is the canonical proof.

## What does NOT work on Linux yet

- `scripts/bootstrap.ps1` and `scripts/verify-clean-reproduction.ps1`
  are PowerShell-only.
- `deploy/agentteams/deploy.ps1` and the `run-*-repair.ps1` family
  are PowerShell-only. The harness
  `tests/test_live_repair.py::test_agentteams_repair_and_sandbox_scripts_are_case_driven`
  asserts the script bodies are case-driven and the Linux shim is
  not part of that contract.
- `deploy/agentteams/configure-deepseek-provider.ps1`,
  `configure-minimax-provider.ps1`, `configure-openai-compatible-provider.ps1`,
  and `configure-stepfun-provider.ps1` are PowerShell-only. Each
  one mutates the Worker `CoPaw` configuration; a Linux equivalent
  would shell out to `kubectl` with the same `kubectl patch`
  payload. Patches welcome.
- `deploy/sandbox/build-runner.ps1` is the canonical
  `docker build` wrapper used by the public-main CI. The same
  `docker build` invocation works on Linux without change; the
  PowerShell wrapper is a Windows convenience for `Get-Content`,
  `Join-Path`, and `Add-Content` only.

## Linux audit findings (2026-08-21)

A static audit of `src/` and `tests/` for Windows-only patterns
turned up **zero** hardcoded `C:\` paths, **`zero`** `os.name` /
`sys.platform == "win32"` branches, and **zero** `os.sep` /
`os.linesep` literals. Every test that needs the current Python
interpreter reads `sys.executable` (a single occurrence in
`tests/test_demo_case.py:116` of the literal `"C:/Python312/python.exe"`
is part of a parameterised rejection test that never executes the
path; the validator just observes the path is not a real pytest
command). The Dockerfile in `deploy/sandbox/Dockerfile` is
multi-stage-free and works on any Docker host.

The known Linux gaps are entirely in `deploy/agentteams/*.ps1` and
`scripts/*.ps1`. None of those PowerShell scripts are pulled in by
Lite mode, so the Lite gate stays green on Linux.

## Reproducing this audit

```bash
# Should report zero matches.
git grep -nE 'C:\\\\|os\.name|MS_WINDOWS|host\.docker\.internal' -- src tests
git grep -n 'posix_only\|sys\.platform\s*==' -- src tests
```

If any of those greps ever returns a match, the match should either
be inside a rejection test (like `test_demo_case.py:116`), inside a
`*.yml` / `*.ps1` file, or documented as a follow-up.
