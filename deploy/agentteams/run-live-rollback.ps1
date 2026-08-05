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
    [ValidateSet("dashscope", "deepseek")]
    [string]$Provider = "dashscope",
    [ValidateSet("qwen3.7-plus", "deepseek-v4-pro")]
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

function Get-MatrixEvent {
    param(
        [Parameter(Mandatory)][string]$RoomId,
        [Parameter(Mandatory)][string]$EventId,
        [Parameter(Mandatory)][string]$AuthToken
    )

    $roomSegment = [uri]::EscapeDataString($RoomId)
    $eventSegment = [uri]::EscapeDataString($EventId)
    return Invoke-Matrix -Method Get `
        -Path "/_matrix/client/v3/rooms/$roomSegment/event/$eventSegment" `
        -AuthToken $AuthToken -Body $null
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
        [Parameter(Mandatory)][string]$RoomId,
        [Parameter(Mandatory)][object[]]$Requirements,
        [Parameter(Mandatory)][string]$AuthToken,
        [Parameter(Mandatory)][long]$StartedAtMilliseconds
    )

    $found = @{}
    $roomSegment = [uri]::EscapeDataString($RoomId)
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
                        roomId = $RoomId
                        eventId = $event.event_id
                        originServerTimestamp = $event.origin_server_ts
                    }
                }
            }
        }
        if ($found.Count -eq $Requirements.Count -or $reachedStart) {
            break
        }
        $from = [string]$feed.end
        if ([string]::IsNullOrWhiteSpace($from)) {
            break
        }
    }
    return $found
}

