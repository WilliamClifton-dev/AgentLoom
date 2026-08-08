# AgentLoom 初赛提交材料

> 团队：零号工位
>
> 参赛赛道：赛题三 - 软件研发全流程协同
>
> 项目：AgentLoom：多智能体 Skill 治理与可验证修复平台
>
> 材料状态：初赛内容底稿；StepFun 真实回滚与真人 L2 审批证据已固化，PPT、PDF、录屏和最终提交包尚待生成
>
> 依据：赛事参赛手册、官方 19 页 PPT 模板、当前仓库及本地可验证证据

## 1. 提交页面怎么填

| 页面字段 | 选择或填写内容 | 提交说明 |
| --- | --- | --- |
| 阶段 | 初赛 | 当前页面已经选中，无需修改 |
| 作品名称（必填） | `AgentLoom：多智能体 Skill 治理与可验证修复平台` | 不只写 AgentLoom，副标题直接说明作品价值 |
| 代码仓库 | `https://github.com/WilliamClifton-dev/AgentLoom` | 仓库已设为公开；正式提交前仍需确认默认分支包含最终提交并可在未登录状态访问 |
| Demo 链接 | 暂时留空 | 该字段在当前页面没有必填星号。最终录屏上传后再填写公开视频链接；不要填 `localhost` 或本机文件路径 |
| 作品附件（必填） | `AgentLoom-初赛提交包.zip` | PPT 完成并导出 PDF 后再制作 ZIP；不要现在上传半成品。单文件不超过 1200 MB，本赛段累计不超过 3600 MB |
| 赛题（必填） | `赛题三：软件研发全流程协同` | AgentLoom 的主闭环是软件缺陷调查、修复、验证和治理，不应选零人工运维或智能客服 |
| 个人职务或身份 | `独立开发者（多智能体系统 / Agent Infra）` | 独立参赛，不虚构产品、算法、测试等其他成员 |

推荐 ZIP 结构：

```text
AgentLoom-初赛提交包.zip
├── 01-AgentLoom-作品简介.pdf
├── 02-AgentLoom-初赛方案.pptx
├── 03-AgentLoom-初赛方案.pdf
├── 04-Agent-Identity清单.pdf
├── 05-核心Skill清单.pdf
├── 06-开源与第三方依赖说明.pdf
├── 07-StepFun回滚证据.pdf
└── README.txt
```

ZIP 中不放 API Key、`.env`、Human 密码、访问令牌、个人绝对路径、未脱敏 Trace、缓存目录或完整 `artifacts/`。代码由 GitHub 仓库提供，ZIP 只放评审材料和必要的脱敏证据截图。

## 2. 500 字以内作品简介

以下正文共 **445 个字符（含空格）、413 个字符（不含空格）**，可直接使用：

> AgentLoom 是基于 AgentTeams 的多智能体 Skill 治理与可验证软件修复平台。它面向团队引入 GitHub 第三方 Skill 时来源不清、权限过大、效果难评测、执行不可追溯等问题，将 Skill 纳入“发现、溯源、扫描、评测、发布、路由、授权、执行、验证、回滚”的生命周期。人把带失败测试、日志、白名单和回滚要求的 Issue 交给 Manager；Manager 拆成调查、受限修复和独立验证，由 Investigator、Implementer、Verifier 通过结构化产物协作。Policy Broker 通过 MCP 对工具、路径、参数和时效进行最小权限控制，L2 高风险操作必须由 Human 审批；全过程生成可审计 Evidence。当前已在 AgentTeams v1.1.2 上完成三 Agent 协作、真实模型修复、独立隐藏测试验证、TUI、失败回滚与审批基础链路。项目计划以 Apache-2.0 开源，自研治理层与第三方工作流内容明确分界。

## 3. 一句话定位与价值

一句话定位：**AgentLoom 把来源各异的 Agent Skill 变成在 AgentTeams 中可准入、可授权、可验证、可审计、可回滚的工程资产，并用软件缺陷修复证明完整闭环。**

核心问题：

1. GitHub Skill 来源、许可证和版本容易漂移，团队无法证明“执行的到底是哪一版”。
2. 工作流文档本身不能约束工具、路径、参数、网络和外部写操作。
3. 生成补丁不等于问题被修复，执行 Agent 自检也不等于独立验证。
4. 多 Agent 对话、人工审批、失败回滚和最终结论缺少统一证据链。

