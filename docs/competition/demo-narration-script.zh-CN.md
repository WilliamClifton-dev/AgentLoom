# AgentLoom 初赛演示口播稿

## 使用方式

- 目标时长：约 5 分钟。若平台限制更短，优先保留第 1、2、3、4、7 段。
- 正式录制前先完成预检，不把登录、启动服务和等待过程录进去。
- 画面只展示公开仓库、脱敏终端输出、AgentTeams Team Room 和脱敏审批证据。
- 口播不必逐字背诵，但加粗的事实不能改错。

## 录制前预检（不录）

1. 启动 Docker Desktop，等待 AgentTeams 服务就绪。
2. 使用 `agentloom-developer` 提前登录 Element，不录用户名和密码输入过程。
3. 关闭微信、邮件、密码管理器和系统通知，隐藏书签栏及个人头像。
4. 终端进入 AgentLoom 仓库根目录，窗口建议至少 140 列、45 行。
5. 执行以下本地预检，不调用模型：

```powershell
docker ps --format "table {{.Names}}\t{{.Status}}"
.\.venv\Scripts\python -m pytest
```

确认 AgentTeams `v1.1.2` Controller、Manager 和三个 Worker 健康，并确认
`375 passed / 3 skipped`，Task 24 两模式矩阵为 `6 PASSED / 0 NOT_RUN`。正式录制只展示已经脱敏的 Task 17/24/26 Evidence 摘要，
不打开 Matrix 正文、Worker 原始日志、凭据或 Signed Grant。

## 1. 开场与真实场景（00:00-00:35）

**画面**：公开 GitHub 仓库首页，停留在 Logo、项目定位和 Competition Scope。

**口播**：

> 大家好，我是零号工位团队的独立开发者。我的项目是 AgentLoom，一套构建在
> AgentTeams 之上的多 Agent 软件缺陷治理系统。它面向需要引入第三方 Agent
> Skill 的研发团队，解决 Skill 来源和版本不清、执行权限失控、补丁缺少独立
> 验证，以及审批和回滚无法追溯的问题。

## 2. 为什么需要 AgentTeams（00:35-01:15）

**画面**：README 的 Architecture 图，鼠标依次指向 Manager、Investigator、
Implementer、Verifier、Policy Broker 和 Evidence。

**口播**：

> 一个补丁的代码可能很少，但真实修复同时包含根因复现、最小权限实施、隐藏测试
> 隔离、人工审批和失败回滚。AgentTeams 在这里承担主协同运行时：Human 把任务
> 交给 Manager，Manager 拆解并委派给三个职责不同的业务 Agent。
> Investigator 负责根因和证据，Implementer 只能在授权范围内生成最小补丁，
> Verifier 在独立边界重新运行测试并给出结论。Manager 是 AgentTeams 的编排资源，
> 参赛 Agent Identity 是这三个业务 Agent，不是为了凑数量额外增加角色。

## 3. AgentTeams 原生协作证据（01:15-02:05）

**画面**：先展示 Investigator 所有的 Leader Room 中 Manager 标记，再切到 Team
Room 中 Investigator 对 Verifier 的明确委派和稍后的 Verifier PASS 标记。只展示
预先确认可公开的事件元数据或脱敏摘要，不展示 Matrix 正文导出。

**口播**：

> 这里展示的是 AgentTeams v1.1.2 的真实跨房间委派。Administrator 先提交未提及
> 任何 Worker 的任务信封；Manager 在 Investigator 所有的 Leader Room 建立精确
> 绑定标记；Investigator 再在 Team Room 明确提及并委派 Verifier；Verifier 之后
> 给出 PASS。事件 ID、房间、发送者和时间顺序被 Evidence 绑定，不能用一个模型
> 事后补写一段总结替代真实角色链路。

## 4. 脱敏治理证据与 TUI（02:05-03:15）

**画面**：切换到放大的 PowerShell，展示 Task 17 脱敏 Evidence 摘要的状态、
Provider、模型、Docker 镜像和哈希；随后在 TUI 中展示任务状态与 Evidence 引用。

**口播**：

> 现在展示的是已固化、已脱敏的 Task 17 Evidence，不会重新请求模型，也不会
> 消耗额度。当前 Provider 是 `minimax-cn`，模型是 `MiniMax-M2.5`。Verifier 的
> 请求经过 Higress 身份校验、Policy Broker 的短时 Grant 和不可变 Docker 沙箱，
> 数据库最终只记录一个 `SUCCEEDED` ToolCall；错误消费者、参数篡改和 Grant 重放
> 都被拒绝。镜像、工作区和 Evidence 都以 SHA-256 固定。
>
> 这个 TUI 是 AgentLoom 自主实现的治理控制面，AgentTeams 负责角色协同；TUI
> 负责把协同产生的健康状态、事件顺序、失败补丁、批准快照和最终 verdict 投影成
> 可检查的一等状态。两者职责不同。

