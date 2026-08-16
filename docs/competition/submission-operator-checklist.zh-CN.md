# AgentLoom 初赛提交操作清单

> 本清单只供参赛者本人操作。GitHub 交付同步不登录、不上传或提交 GOAI 页面。

## 唯一上传文件

- 本地文件名：`AgentLoom-初赛提交包.zip`
- GitHub Release 附件：
  [`AgentLoom-v0.1.0-preliminary-submission.zip`](https://github.com/WilliamClifton-dev/AgentLoom/releases/download/v0.1.0/AgentLoom-v0.1.0-preliminary-submission.zip)
- SHA-256：`174E64EE0B2866133C0341539FBC7D1B0B45750094BF77B12DCDDD486DE29726`
- ZIP 成员：8 个
- 精确成员哈希：[submission-package-manifest.json](submission-package-manifest.json)

本地上传前执行：

```powershell
(Get-FileHash -LiteralPath '.\AgentLoom-初赛提交包.zip' -Algorithm SHA256).Hash
```

输出必须与上面的 SHA-256 完全一致；不一致时停止上传。

## 页面字段

- 平台：<https://www.goaihz.com>
- 作品名称：`AgentLoom：多智能体 Skill 治理与可验证修复平台`
- 团队名称：`零号工位`
- 参赛身份：`独立开发者`
- 赛题：`赛题三：软件研发全流程协同`
- 代码仓库：<https://github.com/WilliamClifton-dev/AgentLoom>
- Demo：<https://williamclifton-dev.github.io/AgentLoom/demo.html>
- Release：<https://github.com/WilliamClifton-dev/AgentLoom/releases/tag/v0.1.0>

作品简介（Python `len` 为 499，满足不超过 500 字符）：

> AgentLoom 是基于 AgentTeams 的多智能体 Skill 治理平台，解决第三方 Skill 来源不清、权限失控、自测不可信和证据分散。Human 将 Issue 交给 Manager，由 Investigator 定位根因、Implementer 受控修复、Verifier 在独立 Docker 沙箱裁决。Policy Broker 通过 MCP 绑定 Agent 身份、工具、路径、参数、时效和短时 Grant，Higress 强制认证，L2 操作由 Human 审批，生成可回放 Evidence。已在 AgentTeams v1.1.2 上完成 MiniMax 三案例治理链路，Task 24 两模式 6/6 通过，门禁为 375 passed / 3 skipped。创新点是用 Skill 生命周期治理、独立验证和 Evidence 闸门约束第三方工作流，而非通用编码 Agent。项目以 Apache-2.0 开源原创控制面；上游与团队原创 Skill 各 1 个发布，原创 Skill 3 次治理调用可严格重开，4 个上游 Skill 隔离，录屏已公开，提交待完成。

## 提交前核对

- [ ] 使用参赛者本人的账号登录 GOAI。
- [ ] 页面中的作品名、团队、身份和赛题与本清单一致。
- [ ] 仓库、Demo 和 Release 均使用公网 URL。
- [ ] 上传文件名和 SHA-256 正确，在线附件大小不是 0。
- [ ] AgentTeams PR #1141 只写 `OPEN`，不写成已合并。
- [ ] 第二台主机 Full 复现仍写为待独立执行。
- [ ] 页面没有 API Key、密码、Token、Signed Grant 或个人绝对路径。

## 提交后留证

- [ ] 点击最终提交或确认按钮。
- [ ] 保存成功页面截图，包含作品名、提交状态和平台时间。
- [ ] 记录提交编号（如有）、提交时间和 ZIP SHA-256。
- [ ] 重新打开作品页，确认状态不是草稿且附件仍可见。
- [ ] 公开截图不展示账号邮箱、手机号、Cookie 或凭据。

只有完成以上人工动作后，才能把“比赛页面提交”从待完成改为完成。
