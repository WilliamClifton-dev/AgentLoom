# AgentLoom 初赛 PPT 生产规格

## 1. 执行目标

本文件是交给制作者或 AI 的执行合同。目标是在不改变官方模板章节结构的前提
下，生成 AgentLoom 初赛 PPTX 和 PDF。最终材料必须让评委清楚看到：

1. AgentTeams v1.1.2 是真实协同运行时。
2. Investigator、Implementer、Verifier 通过结构化交接完成软件修复闭环。
3. AgentLoom 原创价值是 Skill Registry、Policy Broker、三层检测、Evidence、
   Human 审批和回滚治理。
4. Qwen 修复、StepFun 四角色回滚、真人 L2 审批和 175 项测试均有证据。
5. 第三方来源、当前缺口和未完成功能均诚实披露。

## 2. AI 开始前必须获得的输入

缺少任一必需输入时，AI 只能生成草稿和缺件清单，不能声称最终 PPT 已完成。

| 输入 | 必需 | 用途 |
| --- | --- | --- |
| 赛事参赛手册 PDF | 是 | 核对赛题、评分项、提交字段和材料限制 |
| 官方 PPT 框架模板 | 是 | 继承母版、版式、字体、章节页和结束页 |
| 本仓库 `main` 最新版本 | 是 | 核对代码、README、测试和依赖披露 |
| `agentloom-preliminary-submission.md` | 是 | 参赛内容与诚实边界的主来源 |
| `agentloom-architecture.md` | 是 | 架构、模块、契约和流程的详细来源 |
| 本目录三份 Evidence 摘要 | 是 | 回滚、L2 审批、上游贡献和录屏事实来源 |
| 脱敏 Matrix/Element 截图 | 最终版必需 | 展示真实角色发送者和 Human 决策 |
| `-PublicOutput` 回放截图 | 最终版必需 | 展示健康检查、回滚 PASS 和 TUI |
| GitHub Actions 与 PR #1141 截图 | 建议 | 展示工程质量和上游贡献 |

证据截图缺失时使用带编号的明显占位符，例如
`[待插入 E03：StepFun 回滚 PASS 截图]`。禁止生成、绘制或伪造真实系统截图。

## 3. 来源优先级

发生冲突时按以下顺序处理：

1. 赛事参赛手册和官方模板。
2. 已验证的本地 Evidence 与 GitHub 实时状态。
3. `agentloom-preliminary-submission.md`。
4. `agentloom-architecture.md`。
5. README 和其他仓库文档。
6. 旧 PPT 草稿。

旧 PPT 中的 `146 项测试`、`真人审批待完成`、`未创建任何 GitHub PR`、
`生产环境就绪` 均为过期或过度表述，必须替换。

## 4. 模板与版式合同

- 必须导入官方 PPTX 并编辑继承元素，不能只参考配色后从空白页重建。
- 内容映射严格覆盖第 1–19 页。若官方模板另有“感谢聆听”结束页，原样保留；
  结束页不计入 19 页业务内容，也不得塞入新功能说明。
- 不删除模板要求的章节页，不改变章节顺序，不新增业务内容页。
- 保留母版、布局、页脚、页码、Logo、字体、字号、段落和安全边距。
- 标题必须单行；正文优先删减，不通过缩小到不可读字号解决溢出。
- 简单流程用 PowerPoint 原生形状，先放连接线再放节点；不要把复杂架构截图化。
- 只使用真实产品、真实运行和真实代码证据。不得使用虚构客户、奖项、论文、
  指标、引言、用户故事或生成式假截图。
- 每页只承担一个叙事任务，章节页只保留章节标题和一句价值句。
- 所有外部事实和资产在演讲者备注末尾添加 `[Sources]` 区块。

## 5. 证据素材编号