核心价值：

- 对研发团队：缩短第三方 Skill 的评估和接入时间，同时降低供应链与越权风险。
- 对平台团队：以统一 Schema、MCP Policy Broker 和 Evidence 接口管理不同模型与工具。
- 对评审者：可从任务、角色消息、Skill 版本、授权、补丁、测试到 verdict 完整复现。

## 4. PPT 纲要（严格对应官方 19 页模板）

可直接交给 AI 执行的逐页文案、证据素材、模板继承和 QA 规范见
[PPT 生产规格](ppt-production-spec.md)。

### 第 1 页：封面

- 标题：AgentLoom
- 副标题：多智能体 Skill 治理与可验证修复平台
- 赛题：赛题三 - 软件研发全流程协同
- 团队：零号工位
- 身份：独立开发者

### 第 2 页：P0 一页总览

- 痛点：第三方 Skill 来源不清、权限不可控、效果不可证、失败不可回退。
- 方案：AgentTeams Manager + 三业务 Agent 结构化交接 + SkillOps 生命周期 + MCP Policy Broker + 独立验证。
- 主流程：Issue -> Manager 规划 -> Investigator 调查 -> Implementer 受控修复 -> Verifier 独立验证 -> 审批/回滚 -> Evidence 报告。
- 已验证：AgentTeams v1.1.2、三业务 Agent、真实模型修复、StepFun 真实回滚、隐藏测试与 TUI。
- 差异化：不是通用 Coding Agent，而是跨场景可复用的 Skill 治理控制面。

### 第 3 页：目录

1. 场景与价值
2. 方案总览
3. 多 Agent 协同
4. Skill 工程
5. 工程验证与安全
6. 开放与开源
7. 进展与规划
8. 团队

### 第 4 页：章节页 - 场景与价值

只保留章节标题和一句话：让第三方 Skill 从“可阅读提示词”升级为“可治理工程资产”。

### 第 5 页：场景、痛点与目标用户

- 场景：研发团队把一条带失败测试、日志、修改白名单和回滚要求的生产风格 Issue 交给 Manager，由三个不同职能 Agent 协作完成可验证修复。算法缺陷可以很小，但复现、权限、独立验收、审批和失败回滚必须同时成立。
- 用户：研发负责人、Agent 平台工程师、安全/合规负责人。
- 展示 4 个痛点和 3 类用户价值。
- 明确边界：修复 Demo 是参考场景；AgentLoom 的产品本体是 SkillOps 治理。

### 第 6 页：章节页 - 方案总览

只保留章节标题和价值句：在 AgentTeams 原生协同之上增加强制治理和证据闸门。

### 第 7 页：总体架构与技术方案

建议画五层架构图：

```text
Element / TUI / CLI
        |
AgentTeams Manager + Team Room
        |
Investigator -> Implementer -> Verifier
        |
Skill Registry + L1/L2/L3 Detection + Policy Broker MCP
        |
Sandbox / Test Runner / MinIO / SQLite / Evidence Report
```

- AgentTeams 管理 Manager、Worker、Team、Human、Matrix 和共享产物。
- AgentLoom 管理 Skill 准入、风险、路由、授权、任务状态和证据。
- Qwen/DeepSeek/StepFun 等模型通过兼容接口配置注入，不写死在业务契约中。
- Python 3.12、FastAPI、Pydantic、SQLAlchemy、MCP、Typer/Textual/Rich。

### 第 8 页：章节页 - 多 Agent 协同

只保留章节标题和一句话：三个角色权责分离，任何 Agent 都不能独自宣布修复成功。

### 第 9 页：Agent 角色与完整协作流

- 顶部先画既有链路：`Human -> Manager -> Investigator -> Implementer -> Verifier`。
- 左侧放三张角色卡：Investigator、Implementer、Verifier。
- 中间放状态流：Received -> Manager 规划 -> Investigating -> Implementing -> Verifying -> Completed。
- 风险分支：Implementing -> Awaiting Approval -> Approved/Rejected。
- 失败分支：Verifying -> Rolling Back -> Retry/Failed。
- 强调 Manager 是 AgentTeams 编排资源，不计入三个业务 Agent。
- 说明 `agentloom-investigator` 在 AgentTeams Team 资源中兼任 leader 以满足框架拓扑，但 Agent Identity 清单仍只有三个业务 Agent，不新增 TeamLeader 角色。
- 加一句单模型对照：`单模型能生成补丁，但不能天然保证身份隔离、独立验收、L2 审批、失败回滚和 Evidence 链。`
- 页面下方列出交接物：RootCauseReport、PatchArtifact、VerificationResult/RiskReport。

