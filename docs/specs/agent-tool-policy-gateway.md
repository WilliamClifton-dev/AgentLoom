# Spec: Agent Tool Policy Gateway

## Objective

将 AgentLoom 的产品主线从“基于 AgentTeams 的软件修复平台”收缩为一个可嵌入已有 Agent 系统的 Agent Tool Policy Gateway。

Gateway 负责回答四个问题：

1. 哪个受信 Agent 正在请求工具调用；
2. 该 Agent 是否有权以当前目的调用指定工具和动作；
3. 参数、路径、风险级别和审批是否与短时 Grant 一致；
4. 工具执行结果是否形成不可覆盖、可回放的 Evidence。

AgentTeams 保留为一个适配器和已验证的参考集成，不再是 Gateway 的运行时前提。

## Target Users

- 已有 Coding Agent、客服 Agent 或运维 Agent 的平台工程团队；
- 需要限制 Agent 工具、路径、外部写操作和审批边界的安全团队；
- 需要对 Agent 执行结果进行审计和重放的企业团队。

## MVP Scope

MVP 只支持一个完整、可证明的调用闭环：

```text
Trusted Agent identity
  -> Policy decision
  -> short-lived single-use Grant
  -> MCP Gateway
  -> ToolProvider
  -> structured result + append-only Evidence
```

MVP 必须支持：

- MCP `stdio` 和 Streamable HTTP 两种传输；
- 受信 Consumer 到 Agent Identity 的显式映射；
- Tool、Action、参数摘要、请求路径、Skill/Policy 版本和时效绑定；
- Grant 签名校验、nonce 防重放、路径白名单和 fail-closed 错误语义；
- Docker 沙箱中的一个不可信测试工具；
- SQLite Evidence 持久化和结构化重放校验；
- AgentTeams 适配器复用相同的 Gateway 契约。

## Non-Goals

- 不建设新的 Agent 编排器、Agent 商店或聊天界面；
- 不替代 AgentTeams、LangGraph、OpenAI Agents 等上层运行时；
- 不在 MVP 中支持任意远程 URL、任意 Shell 命令或动态下载工具；
- 不引入通用插件市场、策略 DSL 或多租户 RBAC；
- 不把 Higress、Matrix、MinIO 或 AgentTeams 作为核心运行时依赖；
- 不把“证据写入”当作成功的充分条件，最终结果仍必须由工具输出和校验规则支持。

## Architecture Decisions

1. **Policy core is transport-neutral.** MCP 只负责边界传输；身份解析、Grant 校验、Provider 路由和 Evidence 记录属于独立核心。
2. **AgentTeams is an adapter.** AgentTeams Consumer、Higress 和 Matrix 身份映射进入适配器层，不进入核心 Contract。
3. **Grant is the enforcement boundary.** Prompt、Skill 文本和客户端声明都不能直接授予工具权限。
4. **Provider owns execution.** Gateway 不执行 Shell、pytest 或云 API；它只把已校验的请求交给显式 ToolProvider。
5. **Evidence is append-only.** ToolCall、Skill invocation 和结果摘要必须追加写入；历史记录不能被更新覆盖。
6. **Reuse existing contracts first.** 现有 `SkillExecutionGrant`、`ToolExecutionEnvelope`、`ToolCallEventRecord`、`SandboxedTestRunnerProvider` 和拒绝路径测试优先复用。只有现有 Task/AgentTeams 绑定阻碍独立使用时，才提取新的中性字段或 Provider Protocol。

## Core Contract Shape

核心调用上下文至少包含：

- `principal`: 已认证的 Agent Identity；
- `purpose`: 外部任务或调用目的；
- `policyVersion`: 已加载策略版本；
- `skillName` / `skillVersion`: 可选的能力来源绑定；
- `toolName` / `action`: 受控工具动作；
- `parameterDigest`: 规范化参数摘要；
- `requestedPaths`: 规范化相对路径；
- `expiresAt` 和一次性 `nonce`；
- `approvalRef`: 对 L2 外部写操作的人工审批引用；
- `evidenceRefs`: 原始工具输出、产物和验证记录的引用。

核心失败码保持稳定并可由调用方处理：

`POLICY_DENIED`, `GRANT_EXPIRED`, `GRANT_REPLAYED`, `PARAMETER_MISMATCH`,
`PATH_NOT_ALLOWED`, `IDENTITY_MISMATCH`, `APPROVAL_REQUIRED`,
`PROVIDER_UNAVAILABLE`, `EVIDENCE_RECORDING_FAILED`。

## Project Structure Direction

```text
src/agentloom/
├── gateway/              # transport-neutral policy and execution orchestration
├── contracts/            # versioned public request/result/evidence models
├── adapters/             # AgentTeams and future client identity adapters
├── providers/            # sandbox, filesystem and future external providers
├── evidence/             # append-only recording and replay verification
└── policy_mcp.py         # MCP transport entry point and environment wiring
```

Existing top-level modules remain compatibility entry points during migration.
No package split should be performed unless it removes a real AgentTeams coupling or improves a tested public boundary.

## Commands

The existing quality gates remain the baseline during migration:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\ruff.exe check .
.venv\Scripts\mypy.exe src tests
.venv\Scripts\pip-audit.exe
```

The first Gateway vertical slice must additionally provide one documented local command that starts the MCP Gateway and one command that performs a denied call and a successful sandboxed call.

## Testing Strategy

- Contract tests: Pydantic round-trip, aliases, digest binding and stable error codes;
- Policy tests: identity mismatch, expired Grant, replay, parameter tampering, path escape, approval and provider mismatch;
- Provider tests: deterministic fake Provider plus live Docker sandbox tests when Docker is available;
- Evidence tests: append-only writes, digest verification, incomplete recording failure and replay;
- Adapter tests: AgentTeams consumer mapping must produce the same core `PolicyContext` as the local adapter;
- End-to-end test: one successful and at least five denied tool calls through the MCP boundary.

## Boundaries

- **Always:** validate untrusted input at the transport boundary; use canonical JSON for digests; fail closed; record actual identity, policy, provider and result; run focused tests before changing public contracts.
- **Ask first:** adding a dependency; changing the public MCP schema; changing Grant semantics; changing CI or release verification; adding a second external provider.
- **Never:** expose signing keys or gateway assertions to Agents; execute an unapproved command; fall back from Docker to host execution; overwrite Evidence; claim AgentTeams Full support without a real external run.

## Success Criteria

The MVP is complete only when all of the following are true:

1. A non-AgentTeams client can perform one approved sandboxed call through MCP without importing AgentTeams modules.
2. The same client receives deterministic denial for missing, expired, replayed, tampered and identity-mismatched Grants.
3. The successful call and every denial produce structured, redacted Evidence with verifiable digests.
4. AgentTeams remains covered by an adapter contract test and uses the same core policy path.
5. A clean host can run the local Gateway path from a short quickstart without a Matrix, MinIO or Higress deployment.
6. The complete quality gate is green, including the known CI snapshot and repository lint issues being resolved before the first implementation slice is merged.

## Open Questions

- Which first non-AgentTeams client should be supported: a minimal MCP client fixture, an OpenAI-compatible tool client, or another existing Agent runtime?
- Should `SkillExecutionGrant` remain the public name, or should the gateway expose a more general `ToolExecutionGrant` while retaining a compatibility alias?
- Is Docker the only MVP provider, or should a deterministic in-process fake be exposed for local development while keeping host execution explicitly disabled by default?
