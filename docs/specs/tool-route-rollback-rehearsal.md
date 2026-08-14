# Tool route rollback rehearsal specification

## Objective

Prove, without a model or tool execution, that the real Policy Broker Tool
Provider factory can switch from the explicit local-development route to the
production Docker route and roll back to a byte-equivalent local route config.

## Commands

- Focused tests: `.venv\Scripts\python -m pytest tests/test_route_rehearsal.py tests/test_policy_tool_e2e.py`
- CLI rehearsal: `.venv\Scripts\agentloom rehearse-route-rollback --output-root <empty-directory>`
- Quality: `.venv\Scripts\ruff check .` and `.venv\Scripts\mypy src tests`

## Project structure

- `src/agentloom/route_rehearsal.py`: bounded environment switch/rollback and
  evidence contract.
- `src/agentloom/policy_mcp.py`: public Provider factory used by runtime and
  rehearsal.
- `src/agentloom/cli.py`: thin operator command.
- `tests/test_route_rehearsal.py`: route, rollback, redaction, and ownership tests.

## Behavior

The service owns an explicit empty output root, creates an empty synthetic
workspace, and uses the current Policy Broker factory in this sequence:

```text
local-development -> docker -> local-development rollback
```

The Docker route uses an immutable synthetic image digest and only constructs
the Provider; it does not contact the Docker daemon. The local route only
constructs the host Provider and never executes a command. A canonical digest
of the three non-secret route environment variables must match before the switch
and after rollback. The caller's original process environment is restored in an
outer `finally` block even on failure.

## Testing strategy

- RED first for the missing service/command and public factory.
- Real Provider constructors, real `os.environ`, and fresh filesystem roots;
  no mocked route decision.
- Assert provider sequence, config digest equality, deterministic evidence,
  caller environment restoration, pure JSON CLI output, and rejection of
  occupied/symlink roots.

## Boundaries

- Always use only `AGENTLOOM_SANDBOX_BACKEND`, `AGENTLOOM_SANDBOX_IMAGE`, and
  `AGENTLOOM_ALLOW_HOST_TEST_EXECUTION` as route state.
- Never inspect, copy, hash, or emit signing keys, Provider API keys, Matrix
  credentials, or other environment variables.
- Never execute pytest, start Docker, or activate a model Provider in this task.
- Production continues to require Docker; this rehearsal does not authorize a
  local-development fallback.

## Success criteria

- Actual factory IDs are `local-test-runner`,
  `sandboxed-test-runner/docker-sandbox`, and `local-test-runner` in order.
- Baseline and rollback config SHA-256 values are identical.
- Caller route variables are byte-equivalent after success and failure.
- Evidence is deterministic and contains no raw environment value or host path.
- Focused and full gates pass.
