[CmdletBinding()]
param(
    [ValidatePattern("^[A-Za-z0-9._-]+$")]
    [string]$TaskId = ("AL-E2E-" + [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmss")),
    [string]$ControllerContainer = "hiclaw-controller",
    [string]$ManagerContainer = "hiclaw-manager",
    [string]$MatrixBaseUrl = "http://127.0.0.1:18080",
    [int]$TimeoutSeconds = 600,
    [int]$PollSeconds = 5,
    [string]$EvidencePath = ""
)

$ErrorActionPreference = "Stop"

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

function Invoke-Matrix {
    param(
        [Parameter(Mandatory)][ValidateSet("Get", "Post", "Put")][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [string]$authToken = "",
        [object]$Body
    )

    $arguments = @{
        Method = $Method
        Uri = "$MatrixBaseUrl$Path"
        TimeoutSec = 20
    }
    if (-not [string]::IsNullOrWhiteSpace($authToken)) {
        $arguments.Headers = @{ Authorization = "Bearer $authToken" }
    }
    if ($null -ne $Body) {
        $arguments.ContentType = "application/json"
        $arguments.Body = $Body | ConvertTo-Json -Depth 10
    }
    return Invoke-RestMethod @arguments
}

function Send-MatrixText {
    param(
        [Parameter(Mandatory)][string]$RoomId,
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$MentionUserId,
        [Parameter(Mandatory)][string]$authToken
    )

    $roomSegment = [uri]::EscapeDataString($RoomId)
    $transactionId = [guid]::NewGuid().ToString("N")
    $body = @{
        msgtype = "m.text"
        body = $Text
        "m.mentions" = @{ user_ids = @($MentionUserId) }
    }
    $null = Invoke-Matrix -Method Put `
        -Path "/_matrix/client/v3/rooms/$roomSegment/send/m.room.message/$transactionId" `
        -authToken $authToken -Body $body
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
        $event.origin_server_ts -lt $StartedAtMilliseconds
    ) {
        return $false
    }
    if ($event.type -ne "m.room.message" -or $event.content.msgtype -ne "m.text") {
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
        [Parameter(Mandatory)][string]$authToken,
        [Parameter(Mandatory)][long]$StartedAtMilliseconds
    )

    $found = @{}
    foreach ($roomId in $RoomIds) {
        $roomSegment = [uri]::EscapeDataString($roomId)
        try {
            $feed = Invoke-Matrix -Method Get `
                -Path "/_matrix/client/v3/rooms/$roomSegment/messages?dir=b&limit=100" `
                -authToken $authToken -Body $null
        }
        catch {
            continue
        }
        foreach ($event in @($feed.chunk)) {
            foreach ($requirement in $Requirements) {
                if (
                    -not $found.ContainsKey($requirement.key) -and
                    (Test-ExactMarker -event $event `
                        -ExpectedSender $requirement.sender `
                        -Marker $requirement.marker `
                        -StartedAtMilliseconds $StartedAtMilliseconds)
                ) {
                    $found[$requirement.key] = [ordered]@{
                        key = $requirement.key
                        sender = $event.sender
                        marker = $requirement.marker
                        eventId = $event.event_id
                        roomId = $roomId
                        originServerTimestamp = $event.origin_server_ts
                    }
                }
            }
        }
    }
    return $found
}

function Save-Evidence {
    param(
        [Parameter(Mandatory)][string]$Status,
        [Parameter(Mandatory)][hashtable]$Markers,
        [Parameter(Mandatory)][bool]$FollowUpSent
    )

    $orderedMarkers = @()
    foreach ($key in @("implementer", "verifier", "investigator", "manager", "pass")) {
        if ($Markers.ContainsKey($key)) {
            $orderedMarkers += $Markers[$key]
        }
    }
    $evidence = [ordered]@{
        taskId = $TaskId
        startedAt = $startedAt.ToString("o")
        verifiedAt = [DateTimeOffset]::UtcNow.ToString("o")
        status = $Status
        strict = $true
        followUpSent = $FollowUpSent
        criteria = [ordered]@{
            senderMustMatchRole = $true
            markerMustBeIndependentTrimmedLine = $true
        }
        markers = $orderedMarkers
    }
    $json = $evidence | ConvertTo-Json -Depth 10
    if (-not [string]::IsNullOrWhiteSpace($EvidencePath)) {
        $resolved = [IO.Path]::GetFullPath($EvidencePath)
        $directory = Split-Path -Parent $resolved
        if ($directory) {
            [void](New-Item -ItemType Directory -Force -Path $directory)
        }
        [IO.File]::WriteAllText(
            $resolved,
            $json,
            [Text.UTF8Encoding]::new($false)
        )
    }
    return $json
}

$manager = Get-HiclawJson -Arguments @("get", "managers", "default")
$workers = Get-HiclawJson -Arguments @(
    "get", "workers", "--team", "agentloom-repair"
)
$investigator = $workers.workers |
    Where-Object { $_.name -eq "agentloom-investigator" }
$implementer = $workers.workers |
    Where-Object { $_.name -eq "agentloom-implementer" }
$verifier = $workers.workers |
    Where-Object { $_.name -eq "agentloom-verifier" }
if ($null -in @($investigator, $implementer, $verifier)) {
    throw "Expected AgentLoom team identities are not available"
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
    throw "Matrix admin credentials are unavailable"
}
$matrixDomain = $manager.matrixUserID.Split(":", 2)[1]
$adminMatrixUserId = "@$adminUser`:$matrixDomain"
$login = Invoke-Matrix -Method Post -Path "/_matrix/client/v3/login" -Body @{
    type = "m.login.password"
    identifier = @{ type = "m.id.user"; user = $adminMatrixUserId }
    password = $adminPassword
}
$authToken = $login.access_token
if ([string]::IsNullOrWhiteSpace($authToken)) {
    throw "Matrix login did not return a token"
}

$joinedRooms = Invoke-Matrix -Method Get `
    -Path "/_matrix/client/v3/joined_rooms" -authToken $authToken -Body $null
$roomIds = @($joinedRooms.joined_rooms)

$requirements = @(
    [ordered]@{
        key = "implementer"
        sender = $implementer.matrixUserID
        marker = "[$TaskId] IMPLEMENTER_DONE"
    },
    [ordered]@{
        key = "verifier"
        sender = $verifier.matrixUserID
        marker = "[$TaskId] VERIFIER_DONE"
    },
    [ordered]@{
        key = "investigator"
        sender = $investigator.matrixUserID
        marker = "[$TaskId] INVESTIGATOR_DONE"
    },
    [ordered]@{
        key = "manager"
        sender = $manager.matrixUserID
        marker = "[$TaskId] MANAGER_DONE"
    },
    [ordered]@{
        key = "pass"
        sender = $manager.matrixUserID
        marker = "[$TaskId] E2E_PASS"
    }
)

$prompt = @"
$($manager.matrixUserID) [$TaskId] Run a strict AgentTeams runtime E2E using the team-management workflow. Delegate only to agentloom-investigator. The Leader must actually message agentloom-implementer and agentloom-verifier. Each identity must send its own task-prefixed marker: IMPLEMENTER_DONE, VERIFIER_DONE, and INVESTIGATOR_DONE. Send MANAGER_DONE and E2E_PASS only after receiving the Leader report backed by both Worker events. Never fabricate another identity's marker. No host or repository access is needed.
"@.Trim()
$startedAt = [DateTimeOffset]::UtcNow
$startedAtMilliseconds = $startedAt.ToUnixTimeMilliseconds()
Send-MatrixText -RoomId $manager.roomID -Text $prompt `
    -MentionUserId $manager.matrixUserID -authToken $authToken

$deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
$followUpSent = $false
$lastMarkers = @{}
while ([DateTimeOffset]::UtcNow -lt $deadline) {
    $lastMarkers = Find-StrictMarkers -RoomIds $roomIds `
        -Requirements $requirements -authToken $authToken `
        -StartedAtMilliseconds $startedAtMilliseconds
    if ($lastMarkers.Count -eq $requirements.Count) {
        Save-Evidence -Status "PASS" -Markers $lastMarkers `
            -FollowUpSent $followUpSent
        exit 0
    }

    $workersDone = (
        $lastMarkers.ContainsKey("implementer") -and
        $lastMarkers.ContainsKey("verifier")
    )
    if (
        $workersDone -and
        -not $lastMarkers.ContainsKey("investigator") -and
        -not $followUpSent
    ) {
        $followUp = @"
$($manager.matrixUserID) [$TaskId] Both Worker role-owned markers exist, but the Leader has not reported INVESTIGATOR_DONE in the Leader Room. Do not finalize. Remind agentloom-investigator to send exactly [$TaskId] INVESTIGATOR_DONE to you. After receiving it, send exactly two lines: [$TaskId] MANAGER_DONE and [$TaskId] E2E_PASS.
"@.Trim()
        Send-MatrixText -RoomId $manager.roomID -Text $followUp `
            -MentionUserId $manager.matrixUserID -authToken $authToken
        $followUpSent = $true
    }
    Start-Sleep -Seconds $PollSeconds
}

Save-Evidence -Status "TIMEOUT" -Markers $lastMarkers `
    -FollowUpSent $followUpSent
throw "AgentTeams strict E2E timed out after $TimeoutSeconds seconds"
