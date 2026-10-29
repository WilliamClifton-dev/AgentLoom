# AgentLoom quickstart for Windows

This path runs a deterministic repair without Docker, AgentTeams, or a cloud
model. It is the fastest way to confirm that a clone and its Python environment
work. It is also the recommended first link for a reviewer: the run is bounded,
repeatable, and leaves inspectable evidence.

## Requirements

- Windows 10 or 11
- PowerShell 7 or newer
- Git
- Python 3.12 (not 3.11 or 3.13)

## Install and run

```powershell
git clone https://github.com/WilliamClifton-dev/AgentLoom.git
Set-Location AgentLoom

.\scripts\bootstrap.ps1 -Profile lite
.\scripts\demo.ps1
```

The bootstrap creates `.venv`, installs AgentLoom, and applies the local SQLite
migrations. The demo runs the `severity-normalization` Case and writes ignored
evidence under `artifacts/demo/severity-normalization/`.

Expected output ends with:

```text
Demo passed. Evidence: ...\artifacts\demo\severity-normalization
```

Inspect the independent verification summary with:

```powershell
Get-Content .\artifacts\demo\severity-normalization\artifacts\test-results.txt
```

The file should contain `PATCHED TESTS: PASSED`, `HIDDEN TESTS: PASSED`, and
`STATIC CHECKS: PASSED`. The surrounding directory also contains the patch,
risk report, verification result, and redacted evidence JSON.

Open the local evidence panel separately with:

```powershell
.\.venv\Scripts\agentloom tui
```

Run the second bounded Case with:

```powershell
.\scripts\demo.ps1 -Case pagination-boundary
```

Neither command requires or reads a model API key. For the four-role runtime,
continue with [full AgentTeams deployment](windows-agentteams.md).

## Common failures

- **Python version error:** install Python 3.12 and rerun bootstrap. AgentLoom
  deliberately rejects 3.11 and 3.13 so the evidence environment stays fixed.
- **Demo output already exists:** choose a new output directory with
  `.\scripts\demo.ps1 -OutputRoot .\artifacts\demo\my-run`; the runner refuses
  to overwrite evidence from an earlier run.
- **TUI cannot start:** run bootstrap first and verify that
  `.venv\Scripts\agentloom.exe` exists. The TUI is a local evidence viewer; it
  does not replace the deterministic verification command.
