# AgentTeams Investigator-to-Verifier delegation E2E plan

1. Add the Task 17 specification, task ledger, and artifact namespace contract.
2. Add failing static tests for namespace isolation and delegated Matrix routing.
3. Implement a bounded delegated mode that proves Manager delegation,
   Investigator sender, Verifier mention, Team Room location, event ordering,
   Verifier marker, and ToolCall.
4. Run a fresh direct preflight followed by the MiniMax delegated probe.
5. Record redacted evidence, review the change, and run all quality gates.

## Risks

- Agent replies in the wrong room: trigger the Manager in its owned room, require
  a Manager-to-Investigator event and the exact Team Room ID for the handoff, and
  reject assignment or PASS markers from every other room.
- Manager paraphrases away bound fields: stage a non-triggering task-envelope
  Matrix event and encode its exact event ID into the standalone Manager marker.
- A model fabricates another role: bind each marker to Matrix sender identity.
- A marker appears without execution: require one matching database ToolCall and
  Docker Evidence.
- A partial run is retried: create a fresh run root rather than reusing a task
  after any model ToolCall.
