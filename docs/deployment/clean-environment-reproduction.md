# Clean Environment One-Command Reproduction

本文档的唯一权威入口是仓库内的
[`scripts/verify-clean-reproduction.ps1`](../../scripts/verify-clean-reproduction.ps1)。
脚本使用全新的证据目录，任何前置条件、Demo、测试或质量门禁失败都会以非零状态
退出；它不会把旧产物当成当前运行证据。

## Lite：无模型、无 Docker

前置条件：

- Windows、PowerShell 7、Git；
- 可启动的 Python 3.12；
- 能下载 `pyproject.toml` 中锁定范围内的依赖；
- 从全新 clone 运行，且初始不存在 `.venv` 和复现产物。

在仓库根目录执行一个命令：

```powershell
pwsh -NoProfile -File .\scripts\verify-clean-reproduction.ps1 `
  -Profile lite `
  -PythonExecutable "C:\path\to\python.exe"
```

如果 `python` 已明确指向 Python 3.12，可以省略 `-PythonExecutable`。脚本会依次：

1. 运行 Lite bootstrap 并创建独立 `.venv`；
2. 安装开发依赖并运行确定性 `severity-normalization` Demo；
3. 运行完整 pytest，并从 JUnit XML 计算通过、失败、错误和跳过数量；
4. 运行 Ruff、strict mypy、`pip-audit`、`pip check`；
5. 验证 Alembic 只有一个 `0006` head；
6. 输出脱敏的 `agentloom.clean-reproduction/v1alpha1` JSON 及其 SHA-256。

默认输出目录是 `artifacts/reproduction/clean-<UTC>-<suffix>/`。可通过
`-EvidenceRoot` 指定一个尚不存在的目录；目录已存在时脚本会拒绝运行，以防复用旧证据。

## Full：Docker、AgentTeams 和 Provider

Full 模式在 Lite 全部门禁之外，还会失败关闭地检查：

- Docker daemon 可用；
- AgentTeams/HiClaw 所需的五个容器都在运行；
- Provider 凭据只通过环境变量注入；
- bootstrap 生成了脱敏健康证据。

MiniMax：

```powershell
pwsh -NoProfile -File .\scripts\verify-clean-reproduction.ps1 `
  -Profile full -Provider minimax -Model MiniMax-M2.5
```

StepFun：

```powershell
pwsh -NoProfile -File .\scripts\verify-clean-reproduction.ps1 `
  -Profile full -Provider stepfun -Model step-3.7-flash
```

自定义 OpenAI-compatible Provider 使用 `-Provider custom` 和
`-ProviderProfilePath`。Profile 只保存环境变量名称，不能包含 API key。配置校验、
连接测试和严格 AgentTeams E2E 是三个独立门禁；Full bootstrap 成功不能替代具体
模型的修复能力验证。

## 已验证基线

2026-08-15 在一个新 clone 中执行 Lite 命令，初始不存在 `.venv` 或复现证据。结果：

- source commit：`3bd8a9efa422642dd33f2c21ae2b8af4787f3a0a`；
- pytest：`339 passed / 0 failed / 0 errors / 3 skipped`；
- Ruff、strict mypy、`pip-audit`、`pip check`：全部通过；
- Alembic：单一 `0006` head；
- 最终脱敏证据 SHA-256：
  `8b71c65c3efd391b5668f5db112637630769f61fe64de0549afa8ef9a1cd3c5a`。

该证据只证明 Lite 清洁复现。Full 模式脚本已实现失败关闭检查，但仍须在另一台清洁
Windows/Docker 主机上运行后，才能声明跨主机 Full 部署复现成功。

## 常见失败

- Python 不是 3.12：显式传入正确的 `-PythonExecutable`。
- EvidenceRoot 已存在：换一个新目录；不要删除或覆盖旧证据来伪造新运行。
- 依赖下载失败：保持失败状态，修复网络或镜像后在新的 clean clone 重试。
- Full 缺少 Docker、容器或 Provider 环境变量：补齐前置条件后重试；脚本不会降级成
  Lite 并声称 Full 成功。

真实 Demo 录屏与公开上传已经完成并验证。竞赛页面提交仍由 Human 完成，不属于该
脚本的自动化范围；第二台清洁 Windows/Docker 主机的 Full 运行仍需独立执行。