| 编号 | 素材 | 最低可见信息 | 脱敏要求 |
| --- | --- | --- | --- |
| E01 | AgentTeams 健康检查 | v1.1.2、Manager、Team、3 Workers、Human、PASS | 不显示 Docker Inspect、密码、环境变量 |
| E02 | Qwen 修复证据 | 任务、三角色、隐藏测试、补丁哈希、PASS | 不显示 Key、完整原始 Trace、个人路径 |
| E03 | StepFun 回滚 Team Room | 四个事件、真实发送者、严格时间顺序 | 长消息拆成两个镜头/截图，不暴露登录信息 |
| E04 | 回滚公开回放 | stepfun、step-3.7-flash、roleEventCount=4、PASS | 必须使用 `-PublicOutput`，路径为 `<redacted>` |
| E05 | 真人 L2 审批 | Manager 请求、developer 决策、APPROVED | 不显示 Human 密码、Token、完整 Human JSON |
| E06 | GitHub Actions | 最新提交、CI success | 仓库公开页面，不显示本地目录 |
| E07 | AgentTeams PR #1141 | 标题、Open、待审核 | 不得写“已合并” |
| E08 | AgentLoom TUI | 角色状态、事件、哈希、Path `<redacted>` | 必须启用公开输出模式 |

## 6. 逐页生产说明

### 第 1 页：封面

- 叙事任务：建立项目、赛题和团队身份。
- 主标题：`AgentLoom`
- 副标题：`多智能体 Skill 治理与可验证修复平台`
- 辅助信息：`赛题三 · 软件研发全流程协同`、`零号工位 · 独立开发者`
- 版式：使用模板封面，不增加指标、架构图或长段落。

### 第 2 页：P0 一页总览

- 标题：`P0 · 一页纸速览`
- 顶部结论：`AgentLoom 在 AgentTeams 原生协同之上增加 SkillOps 治理、最小权限授权和独立验证，让第三方 Skill 的来源、权限、效果与失败处置都有证据。`
- 五个信息区：

| 区域 | 标题 | 可见文案 | 底部短标签 |
| --- | --- | --- | --- |
| 1 | 核心痛点 | 来源不清、权限不可控、效果不可证、失败不可回退 | `4 项痛点` |
| 2 | 整体方案 | AgentTeams 三 Agent + Skill Registry + Policy Broker MCP + 三层检测 | `治理控制面` |
| 3 | 主流程 | Issue -> 调查 -> 受控修复 -> 独立验证 -> 审批/回滚 -> Evidence | `6 步闭环` |
| 4 | 已验证成果 | Qwen 修复、StepFun 回滚、真人 L2 审批、隐藏测试、TUI | `175 项测试` |
| 5 | 差异化定位 | 不是通用 Coding Agent，而是可迁移的 Skill 治理控制面 | `可复用` |

- 禁止：`生产环境就绪`、`全自动创建 PR`。

### 第 3 页：目录

按模板列出八章：场景与价值、方案总览、多 Agent 协同、Skill 工程、工程验证
与安全、开放与开源、进展与规划、团队。不得新增“商业模式”等章节。

### 第 4 页：章节页 - 场景与价值

- 标题：`场景与价值`
- 价值句：`让第三方 Skill 从“可阅读提示词”升级为“可治理工程资产”。`

### 第 5 页：场景、痛点与目标用户

- 标题：`场景、痛点与目标用户`
- 场景句：`研发团队希望利用开源 Skill 自动处理软件缺陷，但来源、权限、评测和失败处置缺少统一控制。`
- 左侧四个痛点：
  1. 来源与许可证不可追溯，版本可能漂移。
  2. 工具、路径、网络和外部写权限过大。
  3. 自报成功不能证明修复有效，缺少隐藏测试与独立验证。
  4. 审批、失败、回滚和最终结论缺少统一 Evidence。
- 右侧三类用户与价值：
  1. 研发负责人：获得可复现的修复结论和回滚路径。
  2. Agent 平台工程师：用统一 Schema、MCP 与 Evidence 接入不同模型和工具。
  3. 安全/合规负责人：按 Skill、工具、路径、参数和 Human 决策审计。
- 页脚边界：`软件修复是首个 Demo；产品本体是跨场景 SkillOps 治理。`

