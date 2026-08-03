# AgentTeams v1.1.2 deployment

This directory pins the competition runtime and declares the AgentLoom team by
using AgentTeams/HiClaw's stable `hiclaw.io/v1beta1` resources.

Topology:

- `default`: Manager and task coordinator
- `agentloom-investigator`: Team leader and read-only investigator
- `agentloom-implementer`: constrained patch author
- `agentloom-verifier`: independent reviewer
- `agentloom-developer`: Level 2 Human with access to `agentloom-repair`

The Team leader is also a Worker identity. This follows AgentTeams' delegation
boundary: Manager talks to the Team leader, while the leader coordinates members
inside the Team Room. `hiclaw get workers --team agentloom-repair` therefore
returns three distinct Worker identities.

## Configure

Use your own DashScope key in the ignored host-side `hiclaw-manager.env`. The
tracked `hiclaw.env.example` contains names and non-secret defaults only. Never
put a real key in this repository or a Worker resource.

Competition cloud default:

```text
HICLAW_LLM_PROVIDER=qwen
HICLAW_DEFAULT_MODEL=qwen3.7-plus
```

The running CoPaw containers can also be switched without a restart. Put your
own key in the `QWEN_API_KEY` process or user environment variable, then run:

```powershell
.\deploy\agentteams\configure-provider.ps1
```

AgentTeams `v1.1.2` predates `qwen3.7-plus` in its built-in CoPaw catalog. The
script registers that model when missing, activates it for Manager and all three
Workers, and performs one paid connection probe per identity. When quota is
unavailable or a probe is not wanted, use `-SkipConnectionTest`; activation does
not itself invoke the model.

## Apply and verify

Start the official `v1.1.2` embedded deployment first. Then run:

```powershell
.\deploy\agentteams\deploy.ps1 `
  -Model qwen3.7-plus `
  -EvidencePath .\artifacts\agentteams\deployment.json
```

For an explicitly local, non-competition smoke test:

```powershell
.\deploy\agentteams\deploy.ps1 `
  -Model qwen:latest `
  -EvidencePath .\artifacts\agentteams\deployment-local.json
```

Success requires locked image digests, Manager `Running`, Team `Active`, all
three Worker identities `Running`, Human `Active`, and non-empty Matrix Room IDs.
The evidence file deliberately excludes credentials and the Human initial
password. `artifacts/` is ignored by Git.

## Strict role-message E2E

The E2E probe invokes live model APIs and can consume paid quota:

```powershell
.\deploy\agentteams\e2e.ps1 `
  -EvidencePath .\artifacts\agentteams\e2e-qwen-cloud.json
```

It accepts success only when Matrix contains role-owned, independent-line
markers from Investigator, Implementer, Verifier, and Manager. Marker text
inside a prompt, assignment, or status message cannot satisfy the check. The
evidence contains only task, sender, Room, event, timestamp, and strict-match
metadata; it excludes passwords and access tokens.

Local Ollama remains an offline fallback, not the competition default. It is
adequate for provider and delivery smoke tests but was too slow and unreliable
for repeatable multi-step tool orchestration on the current machine.

## Parent-task namespace bridge

AgentTeams `v1.1.2` resolves a Team Leader's `shared/tasks/<id>/` under the
Team namespace, while Manager parent tasks live under global `shared/tasks/`.
The Leader can read the latter as `global-shared/`, but that path is read-only,
so the upstream documented write-back flow cannot carry repair artifacts.

AgentLoom keeps the upstream images unchanged and bridges only one validated
task directory at a time. Stage verifies `spec.md` and mirrors the Manager parent
task into the selected Team namespace:

```powershell
.venv\Scripts\python -m agentloom.namespace_bridge stage `
  --task-id AL-DEMO-001 `
  --team-name agentloom-repair `
  --evidence-path .\artifacts\agentteams\AL-DEMO-001-stage.json
```

After the Leader and Workers finish, collect verifies that the Team copy of
`spec.md` is unchanged and copies only the fixed result allowlist back to the
global parent task:

```powershell
.venv\Scripts\python -m agentloom.namespace_bridge collect `
  --task-id AL-DEMO-001 `
  --team-name agentloom-repair `
  --evidence-path .\artifacts\agentteams\AL-DEMO-001-collect.json
```

The allowlist is `result.md`, `root-cause-report.json`, `patch-artifact.json`,
`verification-result.json`, `risk-report.json`, and `test-results.txt`.
Workspace files, Team metadata, and unknown outputs never cross into the global
namespace. Both operations are idempotent for the same immutable `spec.md` and
fail closed on missing objects or hash mismatches. Evidence contains object
names and SHA-256 values only; it contains no MinIO or Matrix credentials.

AgentTeams `v1.1.2` returns HTTP `405` when `hiclaw apply -f` tries to update an
existing Human. The script therefore preserves an existing
`agentloom-developer` and verifies its room membership. To change that Human's
permissions, delete only that resource and rerun the script; its Matrix password
will rotate.

## Roll back resources

Delete dependents first:

```powershell
docker exec hiclaw-controller hiclaw delete human agentloom-developer
docker exec hiclaw-controller hiclaw delete team agentloom-repair
```

Keep the existing `default` Manager because it is part of the base installation.

## Official v1.1.2 sources

- <https://github.com/agentscope-ai/AgentTeams/blob/v1.1.2/docs/declarative-resource-management.md>
- <https://github.com/agentscope-ai/AgentTeams/blob/v1.1.2/docs/k8s-native-agent-orch.md>
- <https://github.com/agentscope-ai/AgentTeams/blob/v1.1.2/docs/zh-cn/windows-deploy.md>
