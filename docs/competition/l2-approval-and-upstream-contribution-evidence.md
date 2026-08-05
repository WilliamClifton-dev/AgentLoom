# L2 真人审批与 AgentTeams 上游贡献证据

## 结论

AgentLoom 已完成一次真实 L2 Human 审批闭环：Manager 通过 AgentTeams Team
Room 发起绑定到精确参数和回滚计划的审批请求，`agentloom-developer` 使用独立
Matrix 身份作出批准，严格采集器验证发送者、事件顺序和绑定字段后生成
`APPROVED` 证据。

联调期间发现的 AgentTeams v1.1.2 `humanMembers` 更新缺陷也已形成最小修复、
回归测试和公开上游 PR。PR 已提交，当前等待维护者审核，不能写成已合并。

## L2 审批证据

| 字段 | 脱敏结果 |
| --- | --- |
| 运行 | `competition-l2-stepfun-20260805-09` |
| Schema | `agentloom.l2-approval-evidence/v1alpha1` |
| 风险等级 | `L2` |
| 受控路由 | `github-pr-v1` |
| 最终状态 | `APPROVED` |
| 请求发送者 | `@manager:matrix-local.hiclaw.io:18080` |
| 决策发送者 | `@agentloom-developer:matrix-local.hiclaw.io:18080` |
| 请求来源 | `deterministic-host` |

审批证据绑定 `approvalId`、版本、任务 ID、候选 Grant、route、参数摘要、回滚
计划哈希、请求事件、决策事件和服务端时间戳。采集器要求决策发送者与指定
Human Matrix 身份完全一致；Manager 代发、过期事件、字段变更或模糊聊天文本
均不能产生批准结论。

原始 JSON 只保存在本地被 Git 忽略的 `artifacts/` 下。本摘要不包含 Human
密码、访问令牌、API Key、Room 完整导出或个人绝对路径。

## AgentTeams 上游缺陷与修复

| 项目 | 结果 |
| --- | --- |
| 上游项目 | `agentscope-ai/AgentTeams` |
| 影响版本 | `v1.1.2` |
| 缺陷 | Update Team 接口读取了 `humanMembers`，但未写回 `Team.Spec` |
| 用户影响 | CLI 显示更新成功，实际 Team Human 成员保持旧值，导致审批身份联调失败 |
| 修复 | 当请求显式提供 `humanMembers` 时，将其持久化到 `team.Spec.HumanMembers` |
| 回归测试 | 证明成员从旧值更新为新值，并覆盖字段未提供时的兼容行为 |
| 上游 PR | [agentscope-ai/AgentTeams#1141](https://github.com/agentscope-ai/AgentTeams/pull/1141) |
| 当前状态 | `OPEN`，等待维护者审核；未合并，当前无可用状态检查结果 |

该贡献证明 AgentLoom 不是把输入直接转给模型再搬运答案：真实运行中完成了部署、
身份配置、故障复现、日志与资源核对、最小补丁、回归验证和上游协作。它属于
AgentTeams 运行时兼容性修复，不冒充 AgentLoom 团队原创编排框架。

## PPT 与录屏取证建议

PPT 可展示两张脱敏截图：一张包含 Manager 的 L2 请求与绑定摘要，一张包含
`agentloom-developer` 的明确批准和最终 `APPROVED` 结果。上游贡献页只展示 PR
标题、编号和 Open 状态，不展示本地目录或未公开日志。

录屏应按“发起请求 -> Human 独立身份决策 -> Collect 校验 -> Evidence 摘要”
顺序展示，并补充 AgentTeams PR #1141 页面。不要展示环境变量、密码、Token、
完整 Human JSON 或 Matrix 原始导出。
