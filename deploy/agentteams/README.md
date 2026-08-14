# AgentTeams v1.1.2 deployment

This directory pins the competition runtime and declares the AgentLoom team by
using AgentTeams/HiClaw's stable `hiclaw.io/v1beta1` resources.

Topology (AgentTeams requires one Team member to occupy `spec.leader`; this is
a resource mapping, not an additional AgentLoom Agent Identity):

- `default`: Manager and task coordinator
- `agentloom-investigator`: read-only investigator, mapped to `spec.leader`
- `agentloom-implementer`: constrained patch author
- `agentloom-verifier`: independent reviewer
- `agentloom-developer`: Level 2 Human with access to `agentloom-repair`

AgentLoom declares only three business Agent identities: Investigator,
Implementer, and Verifier. AgentTeams routes Manager-to-Team messages through
the member mapped to `spec.leader`, so `agentloom-investigator` occupies that
framework slot while retaining its Investigator duties. No separate TeamLeader
Agent is created. `hiclaw get workers --team agentloom-repair` therefore returns
the same three business identities.

All three business identities receive one MCP endpoint named
`agentloom-policy-broker`. The Manager receives no MCP configuration. For the
local embedded-Docker topology, Workers use the authenticated Higress endpoint
`http://aigw-local.hiclaw.io:8080/mcp-servers/mcp-agentloom-policy-broker`.
Higress forwards that route to the host Broker at
`http://host.docker.internal:8765/mcp` using Streamable HTTP.

## Configure

Use credentials only from ignored host-side environment files or process,
user, or machine environment variables. The tracked `hiclaw.env.example`
contains names and non-secret defaults only. Never put a real key in this
repository or a Worker resource.

Current paid-probe default:

```text
MINIMAX_API_KEY=<process-or-user-environment-only>
HICLAW_LLM_PROVIDER=minimax-cn
HICLAW_DEFAULT_MODEL=MiniMax-M2.5
```

### Administrator-defined OpenAI-compatible providers

Downstream deployers are not restricted by this repository maintainer's
MiniMax-only spending policy. They may use a provider and quota they administer
when its Chat API is compatible with CoPaw's `OpenAIChatModel`. AgentLoom does
not accept arbitrary private protocols: the endpoint must be a public HTTPS
OpenAI-compatible API, and the administrator remains responsible for checking
streaming, tool calling, reasoning fields, context limits, and model-specific
behavior.

Start from the tracked, secret-free template and change only non-secret
metadata. The `providerId` must retain the `custom-` prefix, and
`apiKeyEnvironmentVariable` names the host environment variable that will hold
the credential:

```powershell
Copy-Item `
  .\deploy\agentteams\provider-profiles\example.json `
  .\my-provider.json

.\deploy\agentteams\configure-openai-compatible-provider.ps1 `
  -ProfilePath .\my-provider.json `
  -ValidateOnly
```

Validation is local and model-free. It does not read the named secret, contact
Docker, or call the provider. After validation, set the named environment
variable outside the repository and perform the full deployment:

```powershell
[Environment]::SetEnvironmentVariable(
    "MY_PROVIDER_API_KEY",
    (Read-Host "Provider API key" -MaskInput),
    "Process"
)

.\scripts\bootstrap.ps1 `
  -Profile full `
  -Provider custom `
  -ProviderProfilePath .\my-provider.json
```

The bootstrap validates the Profile before checking the secret or Docker,
deploys Manager and Worker resources with the Profile's model ID, and activates
the custom provider last. It makes no paid model call by default. A deployer who
intentionally wants one connection probe per configured identity must add
`-RunProviderConnectionTest`. The lower-level equivalent is:

```powershell
.\deploy\agentteams\configure-openai-compatible-provider.ps1 `
  -ProfilePath .\my-provider.json

# Optional paid probe; requires explicit authorization and available quota.
.\deploy\agentteams\configure-openai-compatible-provider.ps1 `
  -ProfilePath .\my-provider.json `
  -RunConnectionTest
```

Successful validation proves only that the Profile satisfies the deployment
contract. Successful configuration proves that CoPaw accepted the settings. A
paid connection probe checks basic provider access. None of these is strict
AgentTeams role-message or repair E2E evidence.

### Fixed maintainer providers

