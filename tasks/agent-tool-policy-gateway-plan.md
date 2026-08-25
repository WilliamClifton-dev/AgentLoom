# Implementation Plan: Agent Tool Policy Gateway

## Overview

收缩 AgentLoom 的产品边界：保留现有 Policy Broker、Grant、Tool Contract、沙箱和 Evidence 能力，把 AgentTeams 降为适配器，交付一个不依赖 AgentTeams 部署即可运行的 MCP Tool Policy Gateway。

## Architecture Decisions

- 核心策略和执行编排必须与 MCP transport、AgentTeams、Higress 和 Matrix 解耦。
- 先复用现有 `SkillExecutionGrant`、`ToolExecutionEnvelope`、`ToolCallEventRecord` 和 Docker Provider；不因为改名而复制两套授权模型。
- 第一条产品闭环使用一个沙箱测试工具，先证明权限控制和 Evidence 价值，再扩展外部工具。
- AgentTeams 适配器通过 `PrincipalResolver`/`PolicyContext` 接入核心，不允许核心模块反向 import AgentTeams 运行时。
- 任何 Grant 或 Evidence 公共字段变化都必须先更新 Contract 测试和设计记录。

## Task List

### Phase 0: Baseline and Specification

- [x] Task 1: 固定 Agent Tool Policy Gateway 规格和非目标。
  - Acceptance: `docs/specs/agent-tool-policy-gateway.md` 定义用户、调用链、核心契约、失败码、边界和成功标准。
  - Verify: 人工审阅规格；不修改运行时代码。
  - Files: `docs/specs/agent-tool-policy-gateway.md`

- [x] Task 2: 建立迁移计划和任务依赖。
  - Acceptance: 任务按 Contract -> Policy Core -> Provider -> Adapter -> Docs 顺序排列，每个任务有验证方式。
  - Verify: 检查每个任务的依赖、验收条件和回滚点。
  - Files: `tasks/agent-tool-policy-gateway-plan.md`, `tasks/agent-tool-policy-gateway-todo.md`

### Checkpoint: Specification

- [ ] Human confirms the first non-AgentTeams client and Grant naming direction.
- [ ] Existing AgentTeams flow remains unchanged until the first standalone slice passes.

### Phase 1: Neutral Core Contract

- [ ] Task 3: 提取 transport-neutral 的 `PrincipalResolver`、`PolicyContext` 和 `ToolProvider` Protocol。
  - Acceptance: 核心模块不 import AgentTeams/Higress/Matrix；现有 Policy Broker 行为保持兼容。
  - Verify: Contract tests、mypy、现有 Policy Broker tests。
  - Dependencies: Task 1-2.
  - Files likely touched: `src/agentloom/policy.py`, `src/agentloom/contracts/`, `src/agentloom/gateway/`, `tests/test_policy_broker.py`。

- [ ] Task 4: 将 Grant issuance 从强绑定 `TaskRecord.status == VERIFYING` 的路径抽象为可替换的 authoritative context provider。
  - Acceptance: AgentTeams 使用现有 Task provider；本地 Gateway 使用静态或 SQLite context provider；两者生成同一 Grant contract。
  - Verify: issuer tests covering missing context, wrong policy version, expiry and approval.
  - Dependencies: Task 3.
  - Files likely touched: `src/agentloom/policy.py`, `src/agentloom/contracts/grant.py`, `tests/test_grant_issuer.py`。

### Phase 2: First Vertical Slice

- [ ] Task 5: 增加独立 MCP Gateway local profile。
  - Acceptance: 无 AgentTeams、Matrix、MinIO 或 Higress 时可启动；默认不允许 host execution；只加载明确的 policy/catalog/database 配置。
  - Verify: clean temporary workspace smoke test and startup rejection tests。
  - Dependencies: Task 3-4.
  - Files likely touched: `src/agentloom/policy_mcp.py`, `src/agentloom/cli.py`, `tests/test_policy_tool_e2e.py`。

- [ ] Task 6: 完成一个成功和五个拒绝场景的 MCP E2E。
  - Acceptance: approved sandbox call succeeds; missing Grant, replay, parameter mismatch, path escape and identity mismatch all return stable failure codes and no provider side effect.
  - Verify: focused pytest plus Docker live tests where available.
  - Dependencies: Task 5.
  - Files likely touched: `tests/test_gateway_e2e.py`, `tests/test_policy_broker.py`, `src/agentloom/providers/`。

### Checkpoint: Standalone Gateway

- [ ] Local non-AgentTeams client completes the approved call.
- [ ] All denial paths are fail-closed and recorded.
- [ ] Existing AgentTeams tests still pass unchanged.

### Phase 3: Adapter and Usability

- [ ] Task 7: 将 AgentTeams/Higress consumer mapping 放入 adapter boundary。
  - Acceptance: AgentTeams adapter produces the same core identity/context shape; core package can be imported without AgentTeams deployment files。
  - Verify: adapter contract tests and existing deployment tests.
  - Dependencies: Task 6.
  - Files likely touched: `src/agentloom/adapters/agentteams.py`, `tests/test_agentteams_deployment.py`, `src/agentloom/policy_mcp.py`。

- [ ] Task 8: 写独立 Gateway quickstart 和最小 policy example。
  - Acceptance: clean host can start Gateway and reproduce one allow/deny flow using a short command sequence; no competition-only claims remain in the quickstart.
  - Verify: clean temporary environment or scripted smoke test.
  - Dependencies: Task 6-7.
  - Files likely touched: `docs/deployment/`, `README.md`, `README.en.md`。

### Checkpoint: Product Validation

- [ ] Three target users can understand the value and run the first call without reading the full architecture document.
- [ ] At least one external Agent client or team agrees to trial the Gateway.
- [ ] No new dependency or external provider is added before this checkpoint.

## Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Existing Grant model is too coupled to task workflow | High | Extract an authoritative context Protocol; keep compatibility fields and tests first |
| Gateway remains AgentTeams-specific in practice | High | Make standalone local profile the first vertical slice and test imports without AgentTeams |
| Security model becomes weaker during generalization | Critical | Preserve fail-closed, nonce, digest, path and provider-boundary tests before moving code |
| Scope expands into a general policy language | High | Start with one explicit policy source and one sandbox Provider |
| No real users adopt it | High | Stop feature work after the standalone slice and run three user trials |

## Open Questions

- First external client and exact Grant naming require human confirmation before Task 3.
- Whether to keep the repository name AgentLoom or introduce a Gateway-focused distribution name should be decided after the first user trial.