## 5. 原创治理能力（03:15-03:55）

**画面**：回到 README 的 Implemented 列表，或展示 PPT 中 AgentLoom 原创能力页。

**口播**：

> AgentLoom 的原创核心不是再造一个代码生成模型，而是给 AgentTeams 增加可验证的
> SkillOps 治理层。第三方 Skill 进入 Registry 后先绑定来源、许可证、commit 和
> 内容哈希，再经过三层检测。真正执行前，Policy Broker 会把 Agent、Skill、工具、
> 路径、参数、风险和有效期绑定到一次性 `SkillExecutionGrant`。验证失败、越权或
> 证据不足时默认失败关闭，并保留不可覆盖的 Evidence。

## 6. 真人 L2 审批与工程可信度（03:55-04:35）

**画面**：Element 中依次展示 Manager 的 `github-pr-v1` 审批请求、
`agentloom-developer` 的明确批准和 `APPROVED` 结果；随后快速切到 GitHub Actions
全绿页面和 AgentTeams 上游 PR #1141 的 Open 状态。

**口播**：

> 对联网、新增依赖和创建 PR 等 L2 外部操作，Agent 不能用聊天中的一句“可以”
> 自行放行。审批必须绑定 approval ID、任务、route、参数摘要、回滚计划、有效期和
> Human 身份，字段变化就必须重新审批。这里展示的是独立 Human 身份完成的真实
> 批准证据。
>
> 工程侧，冻结提交通过 375 项 pytest，默认门禁跳过 3 项需显式启用的 Docker
> live tests；Ruff、strict mypy、依赖审计、构建和安装 smoke 也通过，最新公开
> GitHub Actions CI 全绿。
> 我还定位并修复了 AgentTeams 更新 Team 时没有持久化 `humanMembers` 的缺陷，
> 已提交上游 PR #1141，目前仍在等待维护者审核。

## 7. 收束与边界（04:35-05:00）

**画面**：回到架构图或 TUI 的 `PASS` 总览。

**口播**：

> 最终，AgentLoom 形成从 Issue、任务拆解、根因调查、受控修复、独立验证，到
> 人工审批、失败回滚和 Evidence 沉淀的完整闭环。它把“模型能不能写补丁”升级为
> “团队能不能证明谁在什么权限下，用哪一版 Skill 做了什么，以及结果是否可信”。
> 当前版本尚未默认向真实业务仓库写入 PR。五个上游 Skill 中，
> `code-review-and-quality` 已有匹配 Eval 并为 `PUBLISHED`，其余四个仍为
> `QUARANTINED`；团队原创 `patch-scope-validator` v1.0.1 也已发布，三次治理
> 调用可严格重开，所以目录总状态是 `2 PUBLISHED / 4 QUARANTINED`。这些边界
> 都已在公开仓库中明确说明。谢谢。

## 录制结束

1. TUI 按 `Ctrl+C`，出现确认提示后按 `Ctrl+Q` 退出。
2. 从头播放视频，暂停检查每个终端镜头是否出现个人绝对路径或凭据。
3. 确认画面能看清 Manager、Investigator、Verifier 的委派标记、唯一成功 ToolCall、`APPROVED` 和 PR 的 `Open` 状态。
4. 上传后用无痕窗口打开公开视频链接，确认无需登录即可播放。

## 不能说错

- Task 17 Evidence 是既有真实运行的脱敏摘要，不是现场重新调用模型。
- TUI 属于 AgentLoom；AgentTeams 提供 Manager、Worker、Team、Human 和 Matrix
  协同运行时。
- 上游 PR #1141 是已提交、等待审核，不能说已经合并。
- 当前 Task 17 只使用 MiniMax；Qwen、DeepSeek 和 StepFun 均未调用。StepFun 只可作为历史回滚/L2 证据说明。
- 当前没有默认向真实业务仓库自动提交 PR。
- 五个上游 Skill 中仅 `code-review-and-quality` 已完成 Eval 并为 `PUBLISHED`；其余四个仍是 `QUARANTINED`。团队原创 `patch-scope-validator` v1.0.1 另行为 `PUBLISHED`，不能把“上游样本”与“目录总数”混写。
- 项目是初赛 MVP，不能宣称已经生产就绪。