function Wait-StrictMarkers {
    param(
        [Parameter(Mandatory)][string]$RoomId,
        [Parameter(Mandatory)][object[]]$Requirements,
        [Parameter(Mandatory)][string]$AuthToken,
        [Parameter(Mandatory)][long]$StartedAtMilliseconds,
        [Parameter(Mandatory)][DateTimeOffset]$Deadline
    )

    $markers = @{}
    while ([DateTimeOffset]::UtcNow -lt $Deadline) {
        $markers = Find-StrictMarkers -RoomId $RoomId `
            -Requirements $Requirements -AuthToken $AuthToken `
            -StartedAtMilliseconds $StartedAtMilliseconds
        if ($markers.Count -eq $Requirements.Count) {
            return $markers
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
if ($adminMatrixUserId -ne $manager.matrixUserID) {
    throw "Matrix admin identity does not match the AgentTeams Manager."
}
$login = Invoke-Matrix -Method Post -Path "/_matrix/client/v3/login" -Body @{
    type = "m.login.password"
    identifier = @{ type = "m.id.user"; user = $adminMatrixUserId }
    password = $adminPassword
}
$authToken = [string]$login.access_token
if ([string]::IsNullOrWhiteSpace($authToken)) {
    throw "Matrix login did not return an access credential."
}

$startedAt = [DateTimeOffset]::UtcNow
$deadline = $startedAt.AddSeconds($TimeoutSeconds)
$failureMarker = "[$TaskId] VERIFICATION_FAILED"
$rollbackMarker = "[$TaskId] ROLLBACK_REQUESTED"
$executedMarker = "[$TaskId] ROLLBACK_EXECUTED"
$verifiedMarker = "[$TaskId] ROLLBACK_VERIFIED"
$prompt = @"
$($investigator.matrixUserID) [$TaskId] Coordinate a real AgentTeams rollback trace for the supplied L1 candidate. The independent AgentLoom host will execute the candidate and rollback after collecting your role-owned events.

Candidate SHA-256: $failedPatchSha256
Candidate diff:
$failedPatch

Required interaction:
1. Ask $($verifier.matrixUserID) to review the candidate against exact-boundary pagination behavior. The Verifier must post the exact standalone line $failureMarker from its own identity when it rejects the candidate.
2. Stop and wait for the Manager's exact standalone $rollbackMarker event.
3. After that Manager event, directly mention $($implementer.matrixUserID). The Implementer acknowledges restoring the approved snapshot by posting the exact standalone line $executedMarker from its own identity.
4. Only after the Implementer event, directly mention $($verifier.matrixUserID) again. The Verifier posts the exact standalone line $verifiedMarker from its own identity.

Do not claim Human approval: this is an isolated L1 snapshot restore. Do not create another task ID. Do not include any credential in messages.
"@.Trim()
$null = Send-MatrixText -RoomId $team.teamRoomID -Text $prompt `
    -MentionUserId $investigator.matrixUserID -AuthToken $authToken

$failureRequirements = @(
    [ordered]@{
        phase = "VERIFICATION_FAILED"
        agentName = "agentloom-verifier"
        sender = $verifier.matrixUserID
        marker = $failureMarker
    }
)
$failureEvents = Wait-StrictMarkers -RoomId $team.teamRoomID `
    -Requirements $failureRequirements -AuthToken $authToken `
    -StartedAtMilliseconds $startedAt.ToUnixTimeMilliseconds() -Deadline $deadline
$failureEvent = $failureEvents.VERIFICATION_FAILED

$managerEventId = Send-MatrixText -RoomId $team.teamRoomID `
    -Text "$rollbackMarker`nRestore the approved snapshot and retain the failed candidate evidence." `
    -MentionUserId $investigator.matrixUserID -AuthToken $authToken
$managerEvent = Get-MatrixEvent -RoomId $team.teamRoomID `
    -EventId $managerEventId -AuthToken $authToken
if (
    -not (Test-ExactMarker -event $managerEvent `
        -ExpectedSender $manager.matrixUserID -Marker $rollbackMarker `
        -StartedAtMilliseconds $failureEvent.originServerTimestamp) -or
    $managerEvent.origin_server_ts -le $failureEvent.originServerTimestamp
) {
    throw "Manager rollback request event is not ordered after the failure."
}
$managerEvidence = [ordered]@{
    phase = "ROLLBACK_REQUESTED"
    agentName = "agentloom-manager"
    matrixUserId = $managerEvent.sender
    roomId = $team.teamRoomID
    eventId = $managerEvent.event_id
    originServerTimestamp = $managerEvent.origin_server_ts
}

$finalRequirements = @(
    [ordered]@{
        phase = "ROLLBACK_EXECUTED"
        agentName = "agentloom-implementer"
        sender = $implementer.matrixUserID
        marker = $executedMarker
    },
    [ordered]@{
        phase = "ROLLBACK_VERIFIED"
        agentName = "agentloom-verifier"
        sender = $verifier.matrixUserID
        marker = $verifiedMarker
    }
)
$finalEvents = Wait-StrictMarkers -RoomId $team.teamRoomID `
    -Requirements $finalRequirements -AuthToken $authToken `
    -StartedAtMilliseconds $managerEvent.origin_server_ts -Deadline $deadline
if (
    $finalEvents.ROLLBACK_EXECUTED.originServerTimestamp -le
        $managerEvent.origin_server_ts -or
    $finalEvents.ROLLBACK_VERIFIED.originServerTimestamp -le
        $finalEvents.ROLLBACK_EXECUTED.originServerTimestamp
) {
    throw "Rollback role events are not strictly chronological."
}

$roleEvents = @(
    $failureEvent,
    $managerEvidence,
    $finalEvents.ROLLBACK_EXECUTED,
    $finalEvents.ROLLBACK_VERIFIED
)
$submission = [ordered]@{
    schemaVersion = "agentloom.live-rollback-submission/v1alpha1"
    taskId = $TaskId
    caseId = "pagination-boundary"
    provider = $Provider
    model = $Model
    failedPatch = $failedPatch
    failedPatchSha256 = $failedPatchSha256
    rollbackPlan = [ordered]@{
        strategy = "RESTORE_APPROVED_SNAPSHOT"
        allowedChangedPaths = @("lib/pagination.py")
        reason = "Verifier rejected the candidate; restore the last approved snapshot."
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
