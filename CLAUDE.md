# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

AgentLoom 是一个 Agent Tool Policy Gateway 原型，为 Agent 工具调用提供身份绑定、Grant、策略约束、防重放和 Evidence 审计。AgentTeams 软件修复链路是已验证的参考集成，不是 Gateway 的核心运行时前提。

**核心特性：**
- AgentTeams v1.1.2 参考集成（Investigator、Implementer、Verifier）
- Policy Broker：HMAC 签名的 Grant、防重放、审批流程
- Docker 沙箱：隔离的 pytest 执行环境（禁网、只读工作区）
- Skill 生命周期管理：来源锁定、发布/隔离状态、版本控制
- 证据链：不可变的任务事件、可回放的 ToolCall 证据

## 开发环境

- **Python 版本：** 3.12（严格要求，不支持 3.13）
- **Windows 优先：** 主要在 Windows 11 上开发和测试
- **Shell：** PowerShell 用于部署脚本，Bash 用于基础命令

## 常用命令

### 环境设置
```powershell
# 创建虚拟环境并安装依赖
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

### 测试
```powershell
# 运行所有测试
.venv\Scripts\python -m pytest

# 运行单个测试文件
.venv\Scripts\python -m pytest tests/test_contracts.py

# 运行单个测试函数
.venv\Scripts\python -m pytest tests/test_contracts.py::test_agent_identity

# 跳过 Docker 测试（需要 Docker 环境）
.venv\Scripts\python -m pytest -m "not docker"
```

### 代码质量检查
```powershell
# Linting（Ruff）
.venv\Scripts\ruff check .

# 自动修复 Ruff 问题
.venv\Scripts\ruff check --fix .

# 类型检查（strict mypy）
.venv\Scripts\mypy src tests

# 安全审计
.venv\Scripts\pip-audit
```

### 数据库迁移
```powershell
# 升级到最新版本
.venv\Scripts\alembic upgrade head

# 创建新的迁移
.venv\Scripts\alembic revision -m "描述"

# 查看迁移历史
.venv\Scripts\alembic history

# 降级一个版本
.venv\Scripts\alembic downgrade -1
```

### CLI 工具
```powershell
# 启动 TUI 证据控制面板
.venv\Scripts\agentloom tui

# 运行无模型的 Mock 修复案例
.venv\Scripts\python -m agentloom.mock_repair `
  --case-root .\demo\cases\severity-normalization `
  --output-root .\artifacts\demo\severity-normalization
```

### 本地开发 Policy Broker
```powershell
# 设置开发密钥（至少 32 字节）
$env:AGENTLOOM_POLICY_SIGNING_KEY = "your-local-development-secret-key-here"

# 启动 stdio MCP Broker
.venv\Scripts\python -m agentloom.policy_mcp
```

### 完整部署（需要 AgentTeams）
```powershell
# Lite 模式（无模型快速开始）
scripts\bootstrap.ps1 -Profile lite

# Full 模式（需要 AgentTeams v1.1.2 和模型凭据）
scripts\bootstrap.ps1 -Profile full

# 配置 MiniMax Provider（在 Workers 部署后必须执行）
.\deploy\agentteams\configure-minimax-provider.ps1 -Model "MiniMax-M2.5"

# 运行 Live Repair（从项目根目录，使用相对路径）
.\deploy\agentteams\run-live-repair.ps1 `
  -TaskId 'YOUR-TASK-ID' `
  -CaseRoot ./demo/cases/severity-normalization `
  -Provider 'minimax-cn' `
  -Model 'MiniMax-M2.5' `
  -TimeoutSeconds 3600 `
  -SubmissionPath ./artifacts/benchmarks/YOUR-TASK/submission.json `
  -EvidencePath ./artifacts/benchmarks/YOUR-TASK/run-evidence.json
```

## 架构概览

### 核心组件

**1. 契约层 (`contracts.py`)**
- 所有跨进程边界的数据模型都继承 `ContractModel`（严格的 Pydantic，frozen + extra="forbid"）
- 关键类型：`AgentIdentity`、`SkillExecutionGrant`、`SkillMetadata`、`Evidence`、`TaskState`
- 风险等级：L0（无风险）、L1（自动化）、L2/L3（需人工审批）

**2. Policy Broker (`policy.py`, `policy_mcp.py`)**
- HMAC-SHA256 签名的 Grant，绑定 Consumer、参数、有效期、nonce（防重放）
- 两种接口：HTTP API（FastAPI，用于 Higress 路由）和 stdio MCP（本地开发）
- Grant 消费后，nonce 持久化到 SQLite，Broker 重启后仍有效
- 高风险操作（L2/L3）需要人工审批记录

