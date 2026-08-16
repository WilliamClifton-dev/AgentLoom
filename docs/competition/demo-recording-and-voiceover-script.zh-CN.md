# AgentLoom 5:09 Demo 录制与配音脚本

## 成片目标

- 时长：约 5 分 09 秒。
- 画面：1920x1080，建议 30 FPS。
- 录制画面时关闭麦克风和系统声音，后期按段加入配音。
- 不现场调用模型；只展示公开仓库、已登录的 Element、脱敏 Evidence 和 TUI。
- 方括号中的文字是操作或语气提示，不需要念出来。

## 一、录制前准备（不要录进去）

### 1. 隐私检查

1. 开启 Windows 勿扰模式。
2. 退出微信、邮件、密码管理器和其他可能弹出通知的软件。
3. 浏览器隐藏书签栏、下载栏和个人头像。
4. 不打开 `.env`、环境变量、Docker Inspect、Worker 原始日志或 Matrix 原始导出。
5. 准备两个隔离的 Element 会话，不要录制登录过程：
   - `admin`：用于展示 Manager、Worker 和 Team Room 的跨房间协作事件；
   - `agentloom-developer`：只用于展示 L2 Human 审批。
6. 两个账号不要登录在同一浏览器 Profile。可分别使用 Chrome 普通窗口和无痕窗口，
   或在不同浏览器中登录，避免切换账号时录到登录页面。

### 2. 准备浏览器标签页

按以下顺序排列：

1. AgentLoom GitHub 仓库首页：
   `https://github.com/WilliamClifton-dev/AgentLoom`
2. README 的 Architecture 区域。
3. Element：`http://127.0.0.1:18088`，提前定位到要展示的房间和事件。
4. 当前 GitHub Actions：
   `https://github.com/WilliamClifton-dev/AgentLoom/actions/runs/31925933820`
5. AgentTeams PR #1141：
   `https://github.com/agentscope-ai/AgentTeams/pull/1141`

### 3. 准备终端

打开 Windows Terminal 或 PowerShell，字号建议 18-20。录制前执行：

```powershell
Set-Location 'D:\Projects\Agent-Infra'
function prompt { 'PS AgentLoom> ' }
Clear-Host
```

先在不录屏的情况下预检：

```powershell
.venv\Scripts\python.exe -m agentloom.cli inspect-live `
  --health-evidence .\artifacts\agentteams\health.json `
  --run-evidence .\artifacts\benchmarks\task24\task24-governed-20260815-p204013\severity-normalization\live\run-evidence.json `
  --verified-evidence .\artifacts\benchmarks\task24\task24-governed-20260815-p204013\severity-normalization\verified\artifacts\live-repair-evidence.json `
  --public-output
```

必须看到：

- 部署健康状态为 `PASS`；
- Manager 为 `Running`；
- AgentLoom Worker 为 `3/3`；
- 证据链摘要状态为 `PASS`；
- Task ID 为 `AL-T24-SEVERITY-20260815-P204013`；
- Provider/模型为 `minimax-cn / MiniMax-M2.5`；
- `hiddenTestsPassed` 为 `true`，`roleEventCount` 为 `3`；
- 路径显示为 `<redacted>`。

这是一份已经固化的 Task 24 MiniMax Evidence。预检和 TUI 都只读取本地证据，
不会再次请求 MiniMax，也不会消耗 Token。

### 4. 怎样避免“黑盒运行”

录屏展示的是固定 Evidence 回放，不是现场运行。双击根目录的
`START_TASK24_MINIMAX_REPLAY.cmd` 后，程序会先检查文件并运行 `inspect-live`：

1. 任意 Evidence 缺失时立即报错并停止；
2. 证据链校验失败时返回非零状态，不打开 TUI；
3. 只有摘要显示 `PASS` 后，按任意键才会进入 TUI。

如果以后调试真正的 AgentTeams live run，不要只等最终 TUI。至少同时观察 Element
里的角色事件，以及 `hiclaw-controller`、`hiclaw-manager` 和三个 AgentLoom Worker
容器日志。TUI 当前主要用于最终 Evidence 查看，不代表逐阶段的实时遥测。

可打开五个终端标签，分别执行下面的只读观察命令：

```powershell
docker logs -f --since 10m hiclaw-controller
docker logs -f --since 10m hiclaw-manager
docker logs -f --since 10m hiclaw-worker-agentloom-investigator
docker logs -f --since 10m hiclaw-worker-agentloom-implementer
docker logs -f --since 10m hiclaw-worker-agentloom-verifier
```

同时在 Element 中观察 Manager、Investigator、Implementer、Verifier 的事件顺序；
在主终端每隔几秒检查当前任务 Evidence 目录是否出现新的 JSON/patch 产物。若超过
一个轮询周期没有新事件或产物，先暂停任务并查日志，不要直接把超时当成成功。

## 二、正式画面与配音

## 00:00-00:35 项目定位

### 画面操作

1. 从 AgentLoom GitHub 仓库首页开始。
2. 鼠标缓慢指向 Logo、项目名称和第一段简介。
3. 不滚动过快，至少让项目名称完整停留 3 秒。