Put the MiniMax key in the `MINIMAX_API_KEY` process or user environment
variable, then configure Manager and all three AgentLoom Workers:

```powershell
.\deploy\agentteams\configure-minimax-provider.ps1
```

The script uses the custom provider ID `minimax-cn`, fixes the endpoint to
`https://api.minimaxi.com/v1`, and limits the model to `MiniMax-M2.5`. The
built-in CoPaw `minimax` provider targets the international Anthropic endpoint
and is not used. The script never accepts an arbitrary endpoint or writes or
prints the key. Its connection checks are paid calls; use `-SkipConnectionTest`
only for configuration staging. On 2026-08-14 all four AgentTeams identities
passed the MiniMax connection check.

Qwen remains a historical, independently evidenced provider, but it is not used
for current paid probes while that account has no balance. Do not run the
following historical reactivation command unless quota is restored and a human
explicitly authorizes the provider again:

```powershell
.\deploy\agentteams\configure-provider.ps1
```

AgentTeams `v1.1.2` predates `qwen3.7-plus` in its built-in CoPaw catalog. The
script registers that model when missing, activates it for Manager and all three
Workers, and performs one paid connection probe per identity. When quota is
unavailable or a probe is not wanted, use `-SkipConnectionTest`; activation does
not itself invoke the model.

DeepSeek is historical and currently disabled because its account has no
balance. Do not run the following retained configuration command or any
DeepSeek probe unless quota is restored and a human explicitly authorizes the
provider again:

```powershell
.\deploy\agentteams\configure-deepseek-provider.ps1
```

The retained script fixes the provider to `deepseek` and the endpoint to
`https://api.deepseek.com/v1`. Its model allowlist is limited to the models
advertised by the current account: `deepseek-v4-flash` is the low-cost default,
while `deepseek-v4-pro` is available for the final repair E2E. It creates the
custom CoPaw provider when absent, activates it for Manager and all three
AgentLoom Workers, and performs one paid connection probe per identity. It does
not accept an arbitrary provider endpoint and never writes or prints the key.
Use `-SkipConnectionTest` only for configuration staging; it does not prove the
key or quota works.

StepFun Step Plan also remains a historical provider path; the current paid
provider decision authorizes MiniMax only. Do not run the following retained
configuration command unless that decision is explicitly changed:

```powershell
.\deploy\agentteams\configure-stepfun-provider.ps1
```

The script fixes the provider to `stepfun`, the model to `step-3.7-flash`, and
the endpoint to `https://api.stepfun.com/step_plan/v1`. It activates the same
model for Manager and all three AgentLoom Workers with
`reasoning_effort=low`. It never accepts an arbitrary endpoint or writes or
prints the key. Use `-SkipConnectionTest` only when a subsequent live run will
provide the connection evidence.

The following official OpsPilot configuration is retained only to reproduce the
historical DeepSeek evidence. It is disabled while DeepSeek quota is unavailable
and must not be run. When explicitly reauthorized, first switch the Manager so
it can create the Team, then configure the five new Worker containers:

```powershell
.\deploy\agentteams\configure-deepseek-provider.ps1 `
  -Model deepseek-v4-flash `
  -Containers @("hiclaw-manager")

$baselineContainers = @(
  "hiclaw-manager",
  "hiclaw-worker-alert-intake",
  "hiclaw-worker-rca-analyst",
  "hiclaw-worker-remediation-planner",
  "hiclaw-worker-recovery-verifier",
  "hiclaw-worker-opspilot-zero-demo-leader"
)
.\deploy\agentteams\configure-deepseek-provider.ps1 `
  -Model deepseek-v4-flash `
  -Containers $baselineContainers
```

Container names must be confirmed with `docker ps` after AgentTeams creates the
Team. If this deployment uses different names, pass only the confirmed local
`hiclaw-manager` or `hiclaw-worker-*` names.

## Start the Policy Broker

Build the hash-locked pytest runner once. The build uses a Python base image by
immutable digest, installs only wheel hashes from `uv.lock`, and records the
resulting local image ID:

```powershell
.\deploy\sandbox\build-runner.ps1
$sandboxImage = (Get-Content .\artifacts\sandbox\runner-image.txt -Raw).Trim()
```