### 第 6 页：章节页 - 方案总览

- 标题：`方案总览`
- 价值句：`在 AgentTeams 原生协同之上增加强制治理和证据闸门。`

### 第 7 页：总体架构与技术方案

- 标题：`总体架构与技术方案`
- 核心图：五层纵向架构，层间使用单向连接线。

```text
Element / TUI / CLI
        |
AgentTeams Manager + Team Room + Human
        |
Investigator -> Implementer -> Verifier
        |
Skill Registry + L1/L2/L3 Detection + Policy Broker MCP
        |
Sandbox + Test Runner + MinIO + SQLite + Evidence Report
```

- 图旁必须说明边界：
  - AgentTeams：Manager、Worker、Team、Human、Matrix、共享产物和协同运行。
  - AgentLoom：Skill 准入、风险、路由、Grant、状态、验证和证据。
- 技术栈：Python 3.12、FastAPI、Pydantic、SQLAlchemy、MCP、Typer、Textual、Rich。
- 模型：Qwen、DeepSeek、StepFun 通过配置注入，不写死在业务契约中。
- 禁止把 DevDispatcher 画成 AgentLoom 内部模块；它是独立开发辅助项目。

### 第 8 页：章节页 - 多 Agent 协同

- 标题：`多 Agent 协同`
- 价值句：`三个角色权责分离，任何 Agent 都不能独自宣布修复成功。`

### 第 9 页：Agent 角色与完整协作流

- 标题：`Agent 角色与完整协作流`
- 三个角色：

| Agent | 职责 | 主要输入 | 主要输出 | 禁止事项 |
| --- | --- | --- | --- | --- |
| Investigator | 复现失败、定位根因、收集证据 | Issue、代码快照、日志、失败测试 | RootCauseReport、EvidenceRef | 改代码、宣布修复成功 |
| Implementer | 在白名单内生成最小补丁 | 根因报告、约束、验收条件 | PatchArtifact、补丁哈希 | 扩大权限、跳过审批、验证自己的成功 |
| Verifier | 清洁快照中独立验证与风险审查 | 冻结补丁、验收条件 | VerificationResult、RiskReport | 修改补丁、降低标准 |

- 主状态：`Received -> Investigating -> Implementing -> Verifying -> Completed`
- L2 分支：`Implementing -> Awaiting Approval -> Approved / Rejected`
- 失败分支：`Verifying -> Rolling Back -> Retry / Failed`
- 底部强调：`Manager 是 AgentTeams 编排资源，不计入三个业务 Agent。`
- 证据：可在角落使用 E03 的小型真实截图，不要用截图替代流程图。

### 第 10 页：章节页 - Skill 工程

- 标题：`Skill 工程`
- 价值句：`保留上游来源，用本项目契约约束其可执行边界。`

### 第 11 页：核心 Skill、复用与生命周期

- 标题：`核心 Skill、复用与生命周期`
- 上半区：生命周期箭头
  `发现 -> 隔离 -> 溯源/哈希 -> L1 静态扫描 -> L2 沙箱评测 -> L3 场景回归 -> 审批发布 -> 监控/回滚`
- 下半区：六行表格

| Skill | 来源 | 绑定角色 | 当前状态 |
| --- | --- | --- | --- |
| debugging-and-error-recovery | addyosmani/agent-skills | Investigator | QUARANTINED |
| test-driven-development | addyosmani/agent-skills | Implementer | QUARANTINED |
| code-review-and-quality | addyosmani/agent-skills | Verifier | QUARANTINED |
| security-and-hardening | addyosmani/agent-skills | Verifier | QUARANTINED |
| using-agent-skills | addyosmani/agent-skills | Manager | QUARANTINED |
| skill-supply-chain-audit | 团队原创 | Manager + Verifier | IMPLEMENTED / EVAL PENDING |

- 页脚：`上游 Skill 是工作流内容源，不是编排、授权或验证运行时。`
- 禁止把上游 Skill 改名后标成原创，禁止把 `QUARANTINED` 写成 `PUBLISHED`。

