[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$RunRoot,
    [ValidateSet("direct", "delegated")]
    [string]$DispatchMode = "direct",
    [ValidatePattern("^task[0-9]+$")]
    [string]$RunNamespace = "task16",
    [ValidateRange(60, 1200)]
    [int]$TimeoutSeconds = 600,
    [ValidateRange(1, 30)]
    [int]$PollSeconds = 5,
    [string]$ControllerContainer = "hiclaw-controller",
    [string]$ManagerContainer = "hiclaw-manager",
    [string]$MatrixBaseUrl = "http://127.0.0.1:18080"
)

$ErrorActionPreference = "Stop"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$investigatorContainer = "hiclaw-worker-agentloom-investigator"
$verifierContainer = "hiclaw-worker-agentloom-verifier"
$runNamespaceRoot = [IO.Path]::GetFullPath(
    (Join-Path $repoRoot "artifacts\policy-broker\$RunNamespace")
)
$resolvedRunRoot = [IO.Path]::GetFullPath($RunRoot)
if (-not $resolvedRunRoot.StartsWith(
    $runNamespaceRoot + [IO.Path]::DirectorySeparatorChar,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "RunRoot must be inside the selected task artifact namespace"
}
if (-not (Test-Path -LiteralPath $resolvedRunRoot -PathType Container)) {
    throw "Task 16 run root is unavailable"
}
$contextPath = Join-Path $resolvedRunRoot "context.json"
$directEvidencePath = Join-Path $resolvedRunRoot "run-evidence.json"
$databasePath = Join-Path $resolvedRunRoot "broker.db"
$evidenceRoot = Join-Path $resolvedRunRoot "evidence"
$modelVerificationPath = Join-Path $resolvedRunRoot "model-verification.json"
$modelEvidencePath = Join-Path $resolvedRunRoot $(if ($DispatchMode -eq "delegated") {
    "delegation-run-evidence.json"
} else {
    "model-run-evidence.json"
})
$timeoutEvidencePath = Join-Path $resolvedRunRoot "delegation-timeout-evidence.json"
foreach ($requiredPath in @($contextPath, $directEvidencePath, $databasePath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Task 16 direct-run artifact is incomplete"
    }
    if ((Get-Item -LiteralPath $requiredPath).Length -gt 2MB) {
        throw "Task 16 direct-run artifact exceeds the size limit"
    }
}
if (Test-Path -LiteralPath $modelEvidencePath) {
    throw "Task 16 model evidence already exists"
}
if (
    $DispatchMode -eq "delegated" -and
    (Test-Path -LiteralPath $timeoutEvidencePath)
) {
    throw "Delegation timeout evidence already exists"
}
$context = Get-Content -Raw -LiteralPath $contextPath | ConvertFrom-Json
$directEvidence = Get-Content -Raw -LiteralPath $directEvidencePath | ConvertFrom-Json
if (
    $context.schemaVersion -ne "agentloom.sandbox-e2e-context/v1alpha1" -or
    $directEvidence.schemaVersion -ne "agentloom.agentteams-sandbox-e2e/v1alpha1" -or
    $directEvidence.status -ne "DIRECT_PASS" -or
    $directEvidence.workspaceDigest -ne $context.workspaceDigest -or
    $directEvidence.sandboxImage -notmatch "^(?:sha256:[a-f0-9]{64}|[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64})$"
) {
    throw "Task 16 direct-run artifact failed validation"
}
$sandboxImage = [string]$directEvidence.sandboxImage
$databaseUrlPath = $databasePath.Replace("\", "/")
$databaseUrl = "sqlite:///$databaseUrlPath"

function Invoke-Docker {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $output = & docker @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed"
    }
    return @($output)
}

function Get-HiclawJson {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $dockerArguments = @("exec", $ControllerContainer, "hiclaw") +
        $Arguments + @("-o", "json")
    return (Invoke-Docker -Arguments $dockerArguments | Out-String) |
        ConvertFrom-Json
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
        TimeoutSec = 20
    }
    if (-not [string]::IsNullOrWhiteSpace($AuthToken)) {
        $arguments.Headers = @{ Authorization = "Bearer $AuthToken" }
    }
    if ($null -ne $Body) {
        $arguments.ContentType = "application/json"
        $arguments.Body = $Body | ConvertTo-Json -Depth 20
    }
    try {
        return Invoke-RestMethod @arguments
    }
    catch {
        throw "Matrix request failed"
    }
}