### 配音

> 大家好，我是零号工位的独立开发者。这个项目叫 AgentLoom。
>
> Agent 会写代码，也会调用各种 Skill。但到了真实研发环境，我们还得知道：
> Skill 从哪里来，谁有权使用，它改了什么，结果又是否可信。
>
> AgentLoom 做的，就是给多 Agent 协作补上一套可验证、可回放的治理机制。

## 00:35-01:15 多 Agent 分工

### 画面操作

1. 平滑滚动到 README 的 Architecture 图。
2. 按顺序指向 `Manager`、`Investigator`、`Implementer`、`Verifier`。
3. 最后指向 `Policy Broker`、`Docker Sandbox` 和 `Evidence`。

### 配音

> [稍慢] 这里的协同运行时是 AgentTeams。
>
> 任务进来后，Manager 先拆解；Investigator 调查根因；Implementer 在授权范围内
> 修改代码；Verifier 再独立验收。
>
> 这样不是为了凑 Agent 数量，而是为了分开相互冲突的责任。写补丁的人不能自己
> 宣布通过；每个角色都要留下证据。

## 01:15-02:05 AgentTeams 真实协作

### 画面操作

1. 切换到已经用 `admin` 登录的 Element，不展示登录页面。
2. 在 `Worker: agentloom-investigator` 中展示 Task 24 的
   `MANAGER_DELEGATED`。不要打开 `Leader DM: agentloom-investigator`；它不是本次
   Evidence 绑定的房间。
3. 切换到 `Team: agentloom-repair`，展示同一 Task 的 `VERIFIER_ASSIGNED`。
4. 再展示 Verifier 稍后发出的 `VERIFIER_ARTIFACT_DONE`。这表示角色产物已上传，
   不是最终测试 `PASS`；最终 PASS 在下一段的独立 Evidence/TUI 中展示。
5. 只让 Task ID、发送者、事件标记和顺序可见，不长时间展示消息正文、工具参数或
   线程内的完整执行输出。

录制前可直接打开以下三个本地事件深链接，避免在历史消息中手工滚动：

```text
http://127.0.0.1:18088/#/room/#hiclaw-worker-agentloom-investigator:matrix-local.hiclaw.io:18080/$vvk66ejFCnWzXX13AJgo41CTOzjjWk0WCNuOboQNGhw
http://127.0.0.1:18088/#/room/#hiclaw-team-agentloom-repair:matrix-local.hiclaw.io:18080/$zZxC2EFE7lY1N28Bym9yAThoqeB-5c9-B6vKmF3PfHo
http://127.0.0.1:18088/#/room/#hiclaw-team-agentloom-repair:matrix-local.hiclaw.io:18080/$JlFMZwLw5Lx3XFtYrDglc1GcGS0Pm9BUy_3M0Vt-Hg4
```

### 配音

> 现在看到的，是 AgentTeams v1.1.2 里真实发生过的跨房间委派。
>
> 这里，Manager 先把任务绑定给 Investigator；接着 Investigator 在 Team Room
> 里明确委派 Verifier；稍后，Verifier 上传独立审查产物并发出完成标记。
>
> 发送者、房间、事件 ID 和时间顺序都会写进 Evidence。[停顿] 最终测试 PASS
> 还必须由后面的独立主机验证和 Docker ToolCall 证明，不能用一段补写的总结或
> Agent 自己的声明来代替。

## 02:05-03:15 终端 Evidence 与 TUI

### 画面操作

1. 切换到已经清屏的 PowerShell。
2. 在资源管理器双击根目录下的 `START_TASK24_MINIMAX_REPLAY.cmd`，或在终端执行：

```powershell
.\START_TASK24_MINIMAX_REPLAY.cmd
```

3. 摘要出现后停留，让 `status`、`workers`、`provider`、`model`、
   `hiddenTestsPassed` 和 `roleEventCount` 可见。
4. 确认摘要为 `PASS`，再按任意键打开 TUI；如显示 `ERROR` 或 `FAIL`，立即停止录制。
5. 在 TUI 中依次停留于标题、Agent 状态、Task Events 和 Live Evidence 摘要。
6. 不点击 `Run selected case`，也不重新运行任务。
7. 约 03:10 使用 `Ctrl+C` 退出 TUI，然后切换下一画面。

### 配音

> 接下来是 AgentLoom 最核心的部分。
>
> 这里回放的是 Task 24 已经固化的 MiniMax Evidence。它记录了 severity
> normalization 案例的真实协作与验证结果。现在看到的是脱敏摘要，不会再次请求
> 模型，也不会消耗 Token。
>
> Verifier 运行测试前，请求先经过 Higress 确认身份，再由 Policy Broker 检查
> 一次性授权。条件全部匹配，测试才会进入禁网、只读的 Docker 沙箱。
>
> 最终只有一个成功的 ToolCall。更换调用者、修改参数或重放授权，都会被拒绝。
>
> 这个 TUI 是 AgentLoom 的治理界面。AgentTeams 负责协作；AgentLoom 把状态、
> 审批和验证结果整理成可回放证据。