### 第 10 页：章节页 - Skill 工程

只保留章节标题和一句话：保留上游来源，但用本项目契约约束其可执行边界。

### 第 11 页：核心 Skill、复用与生命周期

- 展示五个上游 Skill 与一个团队原创 Skill 的表格。
- 生命周期：发现 -> 隔离 -> 溯源/哈希 -> L1 静态扫描 -> L2 沙箱评测 -> L3 场景回归 -> 审批发布 -> 监控 -> 回滚。
- 绑定关系：Debugging -> Investigator；TDD -> Implementer；Review/Security -> Verifier；Skill Selection -> Manager。
- 明确 `addyosmani/agent-skills` 是工作流内容源，不是 Agent 编排、授权或验证运行时。
- 标注真实状态：五个上游 Skill 已锁定来源、commit 和哈希，当前仍为 `QUARANTINED`，待 Eval 后发布。

### 第 12 页：章节页 - 工程、验证与安全

只保留章节标题和一句话：每个成功结论都必须有角色归属、不可变产物和独立验证证据。

### 第 13 页：运行证据、可观测、安全与云选择

- 真实证据：AgentTeams v1.1.2；Qwen 无人值守修复；StepFun 四角色回滚；隐藏测试通过；补丁与回滚计划哈希。
- 工程检查：全量 pytest、Ruff、strict mypy、pip-audit 全通过。
- 安全：L0-L3、短时参数绑定 Grant、路径/工具白名单、Human 审批、密钥脱敏。
- 可观测：Task/Step/Agent/Skill/Grant/ToolCall/Artifact/Verdict 全链路 ID。
- 当前缺口：最终录屏和提交材料待完成；AgentTeams 上游缺陷修复 PR 已提交，仍在等待维护者审核，不声称已合并。

### 第 14 页：章节页 - 开放与开源

只保留章节标题和一句话：原创控制面开源，第三方内容保留来源、许可证和不可变版本。

### 第 15 页：可复用产物、协议与依赖披露

- Apache-2.0 开源：控制面、Schema、Policy Broker、样例、测试、部署脚本和文档。
- 直接依赖：AgentTeams v1.1.2（Apache-2.0）。
- 内容来源：addyosmani/agent-skills（MIT，未改写为原创，当前未 vendoring）。
- 设计参考：DeepSec、VulnClaw、mcp-scan、Promptfoo、SWE-bench 等，只披露所借鉴思想。
- 可复用输出：Agent Identity Schema、Skill Manifest、Execution Grant、Evidence Bundle、AgentLoom-Bench Case。

### 第 16 页：章节页 - 进展与规划

只保留章节标题和一句话：主修复链与真人审批已跑通，提交前聚焦可复现演示和材料一致性。

### 第 17 页：当前进展、里程碑与风险

三列展示：

- 已完成：AgentTeams 部署、三 Agent、真实修复与 StepFun 回滚 E2E、真人 L2 审批、隐藏测试、TUI、检测/授权/回滚基础。
- 提交前：演示录屏、PPT/PDF、公开仓库检查、提交包一致性审计。
- 复赛候选：将 AgentLoom 的修复结果接入真实业务仓库 Issue/PR、更多 Skill Eval、第二业务场景、OTLP 后端、可选云 Skill。

主要风险：模型波动、AgentTeams 版本变化、第三方 Skill 漂移、Demo 环境复杂、范围过大。每项风险都配固定版本、回放证据、降级方案和非目标约束。

### 第 18 页：章节页 - 团队

只保留章节标题和一句话：独立开发，架构、实现、验证和材料均有 Git 证据链。

### 第 19 页：团队背景与分工

- 团队名：零号工位。
- 成员数：1 人。
- 身份：独立开发者（多智能体系统 / Agent Infra）。
- 分工：需求与赛题对齐、架构、AgentTeams 集成、后端与 TUI、测试、安全、文档和 Demo。
- 事实表达：用 Git 提交、测试、运行 Evidence 说明工作，不虚构企业客户、论文、奖项或额外成员。

## 5. Agent Identity 清单