Inject `AGENTLOOM_POLICY_SIGNING_KEY` and `AGENTLOOM_GATEWAY_ASSERTION` into the
Broker process environment, then start the Broker before applying the
AgentTeams resources. Inject the same assertion into the gateway configurator's
process environment without printing or persisting it. The launcher validates
the workspace and `.venv` runtime, creates ignored Evidence/database
directories, and keeps both secrets out of Worker resources and command output:

```powershell
.\deploy\agentteams\start-policy-broker.ps1 `
  -WorkspaceRoot .\demo\cases\pagination-boundary\before `
  -EvidenceRoot .\artifacts\policy-broker\evidence `
  -DatabasePath .\artifacts\policy-broker\broker.db `
  -SandboxImage $sandboxImage
```

The launcher rejects mutable or missing images, fixes the backend to Docker,
and removes the local host-execution acknowledgement from the child process.
There is no production fallback to host pytest. The launcher stays in the
foreground. Keep it running and use a separately
authorized process holding the same assertion to configure the authenticated
MCP gateway before reapplying the AgentTeams resources:

```powershell
.\deploy\agentteams\configure-policy-broker-gateway.ps1 `
  -EvidencePath .\artifacts\policy-broker\live-worker-probe\higress-gateway.json
```

The configured `AGENTLOOM_DATABASE_URL` is also the replay authority. Each
consumed Grant nonce is atomically persisted as a SHA-256 digest, so restarting
the Broker or opening another Broker on the same database does not make the
Grant reusable. The database contains neither the raw nonce nor the signed
Grant. Starting a Broker without the database is suitable only for local
verification and provides process-local replay protection.

The gateway script validates the pinned controller image, registers an official
Higress `DIRECT_ROUTE` with upstream path `/mcp` and Streamable transport, then
enables `key-auth` for exactly these existing AgentTeams consumers:

- `worker-agentloom-investigator`
- `worker-agentloom-implementer`
- `worker-agentloom-verifier`

Manager and every unrelated Worker remain unauthorized. The script fails if
the expected consumers do not already exist, if the allowlist does not converge,
or if the pinned controller image is not running. It writes only redacted route
metadata; consumer keys and Broker signing authority are never printed.

Embedded Higress `2.2.1` marks generated MCP routes as internal and rejects
Console Route API updates. The script therefore reads the complete generated
Ingress from the embedded Kubernetes API, changes only the two header-control
annotations, preserves `metadata.resourceVersion`, and writes the full object
back with `PUT`. Merge/JSON Patch and disabling the Broker assertion are not
supported fallbacks.

On an existing AgentLoom Team, run the gateway script before `deploy.ps1` so the
reapplied Worker configuration points at a ready route. On a clean environment,
first apply the Team once to let AgentTeams create the three Worker consumers,
then run the gateway script and apply the Team a second time. Do not create
replacement consumers or edit generated Worker `mcporter.json` files manually.

The pinned AgentTeams `setup-mcp-proxy.sh` helper was evaluated but is not used
for this upstream. It registers native MCP servers as `OPEN_API`; with embedded
Higress `2.2.1`, that route did not rewrite
`/mcp-servers/<name>` to the Broker's `/mcp` path and returned upstream `404`.
Higress `DIRECT_ROUTE` expresses the Streamable HTTP path explicitly and is the
verified compatible contract for this pinned runtime.

`host.docker.internal` is specific to the local embedded Docker topology. A
remote or Helm deployment must use its own routable Broker service address in
the Higress service source; Worker resources should continue to reference the
gateway URL rather than the upstream Broker directly.

The current local HTTP boundary authorizes tool execution with signed,
parameter-bound, single-use Grants. On 2026-08-14, the Verifier discovered all
three Broker tools through Higress, obtained a server-derived five-minute Grant,
and completed one bounded pytest call. Direct-host identity failures returned
`401`; the unrelated `worker-alert-intake` returned `403`; the allowlisted
Implementer could neither request nor consume a Verifier Grant; a pytest target
outside signed `authorizedPaths`, parameter tampering, and replay were denied.
The Broker recorded exactly one `SUCCEEDED` ToolCall for
`agentloom-verifier`. This deterministic probe used no model and consumed no
MiniMax or Qwen quota. Redacted evidence is written to
`artifacts/policy-broker/task12/live-verifier-probe.json`.

## Apply and verify

Start the official `v1.1.2` embedded deployment and the Policy Broker first.
For an existing Team, configure the Policy Broker gateway as described above,
then run from the second terminal:

```powershell
.\deploy\agentteams\deploy.ps1 `
  -Model MiniMax-M2.5 `
  -EvidencePath .\artifacts\agentteams\deployment.json