**3. Skill Catalog (`skill_catalog.py`)**
- Skill 状态：`PUBLISHED`（可用）vs `QUARANTINED`（隔离）
- 来源锁定：每个 Skill 有 SHA-256 哈希和来源 URL
- Schema 验证：输入/输出的 JSON Schema
- 当前基线：1 个 PUBLISHED（code-review-and-quality），4 个 QUARANTINED

**4. 沙箱执行**
- **Docker 沙箱** (`docker_sandbox.py`)：生产模式，隔离容器，禁网，只读工作区挂载
- **本地沙箱** (`local_tools.py`)：仅用于可信开发，需要两个环境变量确认：
  - `AGENTLOOM_SANDBOX_BACKEND=local-development`
  - `AGENTLOOM_ALLOW_HOST_TEST_EXECUTION=true`
- 绝不在生产或 AgentTeams 部署中使用本地沙箱

**5. 任务与证据 (`storage.py`, `api.py`)**
- SQLite + Alembic 持久化
- 追加式因果事件：每个状态变更生成不可变事件
- Evidence：任务执行的摘要、输入/输出哈希、时间戳

**6. Skill 开发 (`skills/` 目录)**
- 团队原创 Skill 存放在 `skills/team-original/`
- 每个 Skill 包含：`skill.json`（元数据）、实现代码、测试套件
- Skill 测试应独立可运行：`pytest skills/team-original/<skill-name>/test_*.py`
- 当前已发布原创 Skill：`patch-scope-validator` v1.0.1

**7. AgentTeams 集成**
- 三个业务 Agent：`agentloom-investigator`（占用 `spec.leader` 槽位）、`agentloom-implementer`、`agentloom-verifier`
- Manager 不直接调用 Policy Broker
- 通过 Higress 认证网关路由 MCP 请求：`http://aigw-local.hiclaw.io:8080/mcp-servers/mcp-agentloom-policy-broker`
- **重要：** Workers 必须配置为使用正确的模型 Provider（通过 `configure-minimax-provider.ps1`）

### 数据流

```
Human/Administrator
  ↓
AgentTeams Manager（协调）
  ↓
Investigator（调查、根因分析）
  ↓ 委派
Implementer（生成补丁）
  ↓ 验证请求
Verifier（独立验证）
  ↓ ToolCall with Grant
Higress（身份认证）
  ↓
Policy Broker（签名校验、防重放、审批检查）
  ↓
Docker Sandbox（隔离执行 pytest）
  ↓
Evidence（可回放记录）
```

### 关键约束

**身份与权限：**
- Manager 无 Policy Broker 访问权限
- Worker 不持有 Broker 签名密钥
- 每个 ToolCall 需要有效的 `SkillExecutionGrant`

**沙箱安全：**
- Docker 镜像锁定版本
- 容器禁网（`--network none`）
- 工作区只读挂载（`:ro`）
- 输出限制和超时
- 执行后验证容器清理

**证据链：**
- 所有关键结论必须引用 Evidence ID
- Grant 的 nonce 消费记录持久化
- 任务事件追加式存储（不可篡改）

## 代码风格

- **类型注解：** 严格 mypy，所有公共函数必须有类型注解
- **Pydantic：** 跨边界数据用 `ContractModel`（frozen + extra="forbid"）
- **命名：**
  - 模块/包：`snake_case`
  - 类：`PascalCase`
  - 函数/变量：`snake_case`
  - 类型别名：`PascalCase`（如 `RiskLevel`）
- **行长：** 100 字符（Ruff 配置）
- **导入顺序：** Ruff 自动排序（E, F, I, UP, B）

## 测试策略

- **契约测试：** `tests/test_contracts.py` - 验证 Pydantic 模型的边界行为
- **集成测试：** `tests/test_agentteams_deployment.py` - 验证 AgentTeams 资源
- **沙箱测试：** `tests/test_docker_sandbox.py` - 需要 Docker，用 `@pytest.mark.docker` 标记
- **Mock 测试：** 优先使用确定性 fixture，避免真实 API 调用
- 所有测试必须在干净环境中可重复运行

## 重要文件路径

