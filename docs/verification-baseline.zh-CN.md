# 验证基线与历史记录

此页区分当前工作树验证、已合并主线结果和历史集成记录。不同环境的数字不能互相替代。

## 当前验证

- 当前 PR 工作树 Lite：`382 passed / 3 skipped`；Ruff 和 strict mypy 通过。三个跳过项为可选 Docker 测试。
- public `main` 最近记录的 Full 门禁：`380 passed / 0 skipped`，CI 构建锁定的沙箱镜像后运行。本 PR 的 Full 门禁结果待 GitHub Actions 完成后更新。
- Task 24 三案例、两种模式基准：`6 PASSED / 0 NOT_RUN`。这是已归档基准，不是本次改动刚产生的结果。
- 冻结 `v0.1.0` 门禁：`375 passed / 3 skipped`。

当前付费链路记录的 Provider 是 `minimax-cn / MiniMax-M2.5`。Task 17 记录一条完整受治理 ToolCall。Skill 状态、原始证据引用和发布包审计摘要由仓库中的版本化证据文件维护；这些记录不等于新运行结果。

## 历史运行

以下材料仅用于审计和复现，不是当前验证基线。Qwen 与 DeepSeek 因账户无余额保持禁用。每次新的 MiniMax 或 StepFun 运行都必须使用唯一 run ID 并记录准确 Provider/模型；StepFun 记录不得计入只接受 MiniMax 的 Task 24 版本化基准。

- 2026-08-04，Qwen `qwen3.7-plus` 曾完成无人值守修复，通过独立可见测试、主机专属隐藏测试和静态检查。补丁 SHA-256：`7d9d571a833eabaedf97eac73dad50f6290bfa332d3ef504882398ba2e6d0833`。运行摘要位于 `artifacts/agentteams/live-repair-pagination-qwen-unattended-03.json`；独立验证产物位于 `artifacts/live-repair/AL-LIVE-PAGINATION-UNATTENDED-20260804-03/verified/artifacts/`。
- 早期 StepFun 四角色回滚和 DeepSeek 消息基线是 Human L2 审批记录的历史输入。脱敏摘要见[审批与上游贡献证据](competition/l2-approval-and-upstream-contribution-evidence.md)。
- 历史回放入口为 `scripts/competition-demo.ps1 -Mode replay` 与 `scripts/competition-rollback-demo.ps1 -Mode replay`。回放无需模型；Live 模式是独立的付费并授权操作。

完整竞赛沿革见[初赛提交记录](competition/agentloom-preliminary-submission.md)。架构目标和迁移计划见[产品规格](specs/agent-tool-policy-gateway.md)。
