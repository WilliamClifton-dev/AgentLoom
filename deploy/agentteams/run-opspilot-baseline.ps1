[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Container })]
    [string]$DemoRoot,
    [ValidateSet("deepseek-v4-flash", "deepseek-v4-pro")]
    [string]$Model = "deepseek-v4-flash",
    [ValidatePattern("^http://host\.docker\.internal:18089$")]
    [string]$ToolBaseUrl = "http://host.docker.internal:18089",
    [string]$ControllerContainer = "hiclaw-controller",
    [string]$ManagerContainer = "hiclaw-manager",
    [string]$MatrixBaseUrl = "http://127.0.0.1:18080",
    [int]$CreateTimeoutSeconds = 1800,
    [int]$IncidentTimeoutSeconds = 1200,
    [ValidateRange(30, 1800)]
    [int]$CompletionReminderSeconds = 240,
    [int]$PollSeconds = 10,
    [string]$EvidencePath = ".\artifacts\agentteams\opspilot-baseline.json"
)

$ErrorActionPreference = "Stop"
$teamName = "opspilot-zero-demo"
$leaderName = "opspilot-zero-demo-leader"
$businessWorkers = @(
    "alert-intake",
    "rca-analyst",
    "remediation-planner",
    "recovery-verifier"
)

function Invoke-Docker {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $output = & docker @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($Arguments -join ' ') failed"
    }
    return $output
}

function Get-HiclawJson {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $dockerArguments = @("exec", $ControllerContainer, "hiclaw") +
        $Arguments + @("-o", "json")
    return (Invoke-Docker -Arguments $dockerArguments | Out-String) |
        ConvertFrom-Json
}

function Test-HiclawResource {
    param(
        [Parameter(Mandatory)][string]$Kind,
        [Parameter(Mandatory)][string]$Name
    )

    & docker exec $ControllerContainer hiclaw get $Kind $Name -o json `
        1>$null 2>$null
    return $LASTEXITCODE -eq 0
}

function Invoke-Matrix {
    param(
        [Parameter(Mandatory)][ValidateSet("Get", "Post", "Put")][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [string]$AuthToken = "",
        [object]$Body
    )

    $arguments = @{
        Method = $Method
        Uri = "$MatrixBaseUrl$Path"
        TimeoutSec = 30
    }
    if (-not [string]::IsNullOrWhiteSpace($AuthToken)) {
        $arguments.Headers = @{ Authorization = "Bearer $AuthToken" }
    }
    if ($null -ne $Body) {
        $arguments.ContentType = "application/json"
        $arguments.Body = $Body | ConvertTo-Json -Depth 20
    }
    return Invoke-RestMethod @arguments
}

function Get-MatrixSession {
    param([Parameter(Mandatory)]$Manager)

    $adminUser = (Invoke-Docker -Arguments @(
        "exec", $ManagerContainer, "printenv", "HICLAW_ADMIN_USER"
    ) | Select-Object -First 1).Trim()
    $adminPassword = (Invoke-Docker -Arguments @(
        "exec", $ManagerContainer, "printenv", "HICLAW_ADMIN_PASSWORD"
    ) | Select-Object -First 1).Trim()
    if ([string]::IsNullOrWhiteSpace($adminUser) -or
        [string]::IsNullOrWhiteSpace($adminPassword)) {
        throw "Matrix admin credentials are unavailable"
    }

    $matrixDomain = $Manager.matrixUserID.Split(":", 2)[1]
    $adminMatrixUserId = "@$adminUser`:$matrixDomain"
    $login = Invoke-Matrix -Method Post -Path "/_matrix/client/v3/login" -Body @{
        type = "m.login.password"
        identifier = @{ type = "m.id.user"; user = $adminMatrixUserId }
        password = $adminPassword
    }
    if ([string]::IsNullOrWhiteSpace($login.access_token)) {
        throw "Matrix login did not return a token"
    }
    return [ordered]@{
        userId = $adminMatrixUserId
        token = $login.access_token
    }
}

function Send-MatrixText {
    param(
        [Parameter(Mandatory)][string]$RoomId,
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$MentionUserId,
        [Parameter(Mandatory)][string]$AuthToken
    )

    $roomSegment = [uri]::EscapeDataString($RoomId)
    $transactionId = [guid]::NewGuid().ToString("N")
    $null = Invoke-Matrix -Method Put `
        -Path "/_matrix/client/v3/rooms/$roomSegment/send/m.room.message/$transactionId" `
        -AuthToken $AuthToken -Body @{
            msgtype = "m.text"
            body = $Text
            "m.mentions" = @{ user_ids = @($MentionUserId) }
        }
}