Manager 是 AgentTeams 编排资源，负责计划、委派、状态聚合和 Human 入口；它不作为第四个业务 Agent 申报。以下三个 Agent 的职能、权限和产物明确不同。

| Name | Role | Capabilities | Inputs | Outputs | Dependencies | Decision Boundary | Trace |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `agentloom-investigator` | 根因调查与证据收集 | 读取代码、Issue、日志和失败测试；搜索调用链；提出根因候选 | 仓库只读快照、Issue、日志、失败测试、验收条件 | `RootCauseReport`、`EvidenceRef`、修复约束 | AgentTeams Worker、Debugging Skill、Policy Broker、MinIO、Team Room | L0 只读；禁止改文件、联网写入或宣称最终成功 | Worker Session、Matrix Event、查询范围、证据 ID、置信度、模型 ID |
| `agentloom-implementer` | 最小补丁设计与实施 | 根据根因选择已发布 Skill；在隔离区修改白名单路径；运行局部测试 | `RootCauseReport`、任务约束、验收条件、`SkillCandidateSet` | `PatchArtifact`、`ImplementationNotes`、局部测试证据 | AgentTeams Worker、TDD Skill、Policy Broker、Sandbox、MinIO | L1 隔离写；禁止批准自己的补丁；新增依赖、网络和外部写入升级为 L2 | Worker Session、Skill 版本、Grant、Diff、命令、退出码、产物哈希 |
| `agentloom-verifier` | 独立验证与风险审查 | 在清洁快照重放补丁；运行目标/回归/隐藏测试；审查 Diff 和风险 | 冻结的 `PatchArtifact`、验收条件、原始证据 | `VerificationResult`、`RiskReport`、`Badcase` | AgentTeams Worker、Review/Security Skill、独立 Sandbox、MinIO | 可判定 `PASSED/FAILED/UNSAFE/UNCERTAIN`；禁止修改补丁或降低验收标准 | 独立 Session、测试输出、静态检查、EvidenceRef、verdict、模型 ID |

协作约束：

- Investigator 不能写代码；Implementer 不能自我放行；Verifier 不能修改被验证补丁。
- Manager 必须依据结构化交接物推进状态，不能只依赖自由对话。
- 只有 Verifier 的 `PASSED` 且策略无阻断项时，任务才能进入 `COMPLETED`。
- `UNCERTAIN` 不是成功；必须补充证据或请求 Human 决策。

## 6. 核心 Skill 清单

| Skill | 类型/场景 | 输入 -> 输出 | 调用条件 | 依赖 | 失败处理 | 权限与安全 | 绑定/复用 | 当前状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `debugging-and-error-recovery` | 上游；缺陷定位 | Issue、快照、日志 -> `RootCauseReport`、`EvidenceRef` | 输入完整且失败可复现 | Repository Search、Test Reader | 证据不足返回 `INSUFFICIENT_EVIDENCE`；工具失败重试一次后阻塞 | L0，只读，禁网、禁写 | Investigator；可复用于事故调查 | 来源、commit、MIT、哈希和 Manifest 已锁定；`QUARANTINED`，待 Eval/发布 |
| `test-driven-development` | 上游；受限修复 | 根因、验收标准、白名单 -> `PatchArtifact`、测试证据 | 根因达到证据阈值 | Patch Adapter、Test Runner | 测试失败先回滚；超过预算交回 Manager | L1 隔离写；新增依赖/联网/外部写升级 L2 | Implementer；可复用于 Python 修复 | 来源、commit、MIT、哈希和 Manifest 已锁定；`QUARANTINED`，待 Eval/发布 |
| `code-review-and-quality` | 上游；独立审查 | 冻结补丁、验收条件 -> `ReviewFindings`、verdict | 补丁已冻结并进入清洁环境 | Repository Search、Test Reader | 缺证据返回 `UNCERTAIN`；不得修改补丁 | L0，只读，与 Implementer 会话隔离 | Verifier；可复用于合并前审查 | 来源、commit、MIT、哈希和 Manifest 已锁定；`QUARANTINED`，待 Eval/发布 |
| `security-and-hardening` | 上游；安全闸门 | Diff、依赖、ToolCall、权限 -> `RiskReport` | 代码/依赖变化或风险触发 | Static Check、Policy Engine | 扫描异常不放行，返回 `UNSAFE/UNCERTAIN` | 只读；规则不可由被审 Agent 修改 | Verifier；也用于 Skill 准入 | 来源、commit、MIT、哈希和 Manifest 已锁定；`QUARANTINED`，待 Eval/发布 |
| `using-agent-skills` | 上游；候选 Skill 选择 | 任务、角色、权限、风险 -> `SkillCandidateSet` | 任务已计划且角色已确定 | Skill Registry | 无匹配则 `NO_COMPATIBLE_SKILL`；不自动扩大权限 | L0，只读 Registry；选择不等于授权 | Manager；可跨业务场景复用 | 来源、commit、MIT、哈希和 Manifest 已锁定；`QUARANTINED`，待 Eval/发布 |
| `skill-supply-chain-audit` | 团队原创；第三方 Skill 准入 | Git URL、路径、commit、Manifest -> `ProvenanceReport`、`RiskReport`、发布建议 | 导入、升级或重新发布第三方 Skill | Git Reader、许可证/哈希、Scanner、Eval Runner | 来源失效、许可不明、哈希变化或评测失败均保持隔离 | 默认不可信；禁真实密钥；发布和高风险例外需 Human | Manager + Verifier；可迁移到客服、运维等 SkillOps 场景 | 设计和底层目录/策略能力已有；独立可执行 Skill 与完整 Eval 尚待完成 |