.\deploy\agentteams\configure-minimax-provider.ps1
```

AgentTeams `v1.1.2` accepts `spec.humanMembers` while creating a Team but drops
that field when `hiclaw apply` updates an existing Team. AgentLoom immediately
reapplies the declared members through the embedded Kubernetes merge-patch API
and verifies the returned Team spec before continuing. This compatibility step
is version-scoped, idempotent, and fails the deployment if the member list is
not persisted; it does not expose the embedded API token.

The following DeepSeek deployment order is historical and currently disabled;
do not run it while DeepSeek quota is unavailable. If it is explicitly
reauthorized, deploy the resources with the alternative model ID first, then
activate the direct provider last. Applying AgentTeams resources restores
`hiclaw-gateway`, so reversing this order can send a DeepSeek model ID through
the previously configured Qwen route:

```powershell
.\deploy\agentteams\deploy.ps1 `
  -Model deepseek-v4-flash `
  -EvidencePath .\artifacts\agentteams\deployment-deepseek.json
.\deploy\agentteams\configure-deepseek-provider.ps1 `
  -Model deepseek-v4-flash
```

The historical `deepseek-v4-pro` variant also remains disabled until quota is
restored and its use is explicitly reauthorized.

The following StepFun deployment path is historical and currently disabled. If
it is explicitly authorized in a future provider decision, deploy the resources
first and activate the direct provider last:

```powershell
.\deploy\agentteams\deploy.ps1 `
  -Model step-3.7-flash `
  -EvidencePath .\artifacts\agentteams\deployment-stepfun.json
.\deploy\agentteams\configure-stepfun-provider.ps1
```

Keep Qwen evidence as an independent historical run. Its paid rollback path is
disabled while the account has no balance; do not run `configure-provider.ps1`
unless quota is restored and a human explicitly reauthorizes Qwen.

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

## Official OpsPilot baseline

The official OpsPilot demo is a separate Baseline proof, not the AgentLoom
repair E2E. Start its mock gateway from the downloaded demo directory:

```powershell
$OpsPilotRoot = 'D:\path\to\opspilot-zero-demo'
Set-Location $OpsPilotRoot
python .\tools\mock_tool_server.py --host 0.0.0.0 --port 18089
```

On Windows Docker Desktop, Workers reach that host process through
`http://host.docker.internal:18089`. The Linux bridge gateway address shown in
the upstream runbook does not route back to the Windows host in this setup.
From the AgentLoom repository, run the two incidents serially and save strict
evidence:

```powershell
.\deploy\agentteams\run-opspilot-baseline.ps1 `
  -DemoRoot $OpsPilotRoot `
  -Model deepseek-v4-flash `
  -IncidentTimeoutSeconds 1800 `
  -EvidencePath `
    '.\artifacts\agentteams\opspilot-baseline-deepseek-v4-flash-strict.json'
```

The runner creates the official four Workers and a distinct TeamLeader when
they do not already exist, waits for all CoPaw APIs, configures the six
identities, and runs `INC-1001` before `INC-1002`. It accepts a run only when
the Leader publishes an independent completion line in the Team Room and the
scenario trace contains every required tool call. A delayed reminder directs
the Leader back to the Team Room if it accidentally publishes its final report
to its DM; the runner never fabricates or relays the report itself.

AgentTeams `v1.1.2` currently writes TeamLeader `projectflow` artifacts under
`shared/projects/`, while Worker `taskflow` looks under `shared/tasks/`. For
this official HTTP-tool Baseline, the task therefore instructs the TeamLeader
to pass role inputs inline through Matrix and instructs Workers to call the
mock gateway directly. The four-role interaction, real tool calls, Leader
report, and evidence checks remain live. This workaround is specific to the
official Baseline; AgentLoom's repair artifact path uses the audited namespace
bridge documented below.

The strict DeepSeek run on 2026-08-04 passed both incidents. Keep the resulting
ignored JSON as local competition evidence and do not commit it. This is
historical evidence, not permission to rerun the paid probe.

## Strict role-message E2E

The E2E probe invokes live model APIs and can consume paid quota:

```powershell
.\deploy\agentteams\e2e.ps1 `
  -EvidencePath .\artifacts\agentteams\e2e-minimax-cloud.json
```

