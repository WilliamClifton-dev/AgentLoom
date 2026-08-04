# L2 Human Approval Evidence Plan

## Goal

Produce a fail-closed AgentTeams v1.1.2 demonstration in which an AgentLoom L2
action request is visible in the AgentLoom Team Room, a real Human decides it in
Element, and the local parameter-bound approval ledger is updated only after the
Matrix event sender and exact request binding are verified.

## Decisions

- AgentTeams `permissionLevel: 2` is team-scoped Matrix access; AgentLoom risk
  `L2` is a separate external-write approval classification.
- The Human decision event must come from the configured Human Matrix user in the
  configured Team Room and be newer than the approval request.
- Approval ID, approval version, status, parameter digest, route, risk, and
  rollback hash must match the pending local record.
- Matrix access tokens and passwords remain process-local and never enter evidence.
- A deterministic host demo driver may transport a request as the Manager account,
  but evidence must label that origin and must not call it model-generated.
- No executable grant is issued by this slice; the existing Policy Broker remains
  the only grant issuer after approval, and L3 remains disabled.

## Ordered Work

1. Add reproducible `pip-audit` tooling and audit runtime dependencies.
2. Add strict Matrix L2 approval evidence contracts and verifier tests.
3. Add the AgentTeams/Element prepare-and-collect demo driver with deployment tests.
4. Run preflight/full gates and update demo documentation.

## Acceptance Criteria

- A forged sender, wrong room, stale timestamp, wrong approval version, or any
  binding mismatch cannot update the approval record.
- An exact Human APPROVED or REJECTED event updates exactly one pending record.
- Evidence includes Matrix event IDs, senders, room, timestamps, request binding,
  and final local status, but no password, token, or usable grant signature.
- The user can open Element, review the exact request, decide it, and preserve
  JSON evidence plus optional screenshots/video.

## Verification

- Focused approval/evidence/PowerShell deployment tests.
- Full pytest, Ruff, strict mypy, `git diff --check`, secret-value scan.
- `pip-audit` against an exported runtime dependency set.

## Sources

- https://github.com/agentscope-ai/AgentTeams/blob/v1.1.2/docs/declarative-resource-management.md#human
- https://github.com/agentscope-ai/AgentTeams/blob/v1.1.2/tests/test-04-human-intervene.sh
- https://github.com/agentscope-ai/AgentTeams/tree/v1.1.2
