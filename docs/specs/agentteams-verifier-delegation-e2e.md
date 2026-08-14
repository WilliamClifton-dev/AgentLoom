# Spec: AgentTeams Investigator-to-Verifier delegation E2E

## Objective

Prove that AgentTeams v1.1.2 can carry a real Investigator-to-Verifier handoff
into the already verified governed Docker pytest path. An administrator starts
one non-triggering task envelope in the Investigator-owned room and one bounded
probe in the Manager-owned room. The Manager delegates the envelope event ID to
the Investigator, the Investigator emits a new role-owned Verifier assignment
with an `m.mentions` target, and the Verifier independently issues and consumes
one Policy Broker Grant through Higress.

## Tech stack

- PowerShell 7 orchestration and Matrix Client API v3.
- AgentTeams v1.1.2 with CoPaw Workers.
- MiniMax `MiniMax-M2.5` for Manager, Investigator, and Verifier only.
- Existing AgentLoom Policy Broker, SQLite event store, Higress route, and
  immutable Docker pytest Provider.

## Commands

- Direct preflight: `deploy/agentteams/run-sandbox-e2e.ps1 -RunNamespace task17 -SandboxImage <immutable-id>`.
- Delegated model run: `deploy/agentteams/run-sandbox-model-e2e.ps1 -RunNamespace task17 -DispatchMode delegated -RunRoot <run-root>`.
- Tests: `.venv/Scripts/python -m pytest`.
- Quality: `.venv/Scripts/ruff check .` and `.venv/Scripts/mypy src tests`.

## Project structure

- `deploy/agentteams/`: bounded runtime orchestration.
- `src/agentloom/sandbox_e2e.py`: fixture and ToolCall/Evidence verification.
- `tests/`: static and contract tests.
- `artifacts/policy-broker/task17/`: ignored runtime evidence.
- `.codex/plan-runs/agentloom-mvp/`: durable execution records.

## Code style

Use the existing fail-closed PowerShell pattern: validate paths and runtime
identity before external calls, keep credentials process-local, emit only
allowlisted evidence fields, and throw generic errors without response bodies.

## Testing strategy

- A static regression test must fail until delegated mode targets the Team Room
  and verifies both role-owned events.
- PowerShell parsing verifies both runners before live use.
- A fresh direct preflight proves the new database and Docker path.
- The live MiniMax run must bind Matrix event metadata to exactly one successful
  Verifier ToolCall and matching Docker Evidence.

## Boundaries

- Always: stage the task envelope without any mention; encode its exact Matrix
  event ID into the Manager's standalone delegation marker; then require an Investigator
  assignment in the Team Room, exact sender identities, exact standalone
  markers, exact mentions, and temporal ordering before the Verifier PASS marker.
- Ask first: changing AgentTeams resources, Broker authorization, Provider
  selection, or adding a model Provider.
- Never: directly mention a business Agent from the administrator in delegated
  mode; use a host pytest fallback; expose message bodies, credentials, Worker
  logs, or signed Grants; call Qwen, DeepSeek, or StepFun.

## Success criteria

1. A fresh Task 17 run passes the model-free direct Docker preflight.
2. The administrator stages one task envelope in the Investigator-owned room
   without `m.mentions`, then mentions only the Manager in the Manager-owned room.
3. A later Manager event in the Investigator-owned Leader Room contains the
   exact Manager delegation marker with the task-envelope event ID embedded in
   that line, plus `m.mentions` for the Investigator.
4. A new Team Room event from the Investigator contains the exact delegation
   marker and `m.mentions` for the Verifier.
5. A later Team Room event from the Verifier contains the exact PASS marker.
6. The delegated task has exactly one successful ToolCall from
   `agentloom-verifier`, backed by the immutable Docker image and matching
   workspace/Evidence digests.
7. Persisted evidence contains only IDs, timestamps, hashes, status, provider and
   model names; full tests and security gates pass.

## Open questions

None. Implementer participation remains outside this focused delegation probe.