- **契约定义：** `src/agentloom/contracts.py`
- **Policy Broker：** `src/agentloom/policy.py`, `src/agentloom/policy_mcp.py`
- **Skill 目录：** `src/agentloom/skill_catalog.py`, `skills/catalog.json`
- **沙箱：** `src/agentloom/docker_sandbox.py`, `src/agentloom/local_tools.py`
- **数据库：** `src/agentloom/storage.py`, `migrations/versions/`
- **CLI：** `src/agentloom/cli.py`
- **部署：** `deploy/agentteams/`, `scripts/bootstrap.ps1`

## 环境变量

**必需（生产/AgentTeams）：**
- `AGENTLOOM_POLICY_SIGNING_KEY` - Broker 签名密钥（≥32 字节，仅环境注入）

**模型凭据（按 Provider）：**
- `MINIMAX_API_KEY` - MiniMax Provider（当前付费证据基线）
- 自定义 Provider 通过 Profile 的 `apiKeyEnvironmentVariable` 指定

**沙箱控制（开发专用）：**
- `AGENTLOOM_SANDBOX_BACKEND=local-development` - 启用本地沙箱
- `AGENTLOOM_ALLOW_HOST_TEST_EXECUTION=true` - 确认宿主机执行

**绝不允许：**
- 将签名密钥、模型凭据写入代码、配置文件或 Git 提交
- 在 Worker 资源或 MCP 配置中硬编码密钥

## 部署模式

**Lite（无模型）：**
- 运行确定性 Mock 案例
- 不需要 AgentTeams 或模型 API
- 用于快速验证和开发

**Full（完整治理链路）：**
- 需要 AgentTeams/HiClaw v1.1.2
- 需要模型 Provider 和凭据
- 启动 Manager、三个 Worker、Higress、Policy Broker
- 执行真实的多 Agent 协同和 Docker 沙箱验证

## 竞赛要求

此项目参加 GOAI 赛道一（Agent Infra）初赛。关键约束：
- **运行时：** 必须使用 AgentTeams v1.1.2
- **Agent 数量：** 3 个业务 Agent（Investigator、Implementer、Verifier）
- **Skill：** 必选项，当前 2 PUBLISHED / 4 QUARANTINED
  - `code-review-and-quality` (上游)
  - `patch-scope-validator` v1.0.1 (团队原创)
- **证据基线：** 当前本地 Lite `377 passed / 3 skipped / 0 failed`（共收集 380 项；3 个 skip 是 `tests/test_docker_sandbox_live.py` 的 live 沙箱用例，需要 Docker 守护进程）；最近一次 public-main GitHub Actions 门禁为 `379 passed / 0 skipped`（构建不可变沙箱镜像 `AGENTLOOM_TEST_SANDBOX_IMAGE` 后跑同一组用例）。`test-results.txt` 是提交的本地 Lite 快照；CI 将 Docker Full 快照写入 runner 临时目录，不与 Lite 快照做 drift 比较。
- **开源：** Apache-2.0，依赖披露见 `THIRD_PARTY.md`

## 常见问题排查

### AgentTeams Live Repair 问题

**问题：Workers 使用错误的模型**
- **症状：** `hiclaw get workers` 显示 `step-3.7-flash` 而不是 `MiniMax-M2.5`
- **原因：** Workers 部署时使用默认模型，未配置 Provider
- **解决：** 运行 `.\deploy\agentteams\configure-minimax-provider.ps1 -Model "MiniMax-M2.5"`
- **验证：** 容器内 CoPaw 配置已更新，虽然 Worker 元数据仍显示旧模型名

**问题：run-live-repair.ps1 路径错误**
- **症状：** `GetFullPath: 不支持给定路径的格式`
- **原因：** 从错误的目录调用脚本，或使用了绝对路径参数
- **解决：** 必须从项目根目录调用，使用相对路径（`./demo/cases/...`）
- **错误示例：** `cd deploy/agentteams && .\run-live-repair.ps1` ❌
- **正确示例：** `cd D:\Projects\Agent-Infra && .\deploy\agentteams\run-live-repair.ps1` ✅

**问题：Investigator 完成后不委派**
- **症状：** 运行超时，只完成 Investigator 阶段
- **原因：** Workers 未正确配置模型 Provider，无法调用 LLM
- **解决：** 确保已运行 Provider 配置脚本
- **验证：** 检查 Manager/Workers 的 `/api/models/active` 配置

**问题：输出目录未创建**
- **症状：** 脚本运行但没有生成证据文件
- **原因：** 脚本在早期阶段失败（路径、Provider 等）
- **检查：** 查看 PowerShell 错误输出，通常在前几行

详细架构设计见 `docs/architecture/agentloom-architecture.md`。