所有上游 Skill 固定来源：`addyosmani/agent-skills` commit `7829ffd90d973b6325f5f12f1b1226dcace74443`，MIT。上游内容提供成熟方法；AgentLoom 自研并负责 Manifest、Schema、哈希、风险、角色绑定、权限、Grant、评测、Evidence 和回滚。不得把上游内容包装成团队原创。

## 7. 完整协作闭环

1. **接收任务**：Manager 生成稳定 `taskId`、验收标准、预算和仓库只读快照。
2. **制定计划**：AgentTeams Manager 创建步骤依赖，通过 Team Room 委派 Investigator。
3. **调查根因**：Investigator 复现失败并输出带证据引用的 `RootCauseReport`。
4. **选择 Skill**：Registry 只返回角色、场景和风险匹配且处于 `PUBLISHED` 的 Skill；隔离版本不能执行。
5. **签发权限**：Policy Broker 校验 Agent、Skill、工具、路径、参数摘要、风险、时效和审批，签发短时 `SkillExecutionGrant`。
6. **实施修复**：Implementer 在隔离工作区生成最小补丁和局部测试证据，不接触隐藏测试。
7. **风险判断**：L0/L1 可按策略继续；L2 进入 Human 审批；L3 默认拒绝或要求更高级人工处置。
8. **独立验证**：Verifier 在清洁快照重放补丁，运行目标、回归、隐藏测试和静态/安全检查。
9. **结果决策**：仅 `PASSED` 可完成；`FAILED/UNSAFE/UNCERTAIN` 进入回滚、补证或终止分支。
10. **沉淀证据**：保存角色事件、Skill/模型版本、Grant、ToolCall、产物哈希、测试和 verdict，生成脱敏报告。
11. **受控演进**：失败进入 `Badcase/ExperienceRecord`；任何 Skill 改进必须形成新版本、重新评测并由 Human 发布，禁止运行时自我修改。

## 8. 异常、审批、回滚和审计

### 8.1 异常处理

| 异常 | 系统行为 | 禁止行为 |
| --- | --- | --- |
| Issue、仓库或验收标准缺失 | 标记 `BLOCKED`，请求补充输入 | Agent 猜测需求后直接改代码 |
| 失败无法复现或证据不足 | Investigator 返回 `INSUFFICIENT_EVIDENCE` | 把低置信度根因当成事实 |
| Skill 未发布、哈希变化或许可证不明 | 保持 `QUARANTINED`，拒绝路由 | 自动安装最新版或绕过来源检查 |
| 工具超时/平台暂时失败 | 在预算内重试一次并保留 Trace；仍失败则从 checkpoint 恢复或阻塞 | 丢弃失败记录、伪装成功 |
| 路径、工具或参数越权 | Policy Broker 拒绝，记录 Policy Finding | Agent 自行扩大权限 |
| L2 审批拒绝或超时 | 撤销请求并进入 `LEARNING/CANCELLED` | 沿用过期审批或模糊批准 |
| 目标/回归/隐藏测试失败 | Verifier 判 `FAILED`，恢复清洁快照；预算允许才重试 | Implementer 修改验证结果 |
| 发现安全风险 | 判 `UNSAFE`，阻断发布并生成 RiskReport | 降低阈值以换取通过 |
| 结论不确定 | 判 `UNCERTAIN`，补证或人工确认 | 把不确定当成功 |
| 外部写操作失败 | 不改变本地已验证结论；记录失败并允许显式重试 | 重复创建 PR、评论或工单 |

