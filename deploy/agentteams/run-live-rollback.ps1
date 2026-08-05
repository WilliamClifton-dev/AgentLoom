[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
    [string]$TaskId,
    [ValidatePattern("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
    [string]$TeamName = "agentloom-repair",
    [string]$ControllerContainer = "hiclaw-controller",
    [string]$ManagerContainer = "hiclaw-manager",
    [string]$MatrixBaseUrl = "http://127.0.0.1:18080",
    [ValidateRange(60, 3600)]
    [int]$TimeoutSeconds = 1200,
    [ValidateRange(1, 60)]
    [int]$PollSeconds = 10,
    [string]$CaseRoot = ".\demo\cases\pagination-boundary",
    [string]$FailedPatchPath = "",
    [string]$SubmissionPath = "",
    [string]$EvidencePath = "",
    [ValidateSet("dashscope", "deepseek", "stepfun")]
    [string]$Provider = "dashscope",
    [ValidateSet("qwen3.7-plus", "deepseek-v4-pro", "step-3.7-flash")]
    [string]$Model = "qwen3.7-plus",
    [switch]$ConfirmPaidRun
)

$ErrorActionPreference = "Stop"

if (-not $ConfirmPaidRun) {
    throw "Live rollback collection can spend model quota. Rerun with -ConfirmPaidRun."
}
$approvedPairs = @{
    dashscope = "qwen3.7-plus"
    deepseek = "deepseek-v4-pro"
    stepfun = "step-3.7-flash"
}
if ($approvedPairs[$Provider] -ne $Model) {
    throw "Provider and model are not an approved live E2E pair."
}
$matrixUri = [Uri]$MatrixBaseUrl
if (
    -not $matrixUri.IsAbsoluteUri -or
    $matrixUri.Scheme -ne "http" -or
    $matrixUri.Host -notin @("127.0.0.1", "localhost") -or
    $matrixUri.Port -ne 18080 -or
    $matrixUri.AbsolutePath -ne "/" -or
    -not [string]::IsNullOrWhiteSpace($matrixUri.UserInfo) -or
    -not [string]::IsNullOrWhiteSpace($matrixUri.Query) -or
    -not [string]::IsNullOrWhiteSpace($matrixUri.Fragment)
) {
    throw "MatrixBaseUrl must be the local AgentTeams Matrix endpoint."
}
$MatrixBaseUrl = $matrixUri.GetLeftPart([UriPartial]::Authority)

function Invoke-Docker {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $output = & docker @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "docker command failed during live rollback collection"
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

function Get-CoPawBaseUri {
    param([Parameter(Mandatory)][string]$Container)

    $containerPort = if ($Container -eq $ManagerContainer) { 18799 } else { 8088 }
    $binding = Invoke-Docker -Arguments @(
        "port", $Container, "$containerPort/tcp"
    ) | Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace([string]$binding)) {
        throw "Cannot resolve CoPaw port for $Container."
    }
    if ([string]$binding -notmatch ":(?<port>\d+)$") {
        throw "Unexpected Docker port output for $Container."
    }
    return "http://127.0.0.1:$($Matches.port)"
}

function Assert-ActiveModel {
    param([Parameter(Mandatory)][string]$Container)

    $baseUri = Get-CoPawBaseUri -Container $Container
    $active = Invoke-RestMethod -Method Get `
        -Uri "$baseUri/api/models/active" -TimeoutSec 20
    if (
        $active.active_llm.provider_id -ne $Provider -or
        $active.active_llm.model -ne $Model
    ) {
        throw "AgentTeams active provider/model does not match requested live evidence metadata in $Container."
    }
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
    return Invoke-RestMethod @arguments
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
    $response = Invoke-Matrix -Method Put `
        -Path "/_matrix/client/v3/rooms/$roomSegment/send/m.room.message/$transactionId" `
        -AuthToken $AuthToken -Body @{
            msgtype = "m.text"
            body = $Text
            "m.mentions" = @{ user_ids = @($MentionUserId) }
        }
    if ([string]::IsNullOrWhiteSpace([string]$response.event_id)) {
        throw "Matrix did not return an event ID"
    }
    return [string]$response.event_id
}

function Test-ExactMarker {
    param(
        [Parameter(Mandatory)]$event,
        [Parameter(Mandatory)][string]$ExpectedSender,
        [Parameter(Mandatory)][string]$Marker,
        [Parameter(Mandatory)][long]$StartedAtMilliseconds
    )

    if (-not ($event.sender -eq $ExpectedSender)) {
        return $false
    }
    if (
        $null -eq $event.origin_server_ts -or
        $event.origin_server_ts -lt $StartedAtMilliseconds -or
        $event.type -ne "m.room.message" -or
        $event.content.msgtype -ne "m.text"
    ) {
        return $false
    }
    $lines = @(([string]$event.content.body) -split "`r?`n" |
        ForEach-Object { $_.Trim() })
    return $lines -contains $Marker
}

function Find-StrictMarkers {
    param(
        [Parameter(Mandatory)][string[]]$RoomIds,
        [Parameter(Mandatory)][object[]]$Requirements,
        [Parameter(Mandatory)][string]$AuthToken,
        [Parameter(Mandatory)][long]$StartedAtMilliseconds
    )

    $found = @{}
    foreach ($roomId in $RoomIds) {
        $roomSegment = [uri]::EscapeDataString($roomId)
        $from = ""
        for ($page = 0; $page -lt 20; $page++) {
            $path = "/_matrix/client/v3/rooms/$roomSegment/messages?dir=b&limit=100"
            if (-not [string]::IsNullOrWhiteSpace($from)) {
                $path += "&from=$([uri]::EscapeDataString($from))"
            }
            $feed = Invoke-Matrix -Method Get -Path $path `
                -AuthToken $AuthToken -Body $null
            $reachedStart = $false
            foreach ($event in @($feed.chunk)) {
                if (
                    $null -ne $event.origin_server_ts -and
                    $event.origin_server_ts -lt $StartedAtMilliseconds
                ) {
                    $reachedStart = $true
                }
                foreach ($requirement in $Requirements) {
                    if (
                        -not $found.ContainsKey($requirement.phase) -and
                        (Test-ExactMarker -event $event `
                            -ExpectedSender $requirement.sender `
                            -Marker $requirement.marker `
                            -StartedAtMilliseconds $StartedAtMilliseconds)
                    ) {
                        $found[$requirement.phase] = [ordered]@{
                            phase = $requirement.phase
                            agentName = $requirement.agentName
                            matrixUserId = $event.sender
                            roomId = $roomId
                            eventId = $event.event_id
                            originServerTimestamp = $event.origin_server_ts
                            bindingSha256 = $requirement.bindingSha256
                        }
                    }
                }
            }
            if ($reachedStart) {
                break
            }
            $from = [string]$feed.end
            if ([string]::IsNullOrWhiteSpace($from)) {
                break
            }
        }
    }
    return $found
}

function Wait-StrictMarkers {
    param(
        [Parameter(Mandatory)][string[]]$RoomIds,
        [Parameter(Mandatory)][object[]]$Requirements,
        [Parameter(Mandatory)][string]$AuthToken,
        [Parameter(Mandatory)][long]$StartedAtMilliseconds,
        [Parameter(Mandatory)][DateTimeOffset]$Deadline,
        [ValidateRange(0, 3600)][int]$ReminderAfterSeconds = 0,
        [scriptblock]$OnReminder = $null
    )

    $markers = @{}
    $reminderSent = $false
    $reminderAt = [DateTimeOffset]::FromUnixTimeMilliseconds(
        $StartedAtMilliseconds
    ).AddSeconds($ReminderAfterSeconds)
    while ([DateTimeOffset]::UtcNow -lt $Deadline) {
        $markers = Find-StrictMarkers -RoomIds $RoomIds `
            -Requirements $Requirements -AuthToken $AuthToken `
            -StartedAtMilliseconds $StartedAtMilliseconds
        if ($markers.Count -eq $Requirements.Count) {
            return $markers
        }
        if (
            -not $reminderSent -and
            $null -ne $OnReminder -and
            $ReminderAfterSeconds -gt 0 -and
            [DateTimeOffset]::UtcNow -ge $reminderAt
        ) {
            $null = & $OnReminder
            $reminderSent = $true
        }
        Start-Sleep -Seconds $PollSeconds
    }
    throw "Live rollback role event collection timed out"
}

$resolvedCaseRoot = [IO.Path]::GetFullPath($CaseRoot)
if ([string]::IsNullOrWhiteSpace($FailedPatchPath)) {
    $FailedPatchPath = Join-Path $resolvedCaseRoot "rollback\failed.patch"
}
$resolvedPatch = [IO.Path]::GetFullPath($FailedPatchPath)
if (-not (Test-Path -LiteralPath $resolvedPatch -PathType Leaf)) {
    throw "The deterministic failed candidate patch is missing."
}
if ((Get-Item -LiteralPath $resolvedPatch).Length -gt 128KB) {
    throw "The deterministic failed candidate patch exceeds 128 KiB."
}
$failedPatch = [IO.File]::ReadAllText(
    $resolvedPatch,
    [Text.UTF8Encoding]::new($false, $true)
)
$failedPatchSha256 = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData(
        [Text.Encoding]::UTF8.GetBytes($failedPatch)
    )
).ToLowerInvariant()
$rollbackReason = "Verifier rejected the candidate; restore the last approved snapshot."
$bindingPayload = @(
    $TaskId,
    "pagination-boundary",
    $failedPatchSha256,
    "RESTORE_APPROVED_SNAPSHOT",
    "lib/pagination.py",
    $rollbackReason
) -join "`n"
$bindingSha256 = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData(
        [Text.Encoding]::UTF8.GetBytes($bindingPayload)
    )
).ToLowerInvariant()

if ([string]::IsNullOrWhiteSpace($SubmissionPath)) {
    $SubmissionPath = ".\artifacts\live-rollback\$TaskId\submission.json"
}
if ([string]::IsNullOrWhiteSpace($EvidencePath)) {
    $EvidencePath = ".\artifacts\agentteams\live-rollback-$TaskId.json"
}
$resolvedSubmission = [IO.Path]::GetFullPath($SubmissionPath)
$resolvedEvidence = [IO.Path]::GetFullPath($EvidencePath)
if (
    (Test-Path -LiteralPath $resolvedSubmission) -or
    (Test-Path -LiteralPath $resolvedEvidence)
) {
    throw "Live rollback collection refuses to overwrite existing evidence."
}

$manager = Get-HiclawJson -Arguments @("get", "managers", "default")
$team = Get-HiclawJson -Arguments @("get", "teams", $TeamName)
$workers = Get-HiclawJson -Arguments @("get", "workers", "--team", $TeamName)
$investigator = $workers.workers |
    Where-Object { $_.name -eq "agentloom-investigator" }
$implementer = $workers.workers |
    Where-Object { $_.name -eq "agentloom-implementer" }
$verifier = $workers.workers |
    Where-Object { $_.name -eq "agentloom-verifier" }
if ($null -in @($investigator, $implementer, $verifier)) {
    throw "Expected AgentLoom business Agent identities are unavailable."
}
if ($team.phase -ne "Active" -or -not $team.leaderReady) {
    throw "AgentLoom Team is not ready."
}
$providerContainers = @(
    $ManagerContainer,
    "hiclaw-worker-$($investigator.name)",
    "hiclaw-worker-$($implementer.name)",
    "hiclaw-worker-$($verifier.name)"
)
foreach ($container in $providerContainers) {
    Assert-ActiveModel -Container $container
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
    throw "Matrix admin credentials are unavailable."
}
$matrixDomain = $manager.matrixUserID.Split(":", 2)[1]
$adminMatrixUserId = "@$adminUser`:$matrixDomain"
$login = Invoke-Matrix -Method Post -Path "/_matrix/client/v3/login" -Body @{
    type = "m.login.password"
    identifier = @{ type = "m.id.user"; user = $adminMatrixUserId }
    password = $adminPassword
}
$authToken = [string]$login.access_token
if ([string]::IsNullOrWhiteSpace($authToken)) {
    throw "Matrix login did not return an access credential."
}
$joinedRooms = Invoke-Matrix -Method Get `
    -Path "/_matrix/client/v3/joined_rooms" -AuthToken $authToken -Body $null
$joinedRoomIds = @($joinedRooms.joined_rooms)
if (
    $joinedRoomIds -notcontains $manager.roomID -or
    $joinedRoomIds -notcontains $investigator.roomID -or
    $joinedRoomIds -notcontains $team.teamRoomID
) {
    throw "Matrix admin cannot observe the Manager, Leader DM, and Team rooms."
}
$roomIds = @(
    $manager.roomID,
    $investigator.roomID,
    $team.teamRoomID
)

$startedAt = [DateTimeOffset]::UtcNow
$deadline = $startedAt.AddSeconds($TimeoutSeconds)
$failureMarker = "[$TaskId] VERIFICATION_FAILED $bindingSha256"
$rollbackMarker = "[$TaskId] ROLLBACK_REQUESTED $bindingSha256"
$executedMarker = "[$TaskId] ROLLBACK_EXECUTED $bindingSha256"
$verifiedMarker = "[$TaskId] ROLLBACK_VERIFIED $bindingSha256"
$prompt = @"
$($manager.matrixUserID) [$TaskId] Run a strict AgentTeams rollback workflow through team $TeamName. Delegate coordination to $($investigator.matrixUserID). The independent AgentLoom host will execute the candidate and rollback after collecting the role-owned events.

Candidate SHA-256: $failedPatchSha256
Candidate diff:
$failedPatch

Required interaction:
1. Investigator asks $($verifier.matrixUserID) to review the candidate against exact-boundary pagination behavior. The Verifier posts the exact standalone line $failureMarker from its own identity when it rejects the candidate, then Investigator reports that failure to Manager.
2. Only after receiving the failure report, Manager posts the exact standalone line $rollbackMarker from its own identity and directs Investigator to continue.
3. Investigator directly mentions $($implementer.matrixUserID). The Implementer acknowledges restoring the approved snapshot by posting the exact standalone line $executedMarker from its own identity.
4. Only after the Implementer event, Investigator directly mentions $($verifier.matrixUserID) again. The Verifier posts the exact standalone line $verifiedMarker from its own identity.

Never fabricate another identity's marker. Do not claim Human approval: this is an isolated L1 snapshot restore. Do not create another task ID. Do not include any credential in messages.
"@.Trim()
$null = Send-MatrixText -RoomId $manager.roomID -Text $prompt `
    -MentionUserId $manager.matrixUserID -AuthToken $authToken

$requirements = @(
    [ordered]@{
        phase = "VERIFICATION_FAILED"
        agentName = "agentloom-verifier"
        sender = $verifier.matrixUserID
        marker = $failureMarker
        bindingSha256 = $bindingSha256
    },
    [ordered]@{
        phase = "ROLLBACK_REQUESTED"
        agentName = "agentloom-manager"
        sender = $manager.matrixUserID
        marker = $rollbackMarker
        bindingSha256 = $bindingSha256
    },
    [ordered]@{
        phase = "ROLLBACK_EXECUTED"
        agentName = "agentloom-implementer"
        sender = $implementer.matrixUserID
        marker = $executedMarker
        bindingSha256 = $bindingSha256
    },
    [ordered]@{
        phase = "ROLLBACK_VERIFIED"
        agentName = "agentloom-verifier"
        sender = $verifier.matrixUserID
        marker = $verifiedMarker
        bindingSha256 = $bindingSha256
    }
)
$failureRequirements = @($requirements[0])
$failureEvents = Wait-StrictMarkers -RoomIds $roomIds `
    -Requirements $failureRequirements -AuthToken $authToken `
    -StartedAtMilliseconds $startedAt.ToUnixTimeMilliseconds() -Deadline $deadline
$failureEvent = $failureEvents.VERIFICATION_FAILED

$continuationPrompt = @"
$($manager.matrixUserID) [$TaskId] Continue the existing workflow after the Verifier failure event.

The Verifier posted this exact event in the AgentLoom Team Room:
$failureMarker

Verify the role-owned event, then post $rollbackMarker as an exact standalone line from your own Manager identity and direct $($investigator.matrixUserID) to continue. Never fabricate another identity's marker.
"@.Trim()
$null = Send-MatrixText -RoomId $manager.roomID -Text $continuationPrompt `
    -MentionUserId $manager.matrixUserID -AuthToken $authToken

$managerRequirements = @($requirements[1])
$managerEvents = Wait-StrictMarkers -RoomIds $roomIds `
    -Requirements $managerRequirements -AuthToken $authToken `
    -StartedAtMilliseconds $failureEvent.originServerTimestamp -Deadline $deadline
$managerEvent = $managerEvents.ROLLBACK_REQUESTED

$implementerReminder = {
    $text = @"
$($implementer.matrixUserID) [$TaskId] Retry Phase 3 using this complete inline bound plan. The shared task directory is not required for this acknowledgement.

Failed candidate SHA-256: $failedPatchSha256
Strategy: RESTORE_APPROVED_SNAPSHOT
Allowed changed path: lib/pagination.py
Reason: $rollbackReason
Binding SHA-256: $bindingSha256

Confirm the prior Manager rollback request in Matrix. If valid, post this exact standalone line from your own Implementer identity:
$executedMarker

Do not fabricate another identity's marker.
"@.Trim()
    $null = Send-MatrixText -RoomId $team.teamRoomID -Text $text `
        -MentionUserId $implementer.matrixUserID -AuthToken $authToken
}
$implementerRequirements = @($requirements[2])
$implementerEvents = Wait-StrictMarkers -RoomIds $roomIds `
    -Requirements $implementerRequirements -AuthToken $authToken `
    -StartedAtMilliseconds $managerEvent.originServerTimestamp -Deadline $deadline `
    -ReminderAfterSeconds 45 -OnReminder $implementerReminder
$implementerEvent = $implementerEvents.ROLLBACK_EXECUTED

$verifierContinuationPrompt = {
    $text = @"
$($verifier.matrixUserID) [$TaskId] Retry Phase 4 using this complete inline bound plan. The shared task directory is not required for this check.

Failed candidate SHA-256: $failedPatchSha256
Strategy: RESTORE_APPROVED_SNAPSHOT
Allowed changed path: lib/pagination.py
Reason: $rollbackReason
Binding SHA-256: $bindingSha256
Expected prior event: $executedMarker

Independently confirm in Matrix that the expected event came from $($implementer.matrixUserID) after the Manager rollback request and matches this binding. If valid, post this exact standalone line from your own Verifier identity:
$verifiedMarker

Do not repeat ROLLBACK_EXECUTED and do not fabricate another identity.
"@.Trim()
    $null = Send-MatrixText -RoomId $team.teamRoomID -Text $text `
        -MentionUserId $verifier.matrixUserID -AuthToken $authToken
}
$verifierRequirements = @($requirements[3])
$verifierEvents = Wait-StrictMarkers -RoomIds $roomIds `
    -Requirements $verifierRequirements -AuthToken $authToken `
    -StartedAtMilliseconds $implementerEvent.originServerTimestamp -Deadline $deadline `
    -ReminderAfterSeconds 45 -OnReminder $verifierContinuationPrompt
$events = @{
    VERIFICATION_FAILED = $failureEvent
    ROLLBACK_REQUESTED = $managerEvent
    ROLLBACK_EXECUTED = $implementerEvent
    ROLLBACK_VERIFIED = $verifierEvents.ROLLBACK_VERIFIED
}
if (
    $events.ROLLBACK_REQUESTED.originServerTimestamp -le
        $events.VERIFICATION_FAILED.originServerTimestamp -or
    $events.ROLLBACK_EXECUTED.originServerTimestamp -le
        $events.ROLLBACK_REQUESTED.originServerTimestamp -or
    $events.ROLLBACK_VERIFIED.originServerTimestamp -le
        $events.ROLLBACK_EXECUTED.originServerTimestamp
) {
    throw "Rollback role events are not strictly chronological."
}

$roleEvents = @(
    $events.VERIFICATION_FAILED,
    $events.ROLLBACK_REQUESTED,
    $events.ROLLBACK_EXECUTED,
    $events.ROLLBACK_VERIFIED
)
$submission = [ordered]@{
    schemaVersion = "agentloom.live-rollback-submission/v1alpha1"
    taskId = $TaskId
    caseId = "pagination-boundary"
    provider = $Provider
    model = $Model
    failedPatch = $failedPatch
    failedPatchSha256 = $failedPatchSha256
    bindingSha256 = $bindingSha256
    rollbackPlan = [ordered]@{
        strategy = "RESTORE_APPROVED_SNAPSHOT"
        allowedChangedPaths = @("lib/pagination.py")
        reason = $rollbackReason
    }
    roleEvents = $roleEvents
}
$runEvidence = [ordered]@{
    schemaVersion = "agentloom.live-rollback-run/v1alpha1"
    status = "SUBMISSION_READY"
    strict = $true
    taskId = $TaskId
    provider = $Provider
    model = $Model
    startedAt = $startedAt.ToUniversalTime().ToString("o")
    completedAt = [DateTimeOffset]::UtcNow.ToString("o")
    failedPatchSha256 = $failedPatchSha256
    bindingSha256 = $bindingSha256
    roleEvents = $roleEvents
}

[void](New-Item -ItemType Directory -Force -Path (Split-Path -Parent $resolvedSubmission))
[void](New-Item -ItemType Directory -Force -Path (Split-Path -Parent $resolvedEvidence))
[IO.File]::WriteAllText(
    $resolvedSubmission,
    ($submission | ConvertTo-Json -Depth 30),
    [Text.UTF8Encoding]::new($false)
)
[IO.File]::WriteAllText(
    $resolvedEvidence,
    ($runEvidence | ConvertTo-Json -Depth 30),
    [Text.UTF8Encoding]::new($false)
)
Write-Output ($runEvidence | ConvertTo-Json -Depth 30)
