# StepFun 真实回滚 E2E 证据包

## 结论

| 项目 | 结果 |
| --- | --- |
| 任务 | `AL-LIVE-ROLLBACK-STEPPLAN-20260805-01` |
| 场景 | `pagination-boundary` 合成分页边界缺陷 |
| AgentTeams 运行时 | HiClaw `v1.1.2` |
| 模型 | StepFun `step-3.7-flash`，Step Plan 接口，`reasoning_effort=low` |
| 角色协作 | 4 个角色归属明确、顺序严格递增的 Matrix 事件 |
| 主机独立验证 | 失败复现、批准快照恢复、显式测试、隐藏测试、静态检查均通过 |
| 最终状态 | `PASS` |

本文件是从本机已验证的运行证据提取的脱敏摘要，供初赛 PPT、PDF 和
录屏说明使用。它不包含 API Key、Matrix 密码、访问令牌、个人绝对路径或
完整原始 Trace。

## 完整流程

1. Verifier 检出候选补丁在精确分页边界上不正确，发布
   `VERIFICATION_FAILED`。
2. Manager 确认该角色事件后，发布 `ROLLBACK_REQUESTED`。
3. Implementer 确认恢复批准快照，发布 `ROLLBACK_EXECUTED`。
4. Verifier 确认绑定计划和 Implementer 的角色事件，发布
   `ROLLBACK_VERIFIED`。
5. AgentLoom 主机验证器在独立工作区重放失败候选、恢复批准快照，并运行
   显式测试、隐藏测试和静态检查。

Matrix 角色事件用于证明 AgentTeams 协作、发送者归属和流程顺序；主机验证器
用于证明代码状态及测试结果。两类证据必须同时成立，任一缺失均不生成通过结论。

## 绑定与角色证据

失败候选补丁 SHA-256：
`bdc0974ba9547a09098860d55e51f44facddf2e987a6caf72262b38b8e156dde`

回滚计划绑定 SHA-256：
`7b399d683870dbf89c8ddf8cffd12a56ac3b67fa10eeace89faf00d2d7374fa0`

回滚策略：`RESTORE_APPROVED_SNAPSHOT`，只允许恢复
`lib/pagination.py`。

| 顺序 | 阶段 | 真实角色 | Matrix 事件 ID | 服务端时间戳（ms） |
| --- | --- | --- | --- | --- |
| 1 | `VERIFICATION_FAILED` | `agentloom-verifier` | `$DajYQpLUpyCirUJ3YEAbnCFhdM01Q-AtsTvaO3nRLj0` | `1785917239565` |
| 2 | `ROLLBACK_REQUESTED` | `manager` | `$q0POXJgYp-KO3C-5PoF9dm4ciUPcyrZ6WZIE4bSsLWo` | `1785917275998` |
| 3 | `ROLLBACK_EXECUTED` | `agentloom-implementer` | `$G73OxBDyMhjySXpUDgMUvLJZ0VAWjkLjtWBLvRPrWpw` | `1785917375194` |
| 4 | `ROLLBACK_VERIFIED` | `agentloom-verifier` | `$VJc-jbMRHuFFuSmH7jDFtxNNq4NGQm7Y9chXKzdSsG4` | `1785917785081` |

每个事件均携带相同的回滚计划绑定哈希。采集器还验证事件发送者、事件类型、
独立标记行和时间顺序，不接受管理员代发或提示词中的标记。

## 独立验证结果

| 检查 | 结果 |
| --- | --- |
| 失败候选可复现 | 通过 |
| 回滚已执行 | 通过 |
| 批准快照已恢复 | 通过 |
| 显式测试 | 通过 |
| 隐藏测试 | 通过 |
| 静态检查 | 通过 |

批准快照 SHA-256：
`5f4d772d47730284f20be15a8218704459668a919660a18e77182637c972df00`

失败工作区快照 SHA-256：
`ae50ab8f26881eb58dd785dc814b701a6a7f2111851795e5e5d18f54a44f9281`

提交文件 SHA-256：
`979b48997e3a0787c87adeea54494a94aa86f459e3d7a08ae207a2202ae14dcf`

测试结果 SHA-256：
`57cc603607756d5be485c272a6ef68808292298107a44e22103de7be380f5280`

## 复现方式

在已完成 AgentTeams 部署、且 `STEPFUN_API_KEY` 已在操作系统环境变量中设置的
Windows 主机执行。请使用一个新的任务 ID，运行器拒绝覆盖已有证据：

```powershell
.\scripts\competition-rollback-demo.ps1 `
  -Mode live `
  -TaskId AL-LIVE-ROLLBACK-STEPPLAN-<new-id> `
  -Provider stepfun `
  -Model step-3.7-flash `
  -ConfirmPaidRun
```

运行会消费云模型额度。没有运行额度时，使用免费回放：

```powershell
.\scripts\competition-rollback-demo.ps1 -Mode replay
```

## PPT 与录屏取证

PPT 放一张流程图和一张本表的精简版即可。录屏应展示：AgentTeams 健康状态、
Team Room 中四个独立角色事件、`inspect-rollback` 的 `PASS` 摘要。不要展示
环境变量、Element 密码、Token、完整 Matrix 原始导出或本机绝对路径。