### 8.2 风险与审批

| 等级 | 示例 | 默认策略 |
| --- | --- | --- |
| L0 | 读取代码、日志、测试结果 | 自动允许；只读、禁网 |
| L1 | 隔离工作区改代码、运行白名单测试 | 自动允许；路径、命令和资源受限 |
| L2 | 新增依赖、联网、创建 PR/评论、调用外部写工具 | 必须由指定 Human 对精确请求审批 |
| L3 | 生产发布、密钥/高权限、不可逆操作 | 初赛默认拒绝，不做自动执行 |

L2 审批必须绑定 `approvalId`、版本、任务/Grant ID、Agent、Skill、route、参数摘要、回滚计划哈希、过期时间和 Human Matrix 身份。任一字段变化即使曾经批准也必须重新申请。审批只允许一次明确的 `APPROVED` 或 `REJECTED`，不能把聊天中的“可以”当作授权。

### 8.3 回滚

- 代码回滚：丢弃隔离工作区，在不可变基础快照重新应用或重建。
- Skill 回滚：发布标签指回上一已批准的不可变 SkillVersion，不覆盖历史版本。
- 授权回滚：Grant 到期、拒绝、参数变化或任务终止后立即失效。
- 状态回滚：只通过合法状态迁移恢复到 `IMPLEMENTING`，保留原失败和回滚 Evidence。
- 外部写操作：必须在执行前提供可验证回滚计划；无法回滚的操作按 L3 处理。

### 8.4 审计

每次运行记录：`taskId/stepId`、AgentTeams 资源 ID、Matrix event ID、发送者、模型/provider、Skill 名称/commit/hash、Grant、工具/route、参数摘要、开始结束时间、退出码、产物 SHA-256、测试结果、审批事件、Verifier verdict 和失败原因。

审计不记录 API Key、密码、access token、完整认证响应或不必要的个人信息。报告以 EvidenceRef 引用原始产物；修改后的产物必须生成新哈希，不能覆盖旧证据。

## 9. 开放/开源计划与第三方依赖

### 9.1 开源计划

- 许可证：团队原创代码和文档采用 Apache-2.0。
- 公开范围：SkillOps 控制面、Schema、Policy Broker、原创 Skill、样例 Case、测试、部署脚本、架构和复现文档。
- 不公开：API Key、个人配置、Human 密码、未脱敏日志以及不适合公开的恶意样本。
- 初赛：公开可读仓库、固定 release/tag、README 一键复现路径、架构图、示例 Evidence。
- 复赛：补充 AgentLoom-Bench、多 Case 指标、第二场景适配和贡献指南。

### 9.2 第三方披露

| 项目 | 关系 | 许可证/条款 | 使用边界 |
| --- | --- | --- | --- |
| `agentscope-ai/AgentTeams` | 比赛必选运行时、直接依赖 | Apache-2.0；锁定 v1.1.2 / commit `a994578...` | 使用 Manager、Worker、Team、Human、Matrix、MinIO、Higress；不修改上游镜像，不用自研编排器替代 |
| `addyosmani/agent-skills` | 上游 Skill 内容源 | MIT；锁定 commit `7829ffd...` 和五个内容哈希 | 当前只保存来源元数据和 Manifest，未 vendoring；不得宣称上游工作流为原创 |
| DeepSec、VulnClaw、mcp-scan、Promptfoo、SWE-bench、ToolHive、OpenLIT 等 | 设计/方法参考 | 各自许可证或数据条款 | 只披露借鉴点；未复制的项目不写成运行时依赖 |
| Python 依赖 | 直接依赖 | 以各包许可证为准 | FastAPI、Pydantic、SQLAlchemy、MCP、OpenTelemetry、Typer、Textual、Rich、httpx 等由 `pyproject.toml` 和 `uv.lock` 锁定 |
| Qwen/DeepSeek/StepFun API | 可替换模型服务 | 商业服务条款 | 只通过配置注入；记录实际模型、Token 和费用；不上传密钥和不必要数据 |

