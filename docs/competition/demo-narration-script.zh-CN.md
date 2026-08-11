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
5. 执行以下免费预检：

```powershell
.\scripts\competition-rollback-demo.ps1 `
  -Mode replay `
  -NoTui `
  -PublicOutput
```

确认出现 AgentTeams `v1.1.2`、健康状态 `PASS`、3 个 Worker、Human、
`roleEventCount: 4`、`step-3.7-flash` 和 `<redacted>` 后再开始录制。

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

**画面**：Element 的 `agentloom-repair` Team Room。按时间顺序展示四条消息，
先让发送者和事件名称可见，再缓慢滚动到哈希或结果字段。

**口播**：

> 这里是 AgentTeams 实际使用的 Matrix Team Room，不是我在外围伪造的聊天记录。
> 这次回滚运行中，Verifier 首先报告 `VERIFICATION_FAILED`；Manager 根据失败证据
> 发出 `ROLLBACK_REQUESTED`；Implementer 执行 `ROLLBACK_EXECUTED`；最后由
> Verifier 独立确认 `ROLLBACK_VERIFIED`。四条事件由不同运行时身份发送，并按
> task、快照和产物哈希绑定，因此不能用一个模型事后补写一段总结来替代。

## 4. 脱敏证据回放与 TUI（02:05-03:15）

**画面**：切换到放大的 PowerShell，执行：

```powershell
.\scripts\competition-rollback-demo.ps1 -Mode replay -PublicOutput
```

终端输出时停留在健康检查和 JSON 摘要；TUI 打开后展示状态、角色事件、模型、
哈希和 `<redacted>` 路径。

**口播**：

> 现在运行的是免费、安全的 Evidence 回放，不会重新请求模型，也不会消耗额度。
> 系统首先检查 Docker、AgentTeams `v1.1.2`、Manager、Team、三个 Worker、Human
> 和 Matrix 房间是否健康。随后 AgentLoom 对历史运行证据重新进行绑定校验。
> 可以看到状态为 `PASS`，模型是 StepFun 的 `step-3.7-flash`，角色事件数为 4，
> 本机产物路径已显示为 `<redacted>`。
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
> 工程侧，项目通过 175 项 pytest、Ruff、strict mypy 和依赖审计。我还定位并修复
> 了 AgentTeams 更新 Team 时没有持久化 `humanMembers` 的缺陷，已提交上游
> PR #1141，目前仍在等待维护者审核。

## 7. 收束与边界（04:35-05:00）

**画面**：回到架构图或 TUI 的 `PASS` 总览。

**口播**：

> 最终，AgentLoom 形成从 Issue、任务拆解、根因调查、受控修复、独立验证，到
> 人工审批、失败回滚和 Evidence 沉淀的完整闭环。它把“模型能不能写补丁”升级为
> “团队能不能证明谁在什么权限下，用哪一版 Skill 做了什么，以及结果是否可信”。
> 当前版本尚未默认向真实业务仓库写入 PR，五个上游 Skill 也仍处于隔离评测状态；
> 这些边界都已在公开仓库中明确说明。谢谢。

## 录制结束

1. TUI 按 `Ctrl+C`，出现确认提示后按 `Ctrl+Q` 退出。
2. 从头播放视频，暂停检查每个终端镜头是否出现个人绝对路径或凭据。
3. 确认画面能看清 `PASS`、`APPROVED`、四个角色事件和 PR 的 `Open` 状态。
4. 上传后用无痕窗口打开公开视频链接，确认无需登录即可播放。

## 不能说错

- 免费 replay 是重新校验既有真实 Evidence，不是现场重新调用模型。
- TUI 属于 AgentLoom；AgentTeams 提供 Manager、Worker、Team、Human 和 Matrix
  协同运行时。
- 上游 PR #1141 是已提交、等待审核，不能说已经合并。
- 当前没有默认向真实业务仓库自动提交 PR。
- 五个上游 Skill 仍是 `QUARANTINED`，不能说已经发布。
- 项目是初赛 MVP，不能宣称已经生产就绪。
