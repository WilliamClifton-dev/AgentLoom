<p align="center">
  <img src="docs/assets/agentloom-logo.jpg" alt="AgentLoom - Multi-Agent Governance" width="360">
</p>

# AgentLoom

简体中文 | [English](README.en.md)

面向多 Agent 软件修复的治理型、证据优先 SkillOps 平台，构建于
[AgentTeams](https://github.com/agentscope-ai/AgentTeams) 之上。

AgentLoom 将第三方 Agent Skill 转化为可审查、可授权、可测试、可审计的能力。
参赛场景从生产风格的修复任务开始，以经过独立验证、可回放的证据结束。

> **当前证据基线（2026-08-16）：** AgentTeams `v1.1.2` 使用
> `minimax-cn / MiniMax-M2.5` 完成了 `Administrator -> Manager -> Investigator
> -> Verifier -> 已认证 Higress -> Policy Broker -> 不可变 Docker pytest 沙箱`
> 链路，并产生且仅产生一个受治理的 `SUCCEEDED` ToolCall。历史 clean-clone
> Lite 证据为 **339 passed / 0 failed / 3 skipped（可选 Docker 测试）**，冻结
> `v0.1.0` 门禁为 **375 passed / 3 skipped**。当前 public main 的 GitHub Actions
> 会构建不可变沙箱镜像，门禁为 **379 passed / 0 skipped**；Task 24 两模式基准为
> **6 PASSED / 0 NOT_RUN**。Skill 目录状态为 **2 PUBLISHED / 4 QUARANTINED**；
> 团队原创 `patch-scope-validator` v1.0.1 的三次治理调用均已严格重开。
> Human L2 审批为 `APPROVED`，上游 PR
> [#1141](https://github.com/agentscope-ai/AgentTeams/pull/1141) 仍为 `OPEN`。
> 真人录制、匿名公开播放和正式 `v0.1.0` Release 均已验证。最终八项 P0
> 提交包已完成审计，SHA-256 为
> `0c5dfeb0ba6665609a14129a76cc1c239aed882a17e930c144aa5d3b88f6c306`；
> 目前只有竞赛页面提交仍是 Human 负责的检查点。

## 参赛证据

- 赛道：Agent Infra
- 方向：软件研发全流程协同
- 运行时：AgentTeams/HiClaw `v1.1.2`
- 当前付费证据 Provider：`minimax-cn / MiniMax-M2.5`
- 当前结果：Task 24 三案例两模式矩阵 6/6 完成；Task 17 另行证明一个成功
  ToolCall 经过 Higress、Policy Broker 和全新 Docker 沙箱的完整治理链路
- 当前 public main 门禁：启用不可变 Docker 沙箱测试后 379 passed / 0 skipped；
  冻结 `v0.1.0` 门禁：375 passed / 3 skipped；clean-clone Lite 证据：
  339 passed / 0 failed / 3 skipped；Ruff、strict mypy、pip-audit、语法、
  迁移、Diff 和密钥检查通过
- Skill 状态：`code-review-and-quality`（上游）和 `patch-scope-validator`（团队原创）
  为 `PUBLISHED`，另外四个上游 Skill 为 `QUARANTINED`；三次原创 Skill
  调用均可按完整身份闭包重开
- 提交状态：P0 提交包、公开 Demo 和 `v0.1.0` Release 已完成；竞赛页面提交待完成

当前证据和提交声明索引见[初赛提交记录](docs/competition/agentloom-preliminary-submission.md)。
最终包的精确文件清单与哈希见[公开提交包 manifest](docs/competition/submission-package-manifest.json)，
Human 操作步骤见[赛事提交操作清单](docs/competition/submission-operator-checklist.zh-CN.md)。

## 架构

```mermaid
flowchart LR
    Administrator["Administrator"] --> Manager["AgentTeams Manager"]
    Manager --> Investigator["Investigator"]
    Investigator -->|"受治理委派"| Verifier["Verifier"]
    Verifier --> Higress["已认证 Higress"]
    Higress --> Broker["AgentLoom Policy Broker"]
    Broker --> Grant["签名且限定作用域的 Grant"]
    Broker --> Sandbox["不可变 Docker pytest 沙箱"]
    Broker --> Evidence["可回放 ToolCall 证据"]
    Human["Human L2 审批者"] --> Broker
```

Manager 无权调用 Policy Broker，Worker 不持有 Broker 签名密钥。受治理的
ToolCall 必须同时具备已认证 Worker 身份，以及短时有效、绑定 Consumer、参数和
单次使用的 `SkillExecutionGrant`。Broker 持久化 nonce 消费记录和可回放事件摘要，
再把不可信 pytest 放入全新、禁网、只读挂载工作区的 Docker 沙箱运行。Policy、
身份、沙箱和 Agent 作用域都是运行时控制，不只存在于 Prompt 或文档中。

完整设计见 [AgentLoom 架构设计](docs/architecture/agentloom-architecture.md)。

## 无模型快速开始

前置条件：Python 3.12 和 Git。以下命令不会调用模型或付费 API。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check .
.venv\Scripts\mypy src tests
```

无需 LLM 或云额度即可运行任一确定性修复案例：

```powershell
.venv\Scripts\python -m agentloom.mock_repair `
  --case-root .\demo\cases\severity-normalization `
  --output-root .\artifacts\demo\severity-normalization
```

将 `severity-normalization` 替换成 `pagination-boundary` 即可运行第二个案例。
本地证据控制面板的启动方式为：

```powershell
.venv\Scripts\agentloom tui
```

清洁 clone 的失败关闭门禁只有一个入口：
[`scripts/verify-clean-reproduction.ps1`](scripts/verify-clean-reproduction.ps1)。
它创建全新证据、运行确定性 Demo 和全部质量门禁，并输出脱敏 JSON 摘要及 SHA-256。
详见[清洁环境复现指南](docs/deployment/clean-environment-reproduction.md)和
[五分钟快速开始](docs/deployment/quickstart.md)。

## 完整 AgentTeams 部署

部署、Provider 激活、Policy Broker、Higress 和严格 E2E 的权威说明位于
[deploy/agentteams/README.md](deploy/agentteams/README.md)。Full 模式要求预先安装
锁定版本的 AgentTeams/HiClaw `v1.1.2`；AgentLoom 不提供单容器独立发行版。

已固化的维护者付费证据只使用 MiniMax。新的 Live 探测可按场景选择 MiniMax 或
StepFun，但必须使用唯一 run ID 并记录准确 Provider/模型。下游管理员也可以用
自己的额度，通过经过验证、使用公共 HTTPS 的
[OpenAI-compatible Provider Profile](docs/specs/openai-compatible-provider-profile.md)
接入 Provider。无密钥 Profile 只保存 Provider 元数据和环境变量名称，不保存 API
Key。Provider 只有通过验证后才会激活，付费连接探测还必须显式开启确认开关。

Provider Profile 验证只证明配置结构正确。配置、连接测试和严格 AgentTeams E2E
是三个独立门禁。“OpenAI-compatible”并不证明任意模型都支持所需的角色消息、
流式输出、工具调用、reasoning 参数、上下文长度或修复行为。厂商私有协议需要单独
实现 Adapter，不能直接视为即插即用。

## 已实现能力

- 面向 Skill、Tool 和 Verifier 的稳定 Capability、Provider、Consumer 边界，
  不同实现复用同一组契约测试
- Agent 身份、Skill 元数据、Evidence、验证、检测、Grant、任务和可回放任务事件的
  严格 Pydantic 契约
- HMAC 签名 Grant：绑定有效期、Consumer、审批、参数并防重放；Broker 重启后仍
  持久化已消费 nonce 摘要
- 失败关闭的检测流水线和确定性 L1 Skill 检查
- 具有来源锁定、严格 Schema 和发布/隔离状态的 Skill 目录：一个上游 Skill 和一个
  团队原创 Skill 已发布，另外四个上游 Skill 隔离
- FastAPI 任务 API、乐观状态迁移、追加式因果事件及可逆 SQLite/Alembic 持久化
- 位于 Higress 身份认证和白名单之后的 Streamable HTTP Policy Broker
- 带请求/结果摘要和本地 Evidence 的受治理 ToolCall 事件
- 运行于锁定镜像中的 pytest Tool Provider：禁网、只读工作区、限制输出和超时，
  并验证容器清理
- 锁定版本的 AgentTeams Manager、三个业务 Agent 身份和 Human 资源
- 无密钥 Provider Profile、无模型校验和显式启用的连接探测
- 绑定精确 Matrix event ID 的 Investigator-to-Verifier 受治理委派
- 确定性本地修复案例、隐藏测试、补丁范围约束、回放查看器和 Textual 证据面板
- Human L2 审批证据，以及仍等待维护者审查的上游 PR #1141 `humanMembers` 修复

## 本地 Broker 开发

创建本地数据库，并用至少 32 字节、仅注入进程环境的开发密钥启动验证型 stdio
Broker：

```powershell
.venv\Scripts\alembic upgrade head
$env:AGENTLOOM_POLICY_SIGNING_KEY = "replace-with-a-local-development-secret"
.venv\Scripts\python -m agentloom.policy_mcp
```

旧的宿主机 pytest runner 只允许用于可信本地开发，并同时要求
`AGENTLOOM_SANDBOX_BACKEND=local-development` 和显式确认
`AGENTLOOM_ALLOW_HOST_TEST_EXECUTION=true`。它不是容器或网络沙箱，绝不能执行
不可信测试。AgentTeams 启动器使用锁定的 Docker 后端，也不会导出该确认变量。
签名密钥、模型凭据和 Provider 原始密钥都不得写入已提交的 MCP、Worker 或 Provider
Profile 配置。

## 历史证据

> 以下内容仅为审计和复现而保留，**不是当前证据基线**。Qwen、DeepSeek 因账户
> 无余额继续禁用。MiniMax 和 StepFun 均已获得订阅调用授权，但每次新运行必须使用
> 唯一 run ID 并记录准确 Provider/模型；StepFun 证据不得混入只允许 MiniMax 的
> Task 24 版本化基准。不得把历史付费链路冒充为新运行。

- 2026-08-04，Qwen `qwen3.7-plus` 曾完成无人值守修复，并通过独立的可见测试、
  主机专属隐藏测试和静态检查。生成补丁 SHA-256 为
  `7d9d571a833eabaedf97eac73dad50f6290bfa332d3ef504882398ba2e6d0833`。
  严格运行证据仍位于
  `artifacts/agentteams/live-repair-pagination-qwen-unattended-03.json`，独立验证证据仍位于
  `artifacts/live-repair/AL-LIVE-PAGINATION-UNATTENDED-20260804-03/verified/artifacts/`。
- 更早的 StepFun 四角色回滚和 DeepSeek 消息基线证据仍作为 Human L2 审批记录的
  历史输入。脱敏摘要见
  [L2 审批与上游贡献证据](docs/competition/l2-approval-and-upstream-contribution-evidence.md)。
- 历史回放入口保留为 `scripts/competition-demo.ps1 -Mode replay` 和
  `scripts/competition-rollback-demo.ps1 -Mode replay`。回放无需模型；Live 模式是独立、
  必须明确付费并授权的操作。

## 后续路线图

1. 完成竞赛页面提交并保留平台回执。
2. 在第二台清洁 Windows/Docker 主机验证 Full bootstrap，并发布兼容性记录。
3. 评测四个处于隔离状态的上游 Skill；只有通过 Skill Eval 和来源门禁后才发布。
4. 将受治理修复结果接入一个受控的真实 Issue/PR 工作流。

## 开源与来源

AgentLoom 代码采用 Apache-2.0 许可证。上游运行时、Skill 内容、依赖和设计参考保留
各自许可证及署名要求。详见 [THIRD_PARTY.md](THIRD_PARTY.md)、
[provenance/sources.yaml](provenance/sources.yaml) 和 [CHANGELOG.md](CHANGELOG.md)。

## 安全

MVP 阶段只使用合成 fixture 和隔离仓库。不要把个人 SSH 目录、生产凭据或无关主机
路径挂载到 Worker 或沙箱。安全问题请私下联系仓库所有者。
