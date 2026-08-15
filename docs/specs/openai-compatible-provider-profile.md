# Spec: OpenAI-compatible Provider Profile

## Objective

Let an AgentLoom deployer configure an administrator-approved OpenAI-compatible
model for AgentTeams without editing repository scripts. A reusable JSON Profile
defines non-secret provider metadata; the API key remains in a named host
environment variable. The current repository maintainer authorizes MiniMax and
StepFun subscription calls selected by task fit. The accepted Task 24 report is
immutable historical MiniMax evidence, not a future Provider restriction; every
new live run binds its actual Provider/model and a new run ID. Qwen and DeepSeek
remain unauthorized while their quota is unavailable.

## Tech stack

- PowerShell 7 deployment entrypoint, matching existing AgentTeams scripts.
- AgentTeams `v1.1.2` CoPaw model APIs.
- JSON Profile with explicit `agentloom.provider-profile/v1alpha1` contract.
- No new runtime or development dependency.

## Commands

```powershell
# Validate and configure without a paid model call.
.\deploy\agentteams\configure-openai-compatible-provider.ps1 `
  -ProfilePath .\deploy\agentteams\provider-profiles\example.json

# Explicitly opt into one paid connection test per target identity.
.\deploy\agentteams\configure-openai-compatible-provider.ps1 `
  -ProfilePath .\my-provider.json `
  -RunConnectionTest

# Model-free verification.
.venv\Scripts\python -m pytest tests\test_provider_profile.py `
  tests\test_agentteams_deployment.py
.venv\Scripts\ruff check .
.venv\Scripts\mypy src tests
```

## Project structure

- `deploy/agentteams/configure-openai-compatible-provider.ps1`: validated
  administrator entrypoint.
- `deploy/agentteams/provider-profiles/example.json`: secret-free template.
- `tests/test_provider_profile.py`: parser, validation, and safety contract tests.
- `deploy/agentteams/README.md`: user workflow and compatibility boundary.

## Contract and style

```json
{
  "schemaVersion": "agentloom.provider-profile/v1alpha1",
  "providerId": "custom-example",
  "displayName": "Example OpenAI-compatible provider",
  "baseUrl": "https://api.example.com/v1",
  "modelId": "example-model",
  "apiKeyEnvironmentVariable": "EXAMPLE_API_KEY",
  "generate": {
    "temperature": 0.1,
    "maxTokens": 4096
  }
}
```

Unknown fields and unsupported schema versions fail closed. Provider IDs use a
reserved `custom-` prefix so Profiles cannot overwrite built-in providers. Provider, model,
environment-variable, endpoint, numeric, and container values are bounded before
Docker or CoPaw is contacted. The CoPaw implementation class remains fixed to
`OpenAIChatModel` and cannot be selected by the Profile.

## Testing strategy

- Small tests invoke validation-only mode with valid and malicious Profiles.
- Negative cases cover unknown fields, invalid IDs, HTTP URLs, userinfo,
  localhost/private IP literals, unsafe environment-variable names, invalid
  generation parameters, and unsafe container names.
- Static deployment tests prove secrets are not printed or persisted and paid
  connection checks require `-RunConnectionTest`.
- No test calls Docker, CoPaw, or a model provider.

## Boundaries

- Always: validate the complete Profile before reading a secret or contacting
  Docker; read credentials from process/user/machine environment only; redact
  output; configure only declared `hiclaw-manager` or `hiclaw-worker-*` targets.
- Ask first: private-network endpoints, non-OpenAI protocols, new CoPaw model
  classes, paid probes, or changing the active provider in a shared deployment.
- Never: accept a key in Profile/argv, log a key, allow Agent/task-controlled
  endpoints, accept HTTP endpoints, follow arbitrary redirects, or treat a
  configuration result as E2E evidence.

## Success criteria

- A valid Profile passes model-free validation and can configure a custom CoPaw
  provider/model using the deployer's environment key.
- Configuration makes no paid call by default.
- Invalid or unsafe Profiles fail before secret lookup and Docker access.
- JSON output contains provider/model/container/result metadata but no key.
- Existing MiniMax, Qwen, DeepSeek, and StepFun scripts and evidence remain.
- Full pytest, Ruff, mypy, PowerShell parsing, and secret scans pass.

## Open questions

None for v1alpha1. Private gateways and non-OpenAI protocols require a later,
explicitly reviewed Profile version or Adapter.
