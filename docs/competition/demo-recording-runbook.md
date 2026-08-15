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

先执行不调用模型的只读检查：

```powershell
docker ps --format "table {{.Names}}\t{{.Status}}"
.\.venv\Scripts\python -m pytest
```

预期结果：

- AgentTeams `v1.1.2` 健康状态为 `PASS`。
- Manager、Team、3 个 Worker 和 Human 均可用。
- 冻结后的 public main 门禁为 `375 passed / 3 skipped`；Task 25 clean-clone
  Lite 证据为
  `339 passed / 0 failed / 3 skipped`，两者不得混写。
- Task 17 脱敏摘要中的 provider/model 为 `minimax-cn` / `MiniMax-M2.5`。
- Task 17 数据库结果为且仅为一个 `SUCCEEDED` ToolCall。
- 不打开 Matrix 正文、Worker 原始日志、凭据、Signed Grant 或本机绝对路径。

## 建议镜头顺序

### 1. 项目与运行时

展示公开 GitHub 仓库首页和 README 的 Competition Scope，说明：

- 参赛方向是软件研发全流程协同。
- AgentTeams 是实际协同运行时，不是架构图中的装饰依赖。
- AgentLoom 原创部分是 Skill Registry、Policy Broker、三层检测、Evidence、
  审批和回滚治理层。

### 2. AgentTeams 多角色交互

在 Element 中按时间顺序展示 Task 17 的真实委派标记：

1. Administrator：未提及 Worker 的任务信封。
2. Manager：Investigator 所有 Leader Room 中的精确绑定标记。
3. Investigator：Team Room 中提及 Verifier 的明确委派。
4. Verifier：同一 Team Room 中稍后出现的 PASS 标记。

长消息不必塞进同一个画面。使用两个连续镜头：先展示发送者和事件开头，再向下
滚动展示绑定哈希或完成标记；不要为了单张截图牺牲可读性。

### 3. 脱敏治理证据

展示预先核验的 Task 17 脱敏摘要和 TUI 状态：

- Manager 健康状态。
- Manager、Investigator、Verifier 的委派阶段与事件元数据。
- MiniMax Provider/模型标识。
- Higress、Policy Broker、Docker 沙箱和唯一成功 ToolCall。
- 镜像、工作区和 Evidence 的 SHA-256。

这是既有真实运行的脱敏证据展示，不请求模型生成新答案。

### 4. 真人 L2 审批

在 Element 中分两个镜头展示：

1. Manager 发出的 `github-pr-v1` L2 请求，包含参数摘要和回滚计划绑定。
2. `agentloom-developer` 独立身份发出的明确批准，以及最终 `APPROVED` 结果。

不需要重新创建审批。该部分使用 2026-08-05 已验证的历史运行
`competition-l2-stepfun-20260805-09`，并以
[脱敏摘要](l2-approval-and-upstream-contribution-evidence.md)说明采集器验证了
发送者、时间顺序、route、参数摘要和回滚计划哈希。

### 5. 工程验证与上游贡献

展示 GitHub Actions 和
[AgentTeams PR #1141](https://github.com/agentscope-ai/AgentTeams/pull/1141)：

- AgentLoom 冻结提交门禁为 375 项 pytest 通过、3 项显式启用的 Docker live
  tests 默认跳过；Ruff、strict mypy、依赖审计、构建、安装 smoke 和最新公开
  GitHub Actions CI 均通过。
- PR 修复 AgentTeams 更新 Team 时未持久化 `humanMembers` 的缺陷。
- PR 状态只说“已提交、等待维护者审核”，不要说已经合并。

### 6. 收束

回到主流程总结：Issue -> 调查 -> 受控修复 -> 独立验证 -> 审批/回滚 ->
Evidence。明确当前边界：尚未把 AgentLoom 自动修复结果写入真实业务仓库；
`code-review-and-quality` 已有匹配 Eval 并为 `PUBLISHED`，其余四个上游 Skill
仍为 `QUARANTINED`；团队原创 `patch-scope-validator` v1.0.1 也为 `PUBLISHED`，
目录总状态为 `2 PUBLISHED / 4 QUARANTINED`。提交包已生成，最终录屏、上传和
页面提交仍待 Human 完成。

## 禁止出现在画面中的信息

- API Key、access token、Matrix 密码、Human 初始密码。
- 环境变量值、完整认证响应、完整 Human JSON。
- 个人绝对路径、未脱敏 Trace、完整 Matrix 导出。
- “上游 PR 已合并”“生产环境就绪”“五个 Skill 已发布”等不实表述。

## 录制后检查

- 从头播放一次，确认文字可读、没有通知弹窗和凭据闪现。
- 暂停检查所有终端画面，不应出现盘符加个人目录。
- 核对委派链路、唯一成功 ToolCall、`APPROVED` 和 PR `Open` 状态均可见。
- 视频上传后使用无痕窗口验证公开链接，无需登录即可播放。
- 提交页面不要填写 `localhost`、本机文件路径或仅自己可访问的云盘链接。