仓库已有 `LICENSE`、`THIRD_PARTY.md`、`provenance/sources.yaml`、`pyproject.toml` 和 `uv.lock` 作为披露与复现依据。

## 10. 当前进度与诚实边界

### 10.1 已完成并有本地证据

- AgentTeams v1.1.2 固定版本部署；Manager、Team、3 个业务 Worker 和 Human 资源可运行。
- AgentTeams 严格角色消息 E2E；角色事件按真实 Matrix 身份归属。
- Qwen 无人值守真实修复 E2E：从空任务前缀开始，由三个业务 Agent 分别生成角色产物。
- StepFun 真实回滚 E2E：四个角色事件、回滚计划哈希和独立主机验证均通过；见 [StepFun 回滚证据包](stepfun-live-rollback-evidence.md)。
- 独立本地隐藏测试验证通过；补丁、输入和提交均有 SHA-256 绑定。
- Python 控制面基础：契约、任务状态、检测、Policy Broker MCP、审批账本、存储、API、CLI。
- TUI：任务时间线、证据、失败/回滚/重试 Demo、审批队列和决策操作。
- L2 Human 审批的 Prepare/Collect 和严格事件校验脚本已实现。
- 真人 L2 审批 E2E：Manager 发起精确绑定的 `github-pr-v1` 请求，`agentloom-developer` 以独立 Matrix 身份批准，采集结果为 `APPROVED`；见 [L2 审批与上游贡献证据](l2-approval-and-upstream-contribution-evidence.md)。
- 发现并修复 AgentTeams v1.1.2 更新 Team 时未持久化 `humanMembers` 的上游缺陷，回归测试已通过，修复已提交 [AgentTeams PR #1141](https://github.com/agentscope-ai/AgentTeams/pull/1141)，当前等待维护者审核。
- 2026-08-05 本次复核：全量 pytest、Ruff、strict mypy 和 pip-audit 均通过；StepFun 回滚 E2E 通过。
- Apache-2.0、第三方披露和上游 provenance 基础已具备。

### 10.2 提交前必须补齐

1. 制作最终演示录屏并上传，获得可公开访问的 Demo 链接。
2. 按本纲要完成官方模板 PPT，导出 PDF，并检查字体、架构图和所有截图可读。
3. 从仓库与附件中清除 Key、个人路径、密码、临时文件和未脱敏 Trace。
4. 确认 AgentTeams PR #1141 的公开状态表述准确，只写“已提交/待审核”，除非上游实际合并。
5. PPT 与附件完成后，创建提交用 tag/release，并再次检查默认分支、附件和演示材料的一致性。
6. 确认 GitHub 仓库对评委可访问，并制作最终 ZIP。

### 10.3 不应写成已完成

- AgentTeams 上游 PR #1141 已真实创建但尚未合并；AgentLoom 尚未把自动修复结果写入真实业务仓库的 Issue/PR。
- 五个 `addyosmani/agent-skills` 当前为 `QUARANTINED`，尚未完成 Eval 和正式 `PUBLISHED`。
- 团队原创 `skill-supply-chain-audit` 尚未以独立可执行 Skill 完成全量 Eval。
- 比赛录屏尚未完成。
- 第二业务场景、真实云 Skill、RAG、模型训练和生产级多租户均不是初赛已交付能力。

## 11. 最终提交检查表

- [ ] 作品名称与 PPT、PDF、仓库 README 完全一致。
- [x] 赛题选择“赛题三：软件研发全流程协同”。
- [x] 作品简介不超过 500 字且未夸大当前进展。
- [ ] PPT 使用官方 19 页模板，不删除必需章节。
- [x] 三个 Agent 的角色、输入、输出、边界和 Trace 均完整。
- [x] 核心 Skill 清单包含来源、契约、依赖、失败、安全、复用和状态。
- [x] AgentTeams 在架构、运行证据和协作流程中均为实际必选运行时。
- [x] 正常、失败、审批、拒绝/超时、回滚和审计分支均有说明。
- [x] 开源范围、许可证、第三方来源、模型/API 和数据边界已披露。
- [ ] 所有“已完成”能力都有代码、测试、Trace、哈希或截图支撑。
- [ ] GitHub 仓库可访问，默认分支或提交链接固定，README 可复现。
- [ ] Demo 链接若填写，必须公网可访问；无链接则留空，不填本地地址。
- [ ] ZIP 可正常解压，PPT/PDF 可打开，附件不含任何密钥或密码。
