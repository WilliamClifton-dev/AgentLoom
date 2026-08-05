# AgentLoom quickstart for Windows

This path runs a deterministic repair without Docker, AgentTeams, or a cloud
model. It is the fastest way to confirm that a clone and its Python environment
work.

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
.\.venv\Scripts\agentloom tui
```

The bootstrap creates `.venv`, installs AgentLoom, and applies the local SQLite
migrations. The demo runs the `severity-normalization` Case and writes ignored
evidence under `artifacts/demo/severity-normalization/`.

Run the second bounded Case with:

```powershell
.\scripts\demo.ps1 -Case pagination-boundary
```

Neither command requires or reads a model API key. For the four-role runtime,
continue with [full AgentTeams deployment](windows-agentteams.md).