Historical evidence uses provider-specific filenames such as
`e2e-deepseek-cloud.json`. DeepSeek is currently disabled, so do not reactivate
it or rerun this paid E2E until quota is restored and a human explicitly
authorizes it. A successful connection probe is not an E2E result; the strict
role-message run must pass again after every authorized provider switch.

The verified `deepseek-v4-flash` run on 2026-08-04 completed all four
role-owned markers in 113 seconds. This proves live provider activation and
AgentTeams collaboration; it does not yet prove a live model-generated repair
artifact workflow.

It accepts success only when Matrix contains role-owned, independent-line
markers from Investigator, Implementer, Verifier, and Manager. Marker text
inside a prompt, assignment, or status message cannot satisfy the check. The
evidence contains only task, sender, Room, event, timestamp, and strict-match
metadata; it excludes passwords and access tokens.

Local Ollama remains an offline fallback, not the competition default. It is
adequate for provider and delivery smoke tests but was too slow and unreliable
for repeatable multi-step tool orchestration on the current machine.

## L2 Human approval evidence

This path demonstrates an AgentLoom risk `L2` external-write approval. It is
separate from AgentTeams Human `permissionLevel: 2`, which only grants
team-scoped Matrix access. The demo creates and approves a candidate request;
it does not issue a signed executable grant or perform the external write.

Prepare one short-lived request while Docker and the pinned AgentTeams runtime
are running:

```powershell
.\deploy\agentteams\run-l2-approval-demo.ps1 `
  -Phase Prepare `
  -RunId competition-l2-01
```

The command sends the exact request as the Manager into the
`agentloom-repair` Team Room and creates two local, non-secret decision
templates. Open Element at `http://127.0.0.1:18088`, review the request, choose
the approved or rejected template, and paste the complete JSON as the logged-in
`agentloom-developer` Human. Send exactly one decision before the default
10-minute approval window expires. The script never sends the Human decision.

Collect and verify that event:

```powershell
.\deploy\agentteams\run-l2-approval-demo.ps1 `
  -Phase Collect `
  -RunId competition-l2-01
```

Collection accepts exactly one newer decision from the configured Human in the
exact Team Room. Python then revalidates the Manager sender, Human sender,
Matrix event types and timestamps, approval version, task/grant IDs, risk,
route, parameter digest, rollback hash, pending status, and expiry against the
SQLite ledger. Any mismatch leaves the pending record unchanged. The final
`artifacts/l2-approval/<run-id>/l2-approval-evidence.json` contains event IDs,
Matrix identities, timestamps, hashes, and final status, but no access token,
password, API key, or usable grant.

Preserve this JSON evidence before making screenshots or a competition video.
For the final recording, capture the Team Room request, the Human review and
send action, the successful Collect output, and the redacted evidence fields.
Do not show terminal environment values, login responses, passwords, or tokens.
Video is presentation evidence created after the machine-verifiable JSON exists;
it is not required for the runtime verifier itself.

If the local Human demo credential has appeared in any terminal output, recreate
that Human before the final recording so its credential rotates. AgentTeams
`v1.1.2` also changes room membership during recreation, so rerun `deploy.ps1`
and verify the Human is Active in the Team Room before preparing a new run.

## Unattended live repair E2E

The top-level guarded competition entrypoint can replay the latest completed
run, validate all three evidence layers, and open the TUI without calling a
model:

```powershell
.\scripts\competition-demo.ps1 -Mode replay
```

Use the lower-level commands below when collecting a fresh run or diagnosing one
phase independently. Fresh paid execution remains opt-in through
`competition-demo.ps1 -Mode live -ConfirmPaidRun`.

`run-live-repair.ps1` is the strict collector for the current pagination Case.
For an empty task prefix it automatically stages only `spec.md`, `base/lib/`, and
`base/tests/` from the frozen pagination Case. A non-empty prefix must already
match the exact four-input allowlist. It sends the task to the Manager, verifies
the Manager-to-Investigator handoff and the existing Agent-to-Agent assignments,
requires each business Agent to publish only its owned files and fresh exact-line
events, rejects `expected/`, hidden-test, workspace, and cache objects, checks
immutable input fingerprints and event-after-artifact ordering, rejects any
result object over 128 KiB before download, and binds the actual Matrix event IDs
into a live repair submission:

