# AgentLoom 演示卡

这是一张现场照着做、照着说的简化演示卡。练习模式不调用付费模型，也不要求
启动 Docker 或登录网页版。

## 练习前

1. 打开 `D:\Projects\Agent-Infra` 文件夹。
2. 双击 `START_DEMO.cmd`。
3. 等待 TUI 自动运行，看到左侧状态出现 `COMPLETED`，右侧 Verifier 为
   `PASSED`。
4. 按 `Ctrl+C` 退出。

正式展示已验证的 AgentTeams 证据时，双击 `START_COMPETITION_REPLAY.cmd`。这个
入口需要 Docker Desktop 正在运行，并且本机已经有完成的回滚 Evidence；它不会
重新调用模型或消耗额度。

## 两分钟演示顺序

### 第一屏：项目解决什么问题

指着标题和左侧案例，说：

> AgentLoom 是基于 AgentTeams 的软件缺陷治理系统。输入 Issue 后，由
> Manager 把任务拆成调查、受限修复和独立验证。Investigator 先复现根因，
> 再把结构化结果交给 Implementer 和 Verifier，最后由 Manager 汇总带证据的结论。

### 第二屏：Manager 编排资源与三个 Agent

指着右侧 `AGENT STATUS`，从上到下说：

> 这里不是一个模型直接给答案，而是 Manager、Investigator、Implementer、
> Verifier 分层协作。Manager 负责任务拆解，三个业务 Agent 各自生成有明确归属的
> 交接物。Investigator 在 AgentTeams 资源中兼任团队协调，但不是新增的第四个 Agent。

### 为什么不用一个大模型

> 这个案例的算法改动很小，但它同时要求复现原失败、限制修改范围、隐藏测试隔离、
> 独立验收、L2 审批和失败回滚。一个模型可以写补丁，不能天然替代这些互斥身份和证据责任。

### 第三屏：事件与证据

指着 `TASK EVENTS` 和 `ARTIFACTS`，说：

> 每一步都会写入只追加的任务事件。最终保存根因、补丁 SHA-256、测试结果、
> 风险检测和产物路径，因此结果可以复核，而不是只展示聊天答案。

### 第四屏：失败与回滚

点击左侧 `Run failure / retry`，等待再次完成，然后说：

> 这里故意让第一次验证失败。系统先记录回滚，再允许一次受限重试，最后重新
> 验证通过。这体现了多轮运行、日志检查、回执和维护过程。

## 老师可能追问

**这是不是真实 AgentTeams 运行？**

当前双击启动的是无模型、可重复的本地练习案例，用于讲清 AgentLoom 的治理
流程。真实 AgentTeams 证据由 Matrix/Element 中的多角色事件、运行健康记录和
已验证回滚 Evidence 共同证明，正式录屏使用
`scripts\competition-rollback-demo.ps1 -Mode replay -PublicOutput`。

**TUI 是 AgentTeams 自带的吗？**

不是。TUI 是 AgentLoom 自主实现的 Textual/Rich 治理控制面；AgentTeams 负责
Manager、Worker、Team、Human 和 Matrix 协同。

**是否会自动提交 PR？**

当前版本完成调查、受控修复、验证、审批和回滚证据链。真实业务仓库写入仍是
受控的 L2 外部操作，必须经过独立 Human 审批；不能声称已经默认自动提交 PR。

**为什么还要展示 Element 网页？**

TUI 展示 AgentLoom 的结构化治理结果；Element 展示 AgentTeams 原生的多角色
交互和真人审批。两者证明的内容不同，正式参赛演示不能只展示 TUI。

## 不要说错

- 不要把本地练习案例说成真实模型调用。
- 不要说 AgentTeams 上游修复 PR 已经合并，只能说已提交等待审核。
- 不要展示 API Key、Matrix 密码、环境变量或本机个人路径。
- 不要说项目已经生产就绪，也不要说默认会向用户仓库自动提交 PR。
