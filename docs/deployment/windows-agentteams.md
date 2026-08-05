# Full AgentTeams deployment on Windows

This profile deploys AgentLoom's Manager, Investigator, Implementer, Verifier,
and Human resources on the official AgentTeams/HiClaw `v1.1.2` runtime.
AgentLoom does not install Docker Desktop or silently download the upstream
runtime.

## Requirements

- Docker Desktop 4.20 or newer, using Linux containers
- PowerShell 7 or newer
- Git and Python 3.12
- Recommended minimum: 4 CPU cores, 8 GB RAM, and 20 GB free disk
- A Qwen or DeepSeek account with available API quota

## 1. Install the pinned upstream runtime

Review the official
[AgentTeams Windows guide](https://github.com/agentscope-ai/AgentTeams/blob/v1.1.2/docs/zh-cn/windows-deploy.md),
then run its pinned installer:

```powershell
$env:HICLAW_VERSION = "v1.1.2"
Set-ExecutionPolicy Bypass -Scope Process -Force
$installer = New-Object Net.WebClient
$installer.Encoding = [Text.Encoding]::UTF8
iex $installer.DownloadString('https://higress.ai/hiclaw/install.ps1')
```

Choose local-only network exposure and the CoPaw runtime. Keep the generated
Element credential private. Confirm that `hiclaw-controller` is running before
continuing.

## 2. Supply a model credential

Use a masked prompt so the key is not placed in shell history. DeepSeek is the
lower-cost default for deployment validation:

```powershell
[Environment]::SetEnvironmentVariable(
    "DEEPSEEK_API_KEY",
    (Read-Host "DeepSeek API key" -MaskInput),
    "Process"
)
```

For Qwen, set `QWEN_API_KEY` in the same way. Do not edit `.env.example`, commit
a key, paste it into a resource JSON file, or include it in screenshots.

## 3. Bootstrap AgentLoom

```powershell
git clone https://github.com/WilliamClifton-dev/AgentLoom.git
Set-Location AgentLoom

.\scripts\bootstrap.ps1 `
  -Profile full `
  -Provider deepseek `
  -Model deepseek-v4-flash
```

The command performs local Python initialization, applies the pinned AgentTeams
resources, activates the selected provider last, and runs a strict health check.
Provider activation is deliberately last because applying an AgentTeams resource
restores `hiclaw-gateway`.

Use `deepseek-v4-pro` for the final live repair when quality matters more than
cost, or use `-Provider qwen -Model qwen3.7-plus` for Qwen.

## 4. Verify and collect evidence

```powershell
.\scripts\health-check.ps1
```

Success means the Manager is `Running`, the Team and Human are `Active`, all
three Worker identities are `Running`, room IDs exist, and locked image digests
match. Redacted evidence is written to:

- `artifacts/agentteams/deployment.json`
- `artifacts/agentteams/health.json`

Element is available at `http://127.0.0.1:18088/#/login`. Continue with the
strict role-message and repair flows in the
[AgentTeams runbook](../../deploy/agentteams/README.md).

## Competition demo

Replay the newest complete live repair evidence without a model call:

```powershell
.\scripts\competition-demo.ps1 -Mode replay
```

For an automated preflight that does not open the TUI:

```powershell
.\scripts\competition-demo.ps1 -Mode replay -NoTui
```

A fresh run consumes model quota and therefore requires both a new task ID and
an explicit confirmation switch:

```powershell
.\scripts\competition-demo.ps1 `
  -Mode live `
  -TaskId AL-LIVE-PAGINATION-DEMO-01 `
  -ConfirmPaidRun
```

Live mode refuses to overwrite an existing task, submission, run evidence, or
verification directory. It currently uses the frozen `pagination-boundary` Case
and the already configured `qwen3.7-plus` AgentTeams identities.

## Roll back AgentLoom resources

Delete dependents first; keep the upstream `default` Manager:

```powershell
docker exec hiclaw-controller hiclaw delete human agentloom-developer
docker exec hiclaw-controller hiclaw delete team agentloom-repair
```

This removes AgentLoom's AgentTeams resources. It does not delete local evidence,
the SQLite database, Docker images, or the base AgentTeams installation.