## 03:15-03:55 Skill 治理能力

### 画面操作

1. 回到 README 的 Implemented Capabilities，或打开 PPT 的 Skill 生命周期页面。
2. 依次指向来源、版本、哈希、检测、Grant 和 Evidence。
3. 最后停留在 `2 PUBLISHED / 4 QUARANTINED`。

### 配音

> AgentLoom 的原创重点，是这一层 Skill 治理能力。
>
> 第三方 Skill 进入系统后，会绑定来源、许可证、版本和内容哈希，再经过分层检测。
> 执行前，Policy Broker 还会把调用者、工具、路径和参数写进一次性授权。
>
> 验证失败、越权或证据不完整时，系统会拒绝执行。这样，Skill 就变成有来源、
> 有边界、有验证结果的工程能力。

## 03:55-04:35 人工审批、CI 与上游贡献

### 画面操作

1. 切换到已用 `agentloom-developer` 登录的独立 Element 会话，再展示 L2 请求的
   参数摘要和回滚计划；不要在录屏中执行退出或登录。
2. 展示 `agentloom-developer` 的明确批准和最终 `APPROVED`。
3. 切换到 GitHub Actions，停留在 `quality` 全绿结果和 `379 passed` 日志。
4. 切换到 PR #1141，明确让 `Open` 状态可见。

录制前可直接打开以下两个本地事件深链接：

```text
http://127.0.0.1:18088/#/room/#hiclaw-team-agentloom-repair:matrix-local.hiclaw.io:18080/$6tiGHz989ycTpeliG0g-fusrmcSMxg2AsXfwwq42PTc
http://127.0.0.1:18088/#/room/#hiclaw-team-agentloom-repair:matrix-local.hiclaw.io:18080/$yuPWIMjKfyJvccYw0938JB8dIpdrIQvyhxhvHOPpn3o
```

第一个定位到 Manager 的 L2 请求，第二个定位到 `agentloom-developer` 的
`APPROVED` 决策。两个链接都应在独立的 Developer Element 会话中打开。

### 配音

> 对联网、安装依赖或者创建 PR 这类高风险操作，Agent 不能自己批准自己。
>
> 这里是一次真实的 L2 人工审批。请求绑定了参数、回滚计划和审批人身份；关键字段
> 一旦变化，就必须重新申请。
>
> 当前公开主分支已把三个 Docker 隔离测试纳入 CI，结果是 379 项通过、0 项跳过，
> 其他质量门禁也全部通过。
>
> 我还修复了 AgentTeams 保存 humanMembers 的问题，并提交了上游 PR #1141。
> 它目前仍在等待审核。

## 04:35-05:00 总结与边界

### 画面操作

1. 回到 README 架构图或 PPT 的运行证据总览。
2. 让 `379 passed / 0 skipped`、`6/6 PASSED` 和
   `2 PUBLISHED / 4 QUARANTINED` 至少各停留 2 秒。
3. 最后回到项目 Logo。

### 配音

> 最后，AgentLoom 把任务拆解、受控修改和独立验证，连接到人工审批、回滚与
> Evidence 沉淀。
>
> 它关注的不只是模型能不能写补丁，更关注谁在什么权限下做了什么，以及结果
> 如何被证明。
>
> 当前版本仍是初赛 MVP，不会默认向真实仓库提交 PR。所有边界都可以公开复核。
> 谢谢。

## 05:00-05:09 结束画面

### 画面操作

1. Logo 静止 6-7 秒。
2. 最后 2 秒淡出到黑色。

### 配音

不说话，保留自然尾音。背景音乐如有，最后两秒淡出。

## 三、后期配音建议

1. 七个段落分别录制，不满意时只重录当前段。
2. 语速以自然为准，不要为了填满时间持续说话。
3. 切换窗口、JSON 出现和 TUI 启动时保留 0.5-1 秒停顿。
4. 配音音量保持稳定，背景音乐至少比人声低 15 dB。
5. 不使用夸张播音腔；把稿子理解成向评委解释自己的工程选择。

## 四、录制后必须检查

- 视频能从头播放，分辨率为 1920x1080，声音清晰。
- 没有通知弹窗、用户名密码、Token、环境变量值或个人绝对路径。
- Element 中能看清角色发送者和事件先后顺序。
- 跨房间协作使用 `admin` 会话，L2 Human 审批使用 `agentloom-developer` 会话。
- Matrix 只展示 `VERIFIER_ARTIFACT_DONE`，没有把它口述成最终测试 `PASS`。
- 终端明确显示 `<redacted>`，没有原始 Evidence 路径。
- 终端显示 Task 24、`minimax-cn / MiniMax-M2.5`，并且预检结果为 `PASS`。
- 没有点击 `Run selected case`，录制过程没有重新调用模型。
- `379 passed / 0 skipped` 与当前公开 CI 一致。
- PR #1141 只说 Open、等待审核，没有说已经合并。
- 没有声称项目已生产就绪或默认自动提交真实 PR。
- 上传后使用无痕窗口验证公开视频无需登录即可播放。