```powershell
.\deploy\agentteams\run-live-repair.ps1 `
  -TaskId AL-LIVE-PAGINATION-UNATTENDED-20260804-03 `
  -SubmissionPath `
    .\artifacts\live-repair\AL-LIVE-PAGINATION-UNATTENDED-20260804-03\submission.json `
  -EvidencePath `
    .\artifacts\agentteams\live-repair-pagination-qwen-unattended-03.json

.venv\Scripts\agentloom verify-live `
  --submission `
    .\artifacts\live-repair\AL-LIVE-PAGINATION-UNATTENDED-20260804-03\submission.json `
  --case-root .\demo\cases\pagination-boundary `
  --output-root `
    .\artifacts\live-repair\AL-LIVE-PAGINATION-UNATTENDED-20260804-03\verified
```

If collection fails after the task was already sent, preserve the rejected
evidence and resume from its exact `startedAt` instead of sending the model task
again:

```powershell
.\deploy\agentteams\run-live-repair.ps1 `
  -TaskId AL-LIVE-PAGINATION-20260804-01 `
  -Resume `
  -ResumeEvidencePath `
    .\artifacts\agentteams\live-repair-pagination-qwen-rejected.json `
  -SubmissionPath .\artifacts\live-repair\resume\submission.json `
  -EvidencePath .\artifacts\agentteams\live-repair-resume.json
```

The unattended Qwen run `AL-LIVE-PAGINATION-UNATTENDED-20260804-03` on
2026-08-04 passed the local hidden-test boundary with patch SHA-256
`7d9d571a833eabaedf97eac73dad50f6290bfa332d3ef504882398ba2e6d0833`.
It started from an empty Team prefix and completed without `-Resume`, host file
transfer, or recovery messages. The strict run evidence contains four immutable
input fingerprints, three role-owned Matrix events, the exact nine-object final
allowlist, event-after-artifact checks, and submission SHA-256
`4e7c3e1c0a5d86246c75b31e741d89e6d1860a7ef412b9cd6594283af841dad9`.
The earlier `AL-LIVE-PAGINATION-20260804-01` run remains historical supervised
evidence because AgentTeams `v1.1.2` required transport-only recovery before the
exact-file publication protocol was added.

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

The allowlist is `result.md`, `root-cause-report.json`, `repair.patch`,
`patch-artifact.json`, `verification-result.json`, `risk-report.json`,
`test-results.txt`, and `evidence.json`.
Workspace files, Team metadata, and unknown outputs never cross into the global
namespace. Both operations are idempotent for the same immutable `spec.md` and
fail closed on missing objects or hash mismatches. Evidence contains object
names and SHA-256 values only; it contains no MinIO or Matrix credentials.

## Live rollback trace

From the repository root, use the guarded competition entrypoint with a new task
ID. This calls the configured AgentTeams model and therefore requires explicit
confirmation:

```powershell
.\scripts\competition-rollback-demo.ps1 `
  -Mode live `
  -TaskId AL-LIVE-ROLLBACK-001 `
  -ConfirmPaidRun
```

The collector requires Verifier failure, Manager request, Implementer execution,
and Verifier post-rollback markers from their actual Matrix identities. AgentLoom
then independently applies the failed candidate, reproduces its failure, restores
the approved snapshot, checks its hash, and runs visible, hidden, and static tests.
Use `-Mode replay` after the first successful run to inspect the same evidence in
the TUI without calling a model.

Run the complete offline artifact path against the live AgentTeams MinIO without
calling an LLM:

```powershell
.venv\Scripts\python -m agentloom.mock_artifact_e2e `
  --output-root .\artifacts\demo\mock-artifact-run
```

This validates the Case manifest and frozen snapshot, reproduces a failing Python
test, applies the deterministic patch, runs public tests, verifier-only hidden
tests, and static compilation, emits contract-valid role artifacts, stages the
parent task into the Team namespace, collects the result allowlist, and parses
the collected objects again from the global namespace. It is a deterministic
integration baseline and must remain labelled `Mock`; it does not prove that a
live model generated the repair.

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