function Send-IncidentCompletionReminder {
    param(
        [Parameter(Mandatory)]$Team,
        [Parameter(Mandatory)]$Leader,
        [Parameter(Mandatory)][string]$IncidentId,
        [Parameter(Mandatory)][string]$CompletionMarker,
        [Parameter(Mandatory)][string]$AuthToken
    )

    $text = @"
$($Leader.matrixUserID) 请检查 Team 房间中 $IncidentId 的四个角色回执。若四个角色均已完成，
请立即基于已有回执发送完整事故报告，然后另发独立一行：
$CompletionMarker
不要重新派发任务；若仍缺少角色回执，请只说明缺少哪一个角色。
"@
    Send-MatrixText -RoomId $Team.teamRoomID -Text $text.Trim() `
        -MentionUserId $Leader.matrixUserID -AuthToken $AuthToken
}

function Get-FencedText {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Heading
    )

    $content = Get-Content -Raw -LiteralPath $Path
    $pattern = "(?s)##\s+" + [regex]::Escape($Heading) +
        '.*?```text\s*(?<body>.*?)\s*```'
    $match = [regex]::Match($content, $pattern)
    if (-not $match.Success) {
        throw "Cannot find fenced text under '$Heading' in $Path"
    }
    return $match.Groups["body"].Value.Trim()
}

function Wait-OpsPilotTeamReady {
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($CreateTimeoutSeconds)
    $last = "Team has not been observed"
    $expectedWorkers = @($businessWorkers) + $leaderName

    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        try {
            $team = Get-HiclawJson -Arguments @("get", "teams", $teamName)
            $workers = Get-HiclawJson -Arguments @("get", "workers", "--team", $teamName)
            $workerNames = @($workers.workers | ForEach-Object { $_.name })
            $notRunning = @($workers.workers | Where-Object { $_.phase -ne "Running" })
            $missing = @($expectedWorkers | Where-Object { $_ -notin $workerNames })
            if ($team.phase -eq "Active" -and $team.leaderReady -and
                $team.leaderName -eq $leaderName -and
                $workers.total -eq 5 -and $notRunning.Count -eq 0 -and
                $missing.Count -eq 0 -and
                -not [string]::IsNullOrWhiteSpace($team.teamRoomID)) {
                return [ordered]@{ team = $team; workers = $workers.workers }
            }
            $last = "team=$($team.phase), leader=$($team.leaderName), workers=$($workers.total)"
        }
        catch {
            $last = $_.Exception.Message
        }
        Start-Sleep -Seconds $PollSeconds
    }
    throw "OpsPilot Team did not become ready in time. Last state: $last"
}

function Wait-CoPawApiReady {
    param([Parameter(Mandatory)][string[]]$Containers)

    foreach ($container in $Containers) {
        $containerPort = if ($container -eq $ManagerContainer) { 18799 } else { 8088 }
        $deadline = [DateTimeOffset]::UtcNow.AddSeconds(180)
        $last = "CoPaw API has not been observed"
        while ([DateTimeOffset]::UtcNow -lt $deadline) {
            try {
                $binding = & docker port $container "$containerPort/tcp" 2>&1 |
                    Select-Object -First 1
                if ($LASTEXITCODE -ne 0 -or $binding -notmatch ":(?<port>\d+)$") {
                    throw "Cannot resolve CoPaw port"
                }
                $null = Invoke-RestMethod -Method Get `
                    -Uri "http://127.0.0.1:$($Matches.port)/api/models" `
                    -TimeoutSec 20
                break
            }
            catch {
                $last = $_.Exception.Message
                Start-Sleep -Seconds 5
            }
        }
        if ([DateTimeOffset]::UtcNow -ge $deadline) {
            throw "CoPaw API for $container did not become ready: $last"
        }
    }
}

function Get-RoomMessages {
    param(
        [Parameter(Mandatory)][string]$RoomId,
        [Parameter(Mandatory)][string]$AuthToken
    )

    $roomSegment = [uri]::EscapeDataString($RoomId)
    $feed = Invoke-Matrix -Method Get `
        -Path "/_matrix/client/v3/rooms/$roomSegment/messages?dir=b&limit=100" `
        -AuthToken $AuthToken -Body $null
    return @($feed.chunk)
}

function Wait-IncidentReport {
    param(
        [Parameter(Mandatory)]$Team,
        [Parameter(Mandatory)]$Leader,
        [Parameter(Mandatory)][string]$IncidentId,
        [Parameter(Mandatory)][string]$CompletionMarker,
        [Parameter(Mandatory)][long]$StartedAtMilliseconds,
        [Parameter(Mandatory)][string[]]$RequiredTerms,
        [Parameter(Mandatory)][string]$AuthToken
    )

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($IncidentTimeoutSeconds)
    $completionReminderAt = [DateTimeOffset]::UtcNow.AddSeconds(
        $CompletionReminderSeconds
    )
    $completionReminderSent = $false
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        $events = Get-RoomMessages -RoomId $Team.teamRoomID -AuthToken $AuthToken |
            Where-Object {
                $_.sender -eq $Leader.matrixUserID -and
                $_.origin_server_ts -ge $StartedAtMilliseconds -and
                $_.type -eq "m.room.message" -and
                $_.content.msgtype -eq "m.text"
            }
        $body = (@($events | ForEach-Object { [string]$_.content.body }) -join "`n")
        $hasIncident = $body -match [regex]::Escape($IncidentId)
        $hasCompletionMarker = @($events | Where-Object {
            $lines = @(([string]$_.content.body) -split "`r?`n" |
                ForEach-Object { $_.Trim() })
            $lines -contains $CompletionMarker
        }).Count -gt 0
        $missingTerms = @($RequiredTerms | Where-Object {
            $body -notmatch [regex]::Escape($_)
        })
        if ($hasIncident -and $hasCompletionMarker -and $missingTerms.Count -eq 0) {
            return @($events | Where-Object {
                $text = [string]$_.content.body
                $text -match [regex]::Escape($IncidentId) -and
                $text -notmatch "^(🔧|✅)"
            } | ForEach-Object {
                [ordered]@{
                    sender = $_.sender
                    eventId = $_.event_id
                    originServerTimestamp = $_.origin_server_ts
                    body = $_.content.body
                }
            })
        }
        if (-not $completionReminderSent -and
            [DateTimeOffset]::UtcNow -ge $completionReminderAt) {
            $reminder = @"
$($Leader.matrixUserID) 请检查 $IncidentId 的四个角色回执。若均已完成，请使用
message 工具将完整事故报告发送到 target=room:$($Team.teamRoomID)，然后向同一
Team 房间另发独立一行：$CompletionMarker
不要发送到 DM，不要重新派发已完成的任务；若缺少回执，请只说明缺少的角色。
"@
            Send-MatrixText -RoomId $Team.teamRoomID -Text $reminder.Trim() `
                -MentionUserId $Leader.matrixUserID -AuthToken $AuthToken
            $completionReminderSent = $true
        }
        Start-Sleep -Seconds $PollSeconds
    }
    throw "$IncidentId did not produce a complete leader-owned report in time"
}

function Assert-ToolTrace {
    param(
        [Parameter(Mandatory)][object[]]$Trace,
        [Parameter(Mandatory)][string[]]$RequiredTools,
        [Parameter(Mandatory)][string]$IncidentId
    )

    $observed = @($Trace | ForEach-Object { $_.tool } | Select-Object -Unique)
    $missing = @($RequiredTools | Where-Object { $_ -notin $observed })
    if ($missing.Count -gt 0) {
        throw "$IncidentId tool trace is incomplete: $($missing -join ', ')"
    }
}

function Save-BaselineEvidence {
    param([Parameter(Mandatory)]$Evidence)

    $resolved = [IO.Path]::GetFullPath($EvidencePath)
    $directory = Split-Path -Parent $resolved
    if ($directory) {
        [void](New-Item -ItemType Directory -Force -Path $directory)
    }
    [IO.File]::WriteAllText(
        $resolved,
        ($Evidence | ConvertTo-Json -Depth 30),
        [Text.UTF8Encoding]::new($false)
    )
}

$health = Invoke-RestMethod -Method Get -Uri "$ToolBaseUrl/health" -TimeoutSec 20
if (-not $health.ok) {
    throw "OpsPilot mock gateway health check failed"
}

$manager = Get-HiclawJson -Arguments @("get", "managers", "default")
$session = Get-MatrixSession -Manager $manager
$creationSent = $false
if (-not (Test-HiclawResource -Kind "teams" -Name $teamName)) {
    $createPath = Join-Path $DemoRoot "at\create_agents_messages.md"
    $creationRequest = Get-FencedText -Path $createPath `
        -Heading "复制到 Manager 的完整创建请求"
    $creationRequest = $creationRequest.Replace("<MOCK_TOOL_BASE_URL>", $ToolBaseUrl)
    Send-MatrixText -RoomId $manager.roomID -Text $creationRequest `
        -MentionUserId $manager.matrixUserID -AuthToken $session.token
    $creationSent = $true
}

$ready = Wait-OpsPilotTeamReady
$team = $ready.team
$workers = @($ready.workers)
$containerNames = @($ManagerContainer) + @($workers | ForEach-Object {
    "hiclaw-worker-$($_.name)"
})
Wait-CoPawApiReady -Containers $containerNames
& (Join-Path $PSScriptRoot "configure-deepseek-provider.ps1") `
    -Model $Model -Containers $containerNames | Write-Host

$leader = $workers | Where-Object { $_.name -eq $leaderName }
if ($null -eq $leader) {
    throw "The dedicated OpsPilot TeamLeader Worker is unavailable"
}

$incidentPath = Join-Path $DemoRoot "at\run_demo_task_message.md"
$incidentDefinitions = @(
    [ordered]@{
        id = "INC-1001"
        heading = "第一次任务：订单创建失败"
        scenario = "db_pool_exhausted"
        terms = @("db.pool.maxSize", "50", "8", "L1")
        tools = @(
            "mock_monitoring.list_alerts",
            "mock_logs.search_logs",
            "mock_traces.query_traces",
            "mock_config.list_changes",
            "mock_config.rollback_config",
            "mock_probe.check_endpoint",
            "mock_monitoring.query_metrics"
        )
    },
    [ordered]@{
        id = "INC-1002"
        heading = "第二次任务：订单历史页很慢"
        scenario = "slow_sql_degradation"
        terms = @("8f0a", "1843021", "L3")
        tools = @(
            "mock_monitoring.list_alerts",
            "mock_database.list_slow_queries",
            "mock_config.list_changes",
            "mock_database.enable_read_cache",
            "mock_database.create_index_plan",
            "mock_ticket.create_approval_task",
            "mock_probe.check_endpoint",
            "mock_monitoring.query_metrics"
        )
    }
)
$runs = @()
foreach ($definition in $incidentDefinitions) {
    $null = Invoke-RestMethod -Method Post `
        -Uri "$ToolBaseUrl/tools/$($definition.scenario)/reset" `
        -ContentType "application/json" -Body "{}" -TimeoutSec 20
    $incident = Get-FencedText -Path $incidentPath -Heading $definition.heading
    $incident = $incident.Replace("@<team_leader_name>", $leader.matrixUserID)
    $completionMarker = "[$($definition.id)] INCIDENT_REPORT_COMPLETE"
    $incident += @"


协作约束：不要使用 projectflow、taskflow、filesync 或共享任务目录。请在 Team
房间通过 Matrix @mention 依次向四个 Worker 内联传递本事故的 incident_id、
scenario_id、已有证据、HTTP 工具地址 $ToolBaseUrl 和角色输入；Worker 必须
直接调用 HTTP 工具并在房间回复。最后由 TeamLeader 汇总完整事故报告。
只有四个角色全部完成且最终报告已发送后，TeamLeader 才能另发独立一行：
$completionMarker
"@
    $startedAt = [DateTimeOffset]::UtcNow
    Send-MatrixText -RoomId $team.teamRoomID -Text $incident `
        -MentionUserId $leader.matrixUserID -AuthToken $session.token
    $reportEvents = Wait-IncidentReport -Team $team -Leader $leader `
        -IncidentId $definition.id `
        -CompletionMarker $completionMarker `
        -StartedAtMilliseconds $startedAt.ToUnixTimeMilliseconds() `
        -RequiredTerms $definition.terms -AuthToken $session.token
    $trace = Invoke-RestMethod -Method Get `
        -Uri "$ToolBaseUrl/tools/$($definition.scenario)/trace" -TimeoutSec 20
    Assert-ToolTrace -Trace @($trace.result) `
        -RequiredTools $definition.tools -IncidentId $definition.id
    $runs += [ordered]@{
        incidentId = $definition.id
        scenarioId = $definition.scenario
        startedAt = $startedAt.ToString("o")
        completedAt = [DateTimeOffset]::UtcNow.ToString("o")
        status = "PASS"
        completionMarker = $completionMarker
        markerMustBeIndependentTrimmedLine = $true
        leaderEvents = $reportEvents
        toolTrace = $trace.result
    }
}

$evidence = [ordered]@{
    schemaVersion = "agentloom.opspilot-baseline/v1alpha1"
    verifiedAt = [DateTimeOffset]::UtcNow.ToString("o")
    status = "PASS"
    model = $Model
    mockGateway = $ToolBaseUrl
    creationRequestSent = $creationSent
    team = [ordered]@{
        name = $team.name
        phase = $team.phase
        leaderName = $team.leaderName
        leaderMatrixUserID = $leader.matrixUserID
        teamRoomID = $team.teamRoomID
    }
    workers = @($workers | ForEach-Object {
        [ordered]@{
            name = $_.name
            role = $_.role
            phase = $_.phase
            runtime = $_.runtime
            matrixUserID = $_.matrixUserID
        }
    })
    incidents = $runs
}
Save-BaselineEvidence -Evidence $evidence
$evidence | ConvertTo-Json -Depth 8
