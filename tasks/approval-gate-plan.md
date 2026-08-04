# Approval Gate Plan

## Goal

Add a persistent, parameter-bound approval gate for L2 actions and reject all L3 execution grants in the initial competition runtime.

## Decisions

- An approval binds one task, grant, parameter digest, risk level, route, and rollback-plan hash.
- L2 requires a matching, approved, unexpired record before a Policy Broker grant can be signed.
- L3 records may document a proposal, but the broker never signs an executable L3 grant.
- API and TUI display only structured approval metadata; prompts, credentials, and raw tool output remain outside this feature.

## Ordered Work

1. Add strict Approval contracts and contract tests.
2. Persist approvals with optimistic version checks and an Alembic migration.
3. Bind Policy Broker issuance to an ApprovalRecord and block L3.
4. Add approval API endpoints and TUI queue/detail rendering.
5. Run a controlled Qwen repair E2E using only L1 repair actions.

## Risks

| Risk | Mitigation |
| --- | --- |
| Approval reused for another request | Bind `parameterDigest`, route, risk, and rollback hash. |
| L3 accidentally executes | Reject L3 before signing a grant. |
| Stale decision overwrites a newer one | Require an expected approval version. |
| Qwen cost or output escapes controls | Use the frozen Case, existing command/path limits, and a single explicit E2E run. |