### 第 12 页：章节页 - 工程验证与安全

- 标题：`工程验证与安全`
- 价值句：`每个成功结论都必须有角色归属、不可变产物和独立验证证据。`

### 第 13 页：运行证据、可观测、安全与云选择

- 标题：`运行证据、可观测、安全与云选择`
- 三列布局：

| 列 | 标题 | 可见要点 | 大数字/标签 |
| --- | --- | --- | --- |
| 1 | 真实运行与工程检查 | AgentTeams v1.1.2；Qwen 无人值守修复；StepFun 四角色回滚；隐藏测试；Ruff；strict mypy | `175 tests` |
| 2 | 安全与可观测 | L0-L3；短时参数绑定 Grant；路径/工具白名单；Human 审批；八类实体 ID | `L0-L3` |
| 3 | 诚实边界与贡献 | 真人 L2 已验证；PR #1141 已提交待审核；录屏和提交包待完成；未向真实业务仓库自动写 PR | `Evidence-bound` |

- 建议素材：E04 或 E08 放入第一列下方；E05 放入第二列或第三列下方。
- 截图必须保证 `PASS`、`APPROVED`、发送者和 `<redacted>` 可读。
- 演讲备注必须说清 Qwen 是历史真实修复证据，StepFun 是当前真实回滚证据，
  二者不是同一次运行。

### 第 14 页：章节页 - 开放与开源

- 标题：`开放与开源`
- 价值句：`原创控制面开源，第三方内容保留来源、许可证和不可变版本。`

### 第 15 页：可复用产物、协议与依赖披露

- 标题：`可复用产物、协议与依赖披露`
- 左侧“开源与依赖”：
  1. AgentLoom 原创控制面采用 Apache-2.0。
  2. AgentTeams v1.1.2 为直接依赖，Apache-2.0。
  3. addyosmani/agent-skills 为内容来源，MIT，未冒充原创，当前未 vendoring。
  4. DeepSec、VulnClaw、mcp-scan、Promptfoo、SWE-bench 仅作设计参考。
- 右侧“可复用产物”：Agent Identity Schema、Skill Manifest、Execution Grant、
  Evidence Bundle、AgentLoom-Bench Case。
- 页脚引用 `LICENSE`、`THIRD_PARTY.md`、`provenance/sources.yaml`。

### 第 16 页：章节页 - 进展与规划

- 标题：`进展与规划`
- 价值句：`主修复链与真人审批已跑通，提交前聚焦可复现演示和材料一致性。`

### 第 17 页：当前进展、里程碑与风险

- 标题：`当前进展、里程碑与风险`
- 三列：

| 列 | 内容 |
| --- | --- |
| 已完成 | AgentTeams 部署；三 Agent 协作；Qwen 修复；StepFun 回滚；真人 L2；隐藏测试；TUI；检测/授权/回滚；175 tests |
| 提交前 | 公开录屏；PPT/PDF；无痕访问检查；提交包敏感信息扫描；release/tag |
| 复赛候选 | 自动修复接入真实业务 Issue/PR；更多 Skill Eval；第二场景；OTLP；可选云 Skill |

- 底部风险条：模型波动、AgentTeams 版本变化、第三方 Skill 漂移、Demo 环境
  复杂、范围蔓延。
- 对应控制：版本锁定、回放证据、降级方案、非目标约束。
- 禁止继续把真人审批或 StepFun 回滚列为待办。

### 第 18 页：章节页 - 团队

- 标题：`团队`
- 价值句：`独立开发，架构、实现、验证和材料均有 Git 证据链。`

### 第 19 页：团队背景与分工

- 标题：`团队背景与分工`
- 团队名：`零号工位`
- 成员：`1 人`
- 身份：`独立开发者（多智能体系统 / Agent Infra）`
- 职能：需求与赛题对齐、架构、AgentTeams 集成、后端 API、TUI、测试、安全、
  文档、Demo。
