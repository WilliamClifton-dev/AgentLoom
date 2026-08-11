# AgentLoom 初赛录屏执行清单

逐镜头口播内容见 [AgentLoom 初赛演示口播稿](demo-narration-script.zh-CN.md)。

## 目标

用现有可验证证据说明 AgentLoom 不是“把问题丢给模型再搬运答案”，而是在
AgentTeams v1.1.2 上完成多角色运行、缺陷发现、证据核对、人工审批、失败回滚
和独立验证。录屏不需要再次调用付费模型。

本清单不声明赛事强制时长；最终视频必须服从提交平台的时长和文件大小限制。

## 录制前

1. 启动 Docker Desktop，确认 AgentTeams 容器处于运行状态。
2. 提前登录 Element 的 `agentloom-developer`，再开始录屏；不要录登录过程。
3. 关闭环境变量、密码管理器、`.env`、Docker Inspect 和完整 Human JSON 页面。
4. 浏览器只保留 `agentloom-repair` Team Room 和上游 PR #1141 页面。
5. 终端进入 AgentLoom 仓库根目录，使用公开输出模式。

先执行只读检查：

```powershell
.\scripts\competition-rollback-demo.ps1 `
  -Mode replay `
  -NoTui `
  -PublicOutput
```

预期结果：

- AgentTeams `v1.1.2` 健康状态为 `PASS`。
- Manager、Team、3 个 Worker 和 Human 均可用。
- 回滚摘要状态为 `PASS`，`roleEventCount` 为 `4`。
- provider/model 为 `stepfun` / `step-3.7-flash`。
- `artifactsDirectory` 显示 `<redacted>`，不出现本机绝对路径。

## 建议镜头顺序

### 1. 项目与运行时

展示公开 GitHub 仓库首页和 README 的 Competition Scope，说明：

- 参赛方向是软件研发全流程协同。
- AgentTeams 是实际协同运行时，不是架构图中的装饰依赖。
- AgentLoom 原创部分是 Skill Registry、Policy Broker、三层检测、Evidence、
  审批和回滚治理层。

### 2. AgentTeams 多角色交互

在 Element 的 `agentloom-repair` Team Room 展示四个按时间递增的回滚事件：

1. Verifier：`VERIFICATION_FAILED`
2. Manager：`ROLLBACK_REQUESTED`
3. Implementer：`ROLLBACK_EXECUTED`
4. Verifier：`ROLLBACK_VERIFIED`

长消息不必塞进同一个画面。使用两个连续镜头：先展示发送者和事件开头，再向下
滚动展示绑定哈希或完成标记；不要为了单张截图牺牲可读性。

### 3. 公开安全回放

执行：

```powershell
.\scripts\competition-rollback-demo.ps1 -Mode replay -PublicOutput
```

先展示终端中的健康检查和 `PASS` 摘要，再进入 TUI 展示：

- Manager 健康状态。
- 四个角色事件及顺序。
- StepFun 模型标识。
- 失败补丁、失败快照、批准快照的 SHA-256。
- `Path: <redacted>`。

这是免费回放，只重新校验证据，不请求模型生成新答案。

### 4. 真人 L2 审批

在 Element 中分两个镜头展示：

1. Manager 发出的 `github-pr-v1` L2 请求，包含参数摘要和回滚计划绑定。
2. `agentloom-developer` 独立身份发出的明确批准，以及最终 `APPROVED` 结果。

不需要重新创建审批。使用已验证运行
`competition-l2-stepfun-20260805-09`，并以
[脱敏摘要](l2-approval-and-upstream-contribution-evidence.md)说明采集器验证了
发送者、时间顺序、route、参数摘要和回滚计划哈希。

### 5. 工程验证与上游贡献

展示 GitHub Actions 和
[AgentTeams PR #1141](https://github.com/agentscope-ai/AgentTeams/pull/1141)：

- AgentLoom 本地质量门禁为 175 项 pytest、Ruff、strict mypy。
- PR 修复 AgentTeams 更新 Team 时未持久化 `humanMembers` 的缺陷。
- PR 状态只说“已提交、等待维护者审核”，不要说已经合并。

### 6. 收束

回到主流程总结：Issue -> 调查 -> 受控修复 -> 独立验证 -> 审批/回滚 ->
Evidence。明确当前边界：尚未把 AgentLoom 自动修复结果写入真实业务仓库，五个
上游 Skill 仍处于 `QUARANTINED`，最终录屏与提交包仍在制作。

## 禁止出现在画面中的信息

- API Key、access token、Matrix 密码、Human 初始密码。
- 环境变量值、完整认证响应、完整 Human JSON。
- 个人绝对路径、未脱敏 Trace、完整 Matrix 导出。
- “上游 PR 已合并”“生产环境就绪”“五个 Skill 已发布”等不实表述。

## 录制后检查

- 从头播放一次，确认文字可读、没有通知弹窗和凭据闪现。
- 暂停检查所有终端画面，不应出现盘符加个人目录。
- 核对 `PASS`、`APPROVED`、四个角色发送者和 PR `Open` 状态均可见。
- 视频上传后使用无痕窗口验证公开链接，无需登录即可播放。
- 提交页面不要填写 `localhost`、本机文件路径或仅自己可访问的云盘链接。