function Send-MatrixText {
    param(
        [Parameter(Mandatory)][string]$RoomId,
        [Parameter(Mandatory)][string]$Text,
        [string]$MentionUserId = "",
        [Parameter(Mandatory)][string]$AuthToken
    )

    $roomSegment = [uri]::EscapeDataString($RoomId)
    $transactionId = [Guid]::NewGuid().ToString("N")
    $body = @{
        msgtype = "m.text"
        body = $Text
    }
    if (-not [string]::IsNullOrWhiteSpace($MentionUserId)) {
        $body["m.mentions"] = @{ user_ids = @($MentionUserId) }
    }
    $response = Invoke-Matrix -Method Put `
        -Path "/_matrix/client/v3/rooms/$roomSegment/send/m.room.message/$transactionId" `
        -AuthToken $AuthToken -Body $body
    if ([string]::IsNullOrWhiteSpace([string]$response.event_id)) {
        throw "Matrix did not return an event ID"
    }
    return [pscustomobject]@{
        eventId = [string]$response.event_id
        roomId = $RoomId
        mentionedUserId = $MentionUserId
    }
}

function Find-DelegationEvent {
    param(
        [Parameter(Mandatory)][string[]]$RoomIds,
        [Parameter(Mandatory)][string]$ExpectedSender,
        [Parameter(Mandatory)][string]$ExpectedMentionUserId,
        [Parameter(Mandatory)][string]$Marker,
        [string]$RequiredText = "",
        [Parameter(Mandatory)][long]$StartedAtMilliseconds,
        [Parameter(Mandatory)][string]$AuthToken
    )

    foreach ($roomId in $RoomIds) {
        $roomSegment = [uri]::EscapeDataString($roomId)
        $from = ""
        for ($page = 0; $page -lt 10; $page++) {
            $path = "/_matrix/client/v3/rooms/$roomSegment/messages?dir=b&limit=100"
            if (-not [string]::IsNullOrWhiteSpace($from)) {
                $path += "&from=$([uri]::EscapeDataString($from))"
            }
            try {
                $feed = Invoke-Matrix -Method Get -Path $path `
                    -AuthToken $AuthToken -Body $null
            }
            catch {
                break
            }
            $reachedStart = $false
            foreach ($event in @($feed.chunk)) {
                if (
                    $null -ne $event.origin_server_ts -and
                    $event.origin_server_ts -lt $StartedAtMilliseconds
                ) {
                    $reachedStart = $true
                    continue
                }
                if ($event.sender -ne $ExpectedSender) {
                    continue
                }
                if (
                    $event.type -ne "m.room.message" -or
                    $event.content.msgtype -ne "m.text" -or
                    @($event.content."m.mentions".user_ids) -notcontains $ExpectedMentionUserId
                ) {
                    continue
                }
                $lines = @(([string]$event.content.body) -split "`r?`n" |
                    ForEach-Object { $_.Trim() })
                if (
                    $lines -contains $Marker -and
                    (
                        [string]::IsNullOrWhiteSpace($RequiredText) -or
                        ([string]$event.content.body).Contains($RequiredText)
                    )
                ) {
                    return [pscustomobject]@{
                        sender = [string]$event.sender
                        eventId = [string]$event.event_id
                        roomId = $roomId
                        mentionedUserId = $ExpectedMentionUserId
                        originServerTimestamp = [long]$event.origin_server_ts
                    }
                }
            }
            if ($reachedStart -or [string]::IsNullOrWhiteSpace([string]$feed.end)) {
                break
            }
            $from = [string]$feed.end
        }
    }
    return $null
}

function Find-VerifierMarker {
    param(
        [Parameter(Mandatory)][string[]]$RoomIds,
        [Parameter(Mandatory)]$Verifier,
        [Parameter(Mandatory)][string]$Marker,
        [Parameter(Mandatory)][long]$StartedAtMilliseconds,
        [Parameter(Mandatory)][string]$AuthToken
    )

    foreach ($roomId in $RoomIds) {
        $roomSegment = [uri]::EscapeDataString($roomId)
        try {
            $feed = Invoke-Matrix -Method Get `
                -Path "/_matrix/client/v3/rooms/$roomSegment/messages?dir=b&limit=100" `
                -AuthToken $AuthToken -Body $null
        }
        catch {
            continue
        }
        foreach ($event in @($feed.chunk)) {
            if ($event.sender -ne $Verifier.matrixUserID) {
                continue
            }
            if (
                $null -eq $event.origin_server_ts -or
                $event.origin_server_ts -lt $StartedAtMilliseconds
            ) {
                continue
            }
            if ($event.type -ne "m.room.message" -or $event.content.msgtype -ne "m.text") {
                continue
            }
            $lines = @(([string]$event.content.body) -split "`r?`n" |
                ForEach-Object { $_.Trim() })
            if ($lines -contains $Marker) {
                return [pscustomobject]@{
                    sender = [string]$event.sender
                    eventId = [string]$event.event_id
                    roomId = $roomId
                    originServerTimestamp = [long]$event.origin_server_ts
                }
            }
        }
    }
    return $null
}

$listener = @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)
if ($listener.Count -ne 1) {
    throw "Exactly one sandbox E2E Policy Broker listener is required"
}
$listenerProcess = Get-CimInstance Win32_Process `
    -Filter "ProcessId=$($listener[0].OwningProcess)"
if ($null -eq $listenerProcess -or $listenerProcess.CommandLine -notmatch "agentloom\.policy_mcp") {
    throw "Sandbox E2E Policy Broker listener identity is invalid"
}
$null = Invoke-Docker -Arguments @(
    "exec", $verifierContainer, "sh", "-lc",
    "mcporter list >/dev/null 2>&1"
)

$configurationContainers = if ($DispatchMode -eq "delegated") {
    @($ManagerContainer, $investigatorContainer, $verifierContainer)
} else {
    @($investigatorContainer, $verifierContainer)
}
$configurationOutput = & (Join-Path $PSScriptRoot "configure-minimax-provider.ps1") `
    -Model "MiniMax-M2.5" `
    -Containers $configurationContainers
if ($LASTEXITCODE -ne 0) {
    throw "MiniMax configuration failed"
}
$modelConfiguration = @(
    ($configurationOutput | Out-String | ConvertFrom-Json)
)
if (
    $modelConfiguration.Count -ne $configurationContainers.Count -or
    @($modelConfiguration | Where-Object {
        $_.provider -ne "minimax-cn" -or
        $_.model -ne "MiniMax-M2.5" -or
        $_.connectionVerified -ne $true
    }).Count -ne 0
) {
    throw "MiniMax connection verification did not converge"
}

$manager = Get-HiclawJson -Arguments @("get", "managers", "default")
$team = Get-HiclawJson -Arguments @("get", "teams", "agentloom-repair")
$workers = Get-HiclawJson -Arguments @(
    "get", "workers", "--team", "agentloom-repair"
)
$investigator = $workers.workers |
    Where-Object { $_.name -eq "agentloom-investigator" }
$verifier = $workers.workers |
    Where-Object { $_.name -eq "agentloom-verifier" }
if ($null -in @($investigator, $verifier)) {
    throw "AgentLoom Investigator or Verifier identity is unavailable"
}
if (
    $manager.phase -ne "Running" -or
    $team.phase -ne "Active" -or
    $investigator.phase -ne "Running" -or
    $verifier.phase -ne "Running"
) {
    throw "AgentLoom Manager, Team, Investigator, or Verifier is not ready"
}
$adminUser = (Invoke-Docker -Arguments @(
    "exec", $ManagerContainer, "printenv", "HICLAW_ADMIN_USER"
) | Select-Object -First 1).Trim()
$adminPassword = (Invoke-Docker -Arguments @(
    "exec", $ManagerContainer, "printenv", "HICLAW_ADMIN_PASSWORD"
) | Select-Object -First 1).Trim()
if (
    [string]::IsNullOrWhiteSpace($adminUser) -or
    [string]::IsNullOrWhiteSpace($adminPassword)
) {
    throw "Matrix administrator credentials are unavailable"
}
$matrixDomain = $manager.matrixUserID.Split(":", 2)[1]
$adminMatrixUserId = "@$adminUser`:$matrixDomain"
$authToken = ""
$markerEvent = $null
$taskEnvelopeEvent = $null
$managerDelegationEvent = $null
$delegationEvent = $null
$probeEvent = $null
try {
    $login = Invoke-Matrix -Method Post -Path "/_matrix/client/v3/login" -Body @{
        type = "m.login.password"
        identifier = @{ type = "m.id.user"; user = $adminMatrixUserId }
        password = $adminPassword
    }
    $authToken = [string]$login.access_token
    if (
        [string]::IsNullOrWhiteSpace($authToken) -or
        [string]$login.user_id -ne $adminMatrixUserId
    ) {
        throw "Matrix login did not return an access token"
    }
    $joined = Invoke-Matrix -Method Get -Path "/_matrix/client/v3/joined_rooms" `
        -AuthToken $authToken -Body $null
    $roomIds = @($joined.joined_rooms)
    if (
        $roomIds -notcontains $manager.roomID -or
        $roomIds -notcontains $investigator.roomID -or
        $roomIds -notcontains $verifier.roomID -or
        $roomIds -notcontains $team.teamRoomID
    ) {
        throw "Matrix administrator cannot observe the required AgentLoom rooms"
    }

    $modelTask = $context.tasks.model
    $taskId = [string]$modelTask.taskId
    $marker = [string]$modelTask.successMarker
    $issueRequestJson = $modelTask.issuanceRequest | ConvertTo-Json -Depth 20 -Compress
    $toolRequestJson = $modelTask.toolRequest | ConvertTo-Json -Depth 20 -Compress
    $verifierInstructions = @"
1. Do not use shell, exec, Python, or a local pytest command.
2. Call agentloom-policy-broker.issue_skill_execution_grant with {"request":$issueRequestJson}.
3. If issuance succeeds, immediately call agentloom-policy-broker.execute_governed_tool with {"request":{"signedGrant":"use the exact structured signed Grant returned by step 2 without displaying it","toolRequest":$toolRequestJson}}. Substitute the actual structured Grant object for that quoted instruction.
4. Never print, quote, summarize, persist, or send the "signedGrant" value in Matrix.
5. Only if the governed result status is SUCCEEDED, send the following exact standalone line from the Verifier identity:
$marker
6. On any failure, report failure without the PASS marker and stop. Do not retry with changed parameters, another task, another Skill, or another tool.
"@.Trim()
    if ($DispatchMode -eq "delegated") {
        $delegationMarker = "[$taskId] VERIFIER_DELEGATED"
        $investigatorDispatchBody = @"
$($verifier.matrixUserID)
$delegationMarker

$verifierInstructions
"@.Trim()
        $investigatorDispatchBodyBase64 = [Convert]::ToBase64String(
            [Text.Encoding]::UTF8.GetBytes($investigatorDispatchBody)
        )
        $investigatorDispatchCommand = @"
copaw channels send \
  --agent-id default \
  --channel matrix \
  --target-session "$($team.teamRoomID)" \
  --target-user "$($verifier.matrixUserID)" \
  --text "`$(printf '%s' '$investigatorDispatchBodyBase64' | base64 -d)"
"@.Trim()
        $taskEnvelopeText = @"
[$taskId] TASK_ENVELOPE

This task envelope is inert until a Manager delegation references its exact Matrix event ID. After that delegation, activate this envelope. Use the shell tool exactly once to run this exact CoPaw dispatch command:
$investigatorDispatchCommand

The Investigator must not call the Policy Broker, perform verification, fabricate the Verifier PASS marker, or retry with another room, Agent, task, Skill, or tool.
"@.Trim()
    }
    else {
        $prompt = @"
$($verifier.matrixUserID) [$taskId] This is an administrator E2E probe. Perform exactly one governed sandbox verification as the Verifier and preserve every JSON field below exactly.

Verifier instructions:
$verifierInstructions
"@.Trim()
    }
    $startedAt = [DateTimeOffset]::UtcNow
    $startedAtMilliseconds = $startedAt.ToUnixTimeMilliseconds()
    if ($DispatchMode -eq "delegated") {
        $taskEnvelopeEvent = Send-MatrixText -RoomId $investigator.roomID `
            -Text $taskEnvelopeText -MentionUserId "" -AuthToken $authToken
        $managerDelegationMarker = "[$taskId] MANAGER_DELEGATED $($taskEnvelopeEvent.eventId)"
        $managerDispatchBody = @"
$($investigator.matrixUserID)
$managerDelegationMarker
Execute the referenced TASK_ENVELOPE now.
The exact Investigator dispatch command is:
$investigatorDispatchCommand
Use the shell tool exactly once to run that command. Do not reply in this Leader Room.
"@.Trim()
        $managerDispatchBodyBase64 = [Convert]::ToBase64String(
            [Text.Encoding]::UTF8.GetBytes($managerDispatchBody)
        )
        $prompt = @"
$($manager.matrixUserID) [$taskId] Perform one bounded Leader Room notification for the existing agentloom-repair team. The task envelope is already staged, so do not create task files, state entries, projects, or additional messages. Do not call the Policy Broker or perform verification.

Use the shell tool exactly once to run this exact CoPaw dispatch command:
copaw channels send \
  --agent-id default \
  --channel matrix \
  --target-session "$($investigator.roomID)" \
  --target-user "$($investigator.matrixUserID)" \
  --text "`$(printf '%s' '$managerDispatchBodyBase64' | base64 -d)"

This is the AgentTeams Manager-to-Team-Leader notification step. After that one shell command succeeds, stop. Do not copy or summarize the task envelope, directly delegate to the Verifier, or retry with another Agent, room, task, or tool.
"@.Trim()
        $probeEvent = Send-MatrixText -RoomId $manager.roomID -Text $prompt `
            -MentionUserId $manager.matrixUserID -AuthToken $authToken
    }
    else {
        $probeEvent = Send-MatrixText -RoomId $verifier.roomID -Text $prompt `
            -MentionUserId $verifier.matrixUserID -AuthToken $authToken
    }

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        if ($DispatchMode -eq "delegated") {
            if ($null -eq $managerDelegationEvent) {
                $managerDelegationEvent = Find-DelegationEvent `
                    -RoomIds @($investigator.roomID) `
                    -ExpectedSender $manager.matrixUserID `
                    -ExpectedMentionUserId $investigator.matrixUserID `
                    -Marker $managerDelegationMarker `
                    -RequiredText $taskEnvelopeEvent.eventId `
                    -StartedAtMilliseconds $startedAtMilliseconds `
                    -AuthToken $authToken
            }
            if ($null -ne $managerDelegationEvent -and $null -eq $delegationEvent) {
                $delegationEvent = Find-DelegationEvent `
                    -RoomIds @($team.teamRoomID) `
                    -ExpectedSender $investigator.matrixUserID `
                    -ExpectedMentionUserId $verifier.matrixUserID `
                    -Marker $delegationMarker `
                    -StartedAtMilliseconds $managerDelegationEvent.originServerTimestamp `
                    -AuthToken $authToken
            }
            if ($null -ne $delegationEvent) {
                $markerEvent = Find-VerifierMarker -RoomIds @($team.teamRoomID) `
                    -Verifier $verifier -Marker $marker `
                    -StartedAtMilliseconds $delegationEvent.originServerTimestamp `
                    -AuthToken $authToken
            }
        }
        else {
            $markerEvent = Find-VerifierMarker -RoomIds @($verifier.roomID) `
                -Verifier $verifier -Marker $marker `
                -StartedAtMilliseconds $startedAtMilliseconds -AuthToken $authToken
        }
        if ($null -ne $markerEvent) {
            break
        }
        Start-Sleep -Seconds $PollSeconds
    }
    if ($null -eq $markerEvent) {
        if ($DispatchMode -eq "delegated") {
            $timeoutEvidence = [ordered]@{
                schemaVersion = "agentloom.agentteams-sandbox-delegation-timeout/v1alpha1"
                runId = $directEvidence.runId
                startedAt = $startedAt.ToString("o")
                timedOutAt = [DateTimeOffset]::UtcNow.ToString("o")
                status = "TIMEOUT"
                dispatchMode = $DispatchMode
                stages = [ordered]@{
                    taskEnvelopeStaged = $null -ne $taskEnvelopeEvent
                    managerDelegationObserved = $null -ne $managerDelegationEvent
                    investigatorDelegationObserved = $null -ne $delegationEvent
                    verifierMarkerObserved = $null -ne $markerEvent
                }
                taskEnvelope = $taskEnvelopeEvent
                probe = $probeEvent
                managerDelegation = $managerDelegationEvent
                delegation = $delegationEvent
                marker = $markerEvent
            }
            [IO.File]::WriteAllText(
                $timeoutEvidencePath,
                ($timeoutEvidence | ConvertTo-Json -Depth 10),
                [Text.UTF8Encoding]::new($false)
            )
        }
        throw "$DispatchMode MiniMax Verifier sandbox marker timed out"
    }
}
finally {
    $authToken = $null
    $adminPassword = $null
    $login = $null
}

& $venvPython @(
    "-m", "agentloom.sandbox_e2e", "verify",
    "--database-url", $databaseUrl,
    "--evidence-root", $evidenceRoot,
    "--context", $contextPath,
    "--expected-image", $sandboxImage,
    "--task", "model",
    "--output", $modelVerificationPath
)
if ($LASTEXITCODE -ne 0) {
    throw "MiniMax ToolCall is not backed by valid Docker Evidence"
}
$modelVerification = Get-Content -Raw -LiteralPath $modelVerificationPath |
    ConvertFrom-Json
$redactedModelConfiguration = @($modelConfiguration | ForEach-Object {
    [ordered]@{
        container = $_.container
        provider = $_.provider
        model = $_.model
        connectionVerified = $_.connectionVerified
    }
})
$evidenceSchema = if ($DispatchMode -eq "delegated") {
    "agentloom.agentteams-sandbox-delegation-e2e/v1alpha1"
} else {
    "agentloom.agentteams-sandbox-model-e2e/v1alpha1"
}
$redactedEvidence = [ordered]@{
    schemaVersion = $evidenceSchema
    runId = $directEvidence.runId
    startedAt = $startedAt.ToString("o")
    verifiedAt = [DateTimeOffset]::UtcNow.ToString("o")
    status = "PASS"
    dispatchMode = $DispatchMode
    sandboxImage = $sandboxImage
    workspaceDigest = $context.workspaceDigest
    caseId = $context.caseId
    caseFingerprint = $context.caseFingerprint
    modelConfiguration = $redactedModelConfiguration
    probe = [ordered]@{
        sender = $adminMatrixUserId
        eventId = $probeEvent.eventId
        roomId = $probeEvent.roomId
        mentionedUserId = $probeEvent.mentionedUserId
    }
    marker = $markerEvent
    model = $modelVerification.tasks.model
}
if ($DispatchMode -eq "delegated") {
    $redactedEvidence["taskEnvelope"] = $taskEnvelopeEvent
    $redactedEvidence["managerDelegation"] = $managerDelegationEvent
    $redactedEvidence["delegation"] = $delegationEvent
}
[IO.File]::WriteAllText(
    $modelEvidencePath,
    ($redactedEvidence | ConvertTo-Json -Depth 10),
    [Text.UTF8Encoding]::new($false)
)
$redactedEvidence | ConvertTo-Json -Depth 10
