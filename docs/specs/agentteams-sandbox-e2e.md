# Spec: AgentTeams to Docker governed pytest E2E

## Objective

Prove the complete production path from the AgentTeams Verifier identity,
through authenticated Higress and the Policy Broker, into a fresh Docker pytest
sandbox. Extend the deterministic transport proof with one MiniMax-driven tool
call without weakening any runtime authorization boundary.

## Trust boundaries

- MiniMax output and Matrix text are untrusted inputs.
- Higress supplies the authenticated Worker consumer; the Broker maps only the
  Verifier consumer to `agentloom-verifier`.
- The Broker derives Agent identity, Grant ID, nonce, expiry, Skill hash, and
  risk from authoritative state.
- Tool parameters bind the pytest argv, working directory, limits, and
  `workspaceDigest`. The image and Docker controls remain trusted server config.
- Signing keys, gateway assertions, Matrix credentials, model credentials, and
  signed Grants must not enter prompts, command arguments, logs, or redacted
  evidence. A signed Grant may exist only transiently in the Worker/MCP call.

## Acceptance

1. A fresh database contains separate direct-preflight and MiniMax tasks in
   `VERIFYING`, both restricted to `tests/test_pagination.py`.
2. The Broker replaces any prior listener using a new process-only signing key
   and gateway assertion, immutable Docker image ID, and no host fallback.
3. Direct Verifier `mcporter` issuance and execution succeed through Higress;
   wrong-consumer execution and replay fail.
4. An administrator sends a bounded E2E probe directly to the Verifier-owned
   Matrix room. MiniMax is the active Verifier model and independently performs
   issuance and execution, then emits its own exact PASS marker in that room.
5. Each success has exactly one valid ToolCall and Evidence proving the Docker
   Provider, image ID, snapshot digest, exit code zero, and passing pytest.
6. Redacted run evidence contains only IDs, hashes, provider/model names,
   statuses, and Matrix event identity. It contains no secrets or signed Grant.

## Non-goals

- Letting the model construct shell commands or choose infrastructure settings.
- Treating a Matrix marker without matching database/Evidence as success.
- Calling Qwen, DeepSeek, StepFun, or any provider other than MiniMax.
- Claiming Docker is VM-grade isolation or that OpenSandbox is implemented.