- 可验证原则：`以 Git 提交、175 项测试和运行 Evidence 说明成果。`
- 明确：不虚构企业客户、论文、奖项或额外成员。

### 模板结束页（若存在）

保留模板原有结束页，只允许将副标题改为：
`AgentLoom · 多智能体 Skill 治理与可验证修复平台`

## 7. 演讲者备注与来源格式

每页备注先写 2–5 句讲解，再在末尾加入：

```text
[Sources]
- https://github.com/agentscope-ai/AgentTeams/tree/v1.1.2
- https://github.com/WilliamClifton-dev/AgentLoom
[/Sources]
```

只放该页实际使用的来源。推荐映射：

- 第 7、9、13 页：AgentTeams v1.1.2、AgentLoom 仓库。
- 第 11、15 页：addyosmani/agent-skills、LICENSE、THIRD_PARTY、provenance。
- 第 13、17 页：AgentLoom CI、PR #1141、两份脱敏 Evidence 摘要。
- 内部 Evidence 不编造公网 URL；在备注中写仓库内相对文档路径。

## 8. 生成步骤

1. 读取参赛手册，提取硬性字段和禁改模板要求，形成检查表。
2. 导入官方模板，检查所有母版、布局、占位符、页脚和结束页。
3. 为 1–19 页建立“输出页 -> 模板源页”映射，不新建平行设计体系。
4. 先填文本，保持模板原字号；溢出时缩短文案或换模板已有布局。
5. 使用原生形状绘制第 7、9、11 页图表，连接线置于节点下层。
6. 插入 E01–E08 中实际提供的脱敏截图；缺少素材时保留编号占位。
7. 为每页写演讲者备注和 `[Sources]`。
8. 导出新 PPTX，不覆盖官方模板；再导出 PDF。
9. 渲染每一页 PNG，逐页检查后再看全套缩略图。
10. 修复所有文字溢出、异常换行、重叠、低清截图、空占位符和页码错误。

## 9. 最终验收

- [ ] 1–19 页内容顺序与官方框架一致，模板结束页按原结构保留。
- [ ] 项目名、赛题、团队名与提交页面完全一致。
- [ ] AgentTeams 在架构、流程和证据页均为真实运行时。
- [ ] Manager 与三个业务 Agent 的边界准确。
- [ ] 五个上游 Skill 标记为 `QUARANTINED`，来源和许可证清楚。
- [ ] 175 项测试、真人 L2、StepFun 回滚、PR #1141 状态均为最新事实。
- [ ] 没有 `146 tests`、`生产就绪`、`PR 已合并`、`Skill 已发布`等过期表述。
- [ ] 所有真实系统截图均来自提供素材，未生成假截图。
- [ ] 所有公开终端/TUI 截图使用 `-PublicOutput`，路径为 `<redacted>`。
- [ ] PPTX 和 PDF 均可打开，字体未替换，标题不换行，正文无裁切。
- [ ] 逐页渲染无重叠、无空占位符、无密钥、密码、Token 或个人路径。
- [ ] 演讲者备注包含必要来源，外部 PR 只写 Open/待审核。

## 10. 可直接交给 AI 的任务指令

```text
读取赛事参赛手册、官方 PPT 框架模板、AgentLoom 仓库 main 分支，以及
docs/competition/ppt-production-spec.md 中的完整生产规格。严格编辑官方模板，
不要从空白页重建，不删除或重排第 1–19 页。若模板含结束页则保留。

按规格逐页填写可见文案、图表、真实脱敏截图和演讲者备注。以仓库及 Evidence
为事实来源，不得沿用 146 tests、真人审批待完成、未创建任何 GitHub PR、生产
环境就绪等过期表述。缺少真实截图时保留编号占位并报告缺件，禁止生成假截图。

输出独立的 AgentLoom 初赛方案 PPTX 和 PDF。完成后渲染每一页，逐页检查文字
溢出、重叠、异常换行、空占位符、字体替换、截图清晰度和敏感信息；修复后再
交付。最终同时给出逐页 QA 结果和仍缺少的素材清单。
```
