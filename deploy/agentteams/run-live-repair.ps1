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
    [ValidateRange(1, 3600)]
    [int]$TimeoutSeconds = 1800,
    [ValidateRange(1, 60)]
    [int]$PollSeconds = 10,
    [Parameter(Mandatory)][string]$CaseRoot,
    [ValidateSet("dashscope", "deepseek", "stepfun", "minimax-cn")]
    [string]$Provider = "minimax-cn",
    [ValidateSet("qwen3.7-plus", "deepseek-v4-pro", "step-3.7-flash", "MiniMax-M2.5")]
    [string]$Model = "MiniMax-M2.5",
    [string]$SubmissionPath = "",
    [string]$EvidencePath = "",
    [switch]$Resume,
    [string]$ResumeEvidencePath = ""
)

$ErrorActionPreference = "Stop"
$MaxArtifactBytes = 131072
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$providerModels = @{
    dashscope = "qwen3.7-plus"
    deepseek = "deepseek-v4-pro"
    stepfun = "step-3.7-flash"
    "minimax-cn" = "MiniMax-M2.5"
}
if ($providerModels[$Provider] -ne $Model) {
    throw "Provider and model are not an approved live repair pair"
}
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    throw "AgentLoom Python runtime is unavailable"
}

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
        [AllowEmptyString()][string]$MentionUserId = "",
        [Parameter(Mandatory)][string]$AuthToken
    )

    $roomSegment = [uri]::EscapeDataString($RoomId)
    $transactionId = [guid]::NewGuid().ToString("N")
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

function New-CoPawSendCommand {
    param(
        [Parameter(Mandatory)][string]$RoomId,
        [Parameter(Mandatory)][string]$UserId,
        [Parameter(Mandatory)][string]$Text
    )

    $textBase64 = [Convert]::ToBase64String(
        [Text.Encoding]::UTF8.GetBytes($Text)
    )
    return @"
copaw channels send \
  --agent-id default \
  --channel matrix \
  --target-session "$RoomId" \
  --target-user "$UserId" \
  --text "`$(printf '%s' '$textBase64' | base64 -d)"
"@.Trim()
}

function New-CoPawSendObjectCommand {
    param(
        [Parameter(Mandatory)][string]$RoomId,
        [Parameter(Mandatory)][string]$UserId,
        [Parameter(Mandatory)]
        [ValidatePattern("^[A-Za-z0-9][A-Za-z0-9._/-]{0,511}$")]
        [string]$ObjectPath
    )

    return @"
copaw channels send \
  --agent-id default \
  --channel matrix \
  --target-session "$RoomId" \
  --target-user "$UserId" \
  --text "`$(mc cat '$ObjectPath')"
"@.Trim()
}

function Test-ExactMarker {
    param(
        [Parameter(Mandatory)]$event,
        [Parameter(Mandatory)][string]$ExpectedSender,
        [Parameter(Mandatory)][string]$Marker,
        [string]$ExpectedMentionUserId = "",
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
    if (-not ($lines -contains $Marker)) {
        return $false
    }
    if (
        -not [string]::IsNullOrWhiteSpace($ExpectedMentionUserId) -and
        -not ($event.content."m.mentions".user_ids -contains $ExpectedMentionUserId)
    ) {
        return $false
    }
    return $true
}

function Find-StrictMarkers {
    param(
        [Parameter(Mandatory)][string[]]$RoomIds,
        [Parameter(Mandatory)][object[]]$Requirements,
        [Parameter(Mandatory)][string]$AuthToken,
        [Parameter(Mandatory)][long]$StartedAtMilliseconds
    )

    $found = @{}
    foreach ($RoomId in $RoomIds) {
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
                        -not $found.ContainsKey($requirement.key) -and
                        (Test-ExactMarker -event $event `
                            -ExpectedSender $requirement.sender `
                            -Marker $requirement.marker `
                            -ExpectedMentionUserId $requirement.mentionedUserId `
                            -StartedAtMilliseconds $StartedAtMilliseconds)
                    ) {
                        $found[$requirement.key] = [ordered]@{
                            key = $requirement.key
                            phase = $requirement.phase
                            agentName = $requirement.agentName
                            sender = $event.sender
                            mentionedAgent = $requirement.mentionedAgent
                            mentionedUserId = $requirement.mentionedUserId
                            eventId = $event.event_id
                            roomId = $RoomId
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
    }
    return $found
}

function Get-TaskObjects {
    param([Parameter(Mandatory)][string]$TaskPrefix)

    $lines = @(Invoke-Docker -Arguments @(
        "exec", $ControllerContainer, "mc", "ls", "--recursive", "--json",
        "hiclaw/$TaskPrefix"
    ))
    $objects = @()
    foreach ($line in $lines) {
        if (-not [string]::IsNullOrWhiteSpace([string]$line)) {
            $objects += ([string]$line | ConvertFrom-Json)
        }
    }
    return $objects
}

function Copy-TaskObject {
    param(
        [Parameter(Mandatory)][string]$TaskPrefix,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][string]$ContainerTempRoot
    )

    $containerPath = "$ContainerTempRoot/$Name"
    try {
        $null = Invoke-Docker -Arguments @(
            "exec", $ControllerContainer, "mc", "cp",
            "hiclaw/$TaskPrefix$Name", $containerPath
        )
        $null = Invoke-Docker -Arguments @(
            "cp", "$ControllerContainer`:$containerPath", $Destination
        )
    }
    finally {
        try {
            $null = Invoke-Docker -Arguments @(
                "exec", $ControllerContainer, "rm", "-f", $containerPath
            )
        }
        catch {
        }
    }
}

function Stage-LiveRepairCase {
    param(
        [Parameter(Mandatory)][string]$TaskPrefix,
        [Parameter(Mandatory)][string]$SourceRoot,
        [Parameter(Mandatory)]$CaseContext
    )

    $resolvedCaseRoot = [IO.Path]::GetFullPath($SourceRoot)
    $sourceFiles = @($CaseContext.sourceFiles | ForEach-Object {
        [ordered]@{
            objectName = [string]$_.objectName
            sourcePath = Join-Path $resolvedCaseRoot (
                "before/" + [string]$_.sourcePath
            )
            sha256 = [string]$_.sha256
            sizeBytes = [int64]$_.sizeBytes
        }
    })
    foreach ($source in $sourceFiles) {
        if (-not (Test-Path -LiteralPath $source.sourcePath -PathType Leaf)) {
            throw "Live repair Case input is missing: $($source.sourcePath)"
        }
        $item = Get-Item -LiteralPath $source.sourcePath
        $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $source.sourcePath).Hash
        if (
            [int64]$item.Length -ne $source.sizeBytes -or
            $actualHash -ne $source.sha256
        ) {
            throw "Live repair Case input changed after validation"
        }
    }

    $specTemp = [IO.Path]::GetTempFileName()
    $containerTempRoot = "/tmp/agentloom-stage-$TaskId-$([guid]::NewGuid().ToString('N'))"
    $containerFiles = @()
    try {
        $spec = [string]$CaseContext.spec
        [IO.File]::WriteAllText(
            $specTemp,
            $spec,
            [Text.UTF8Encoding]::new($false)
        )
        $sourceFiles += [ordered]@{
            objectName = "spec.md"
            sourcePath = $specTemp
        }

        $null = Invoke-Docker -Arguments @(
            "exec", $ControllerContainer, "mkdir", "-p", $containerTempRoot
        )
        foreach ($source in $sourceFiles) {
            $containerPath = "$containerTempRoot/$([guid]::NewGuid().ToString('N'))"
            $containerFiles += $containerPath
            $null = Invoke-Docker -Arguments @(
                "cp", [string]$source.sourcePath,
                "$ControllerContainer`:$containerPath"
            )
            $null = Invoke-Docker -Arguments @(
                "exec", $ControllerContainer, "mc", "cp", $containerPath,
                "hiclaw/$TaskPrefix$($source.objectName)"
            )
        }
    }
    finally {
        if (Test-Path -LiteralPath $specTemp -PathType Leaf) {
            Remove-Item -LiteralPath $specTemp -Force
        }
        foreach ($containerFile in $containerFiles) {
            try {
                $null = Invoke-Docker -Arguments @(
                    "exec", $ControllerContainer, "rm", "-f", $containerFile
                )
            }
            catch {
            }
        }
        try {
            $null = Invoke-Docker -Arguments @(
                "exec", $ControllerContainer, "rmdir", $containerTempRoot
            )
        }
        catch {
        }
    }
}

function Add-EvidenceRef {
    param(
        [Parameter(Mandatory)]$Artifact,
        [Parameter(Mandatory)][string]$PropertyName,
        [Parameter(Mandatory)][string]$EventId
    )

    $refs = @($Artifact.$PropertyName)
    if ($refs -notcontains $EventId) {
        $Artifact.$PropertyName = @($refs + $EventId)
    }
}

function Assert-TaskId {
    param(
        [Parameter(Mandatory)]$Artifact,
        [Parameter(Mandatory)][string]$PropertyName,
        [Parameter(Mandatory)][string]$ArtifactName
    )

    if ([string]$Artifact.$PropertyName -ne $TaskId) {
        throw "$ArtifactName task ID does not match $TaskId"
    }
}

function New-CoordinationTrace {
    param([Parameter(Mandatory)][hashtable]$Markers)

    $events = @()
    foreach ($key in @(
        "manager-delegated",
        "implementer-assigned",
        "verifier-assigned"
    )) {
        if ($Markers.ContainsKey($key)) {
            $marker = $Markers[$key]
            $events += [ordered]@{
                phase = $marker.phase
                agentName = $marker.agentName
                matrixUserId = $marker.sender
                mentionedAgent = $marker.mentionedAgent
                mentionedUserId = $marker.mentionedUserId
                roomId = $marker.roomId
                eventId = $marker.eventId
                originServerTimestamp = $marker.originServerTimestamp
            }
        }
    }
    return [ordered]@{
        schemaVersion = "agentloom.coordination-trace/v1alpha1"
        taskId = $TaskId
        events = $events
    }
}

function Save-RunEvidence {
    param(
        [Parameter(Mandatory)][string]$Status,
        [Parameter(Mandatory)][hashtable]$Markers,
        [object[]]$Objects = @(),
        [string]$SubmissionSha256 = "",
        [object[]]$InputObjects = @()
    )

    $eventEvidence = @()
    foreach ($key in @("investigator", "implementer", "verifier")) {
        if ($Markers.ContainsKey($key)) {
            $marker = $Markers[$key]
            $eventEvidence += [ordered]@{
                key = $marker.key
                agentName = $marker.agentName
                sender = $marker.sender
                eventId = $marker.eventId
                roomId = $marker.roomId
                originServerTimestamp = $marker.originServerTimestamp
            }
        }
    }
    $objectEvidence = @($Objects | ForEach-Object {
        [ordered]@{
            name = $_.key
            size = $_.size
            lastModified = $_.lastModified
            etag = $_.etag
        }
    })
    $inputEvidence = @($InputObjects | ForEach-Object {
        [ordered]@{
            name = $_.key
            size = $_.size
            etag = $_.etag
        }
    })
    $evidence = [ordered]@{
        schemaVersion = "agentloom.live-repair-run/v1alpha1"
        taskId = $TaskId
        caseId = $caseContext.caseId
        caseFingerprint = $caseContext.caseFingerprint
        provider = $Provider
        model = $Model
        startedAt = $startedAt.ToString("o")
        verifiedAt = [DateTimeOffset]::UtcNow.ToString("o")
        status = $Status
        strict = $true
        criteria = [ordered]@{
            senderMustMatchRole = $true
            eventMustFollowTaskStart = $true
            markerMustBeIndependentTrimmedLine = $true
            resultObjectsMustFollowTaskStart = $true
            hiddenAndExpectedObjectsForbidden = $true
            resultObjectsMustBeAllowlisted = $true
            inputObjectsRemainUnchanged = $true
            completionEventMustFollowArtifacts = $true
            coordinationEventsMustMatchMentions = $true
        }
        inputObjects = $inputEvidence
        coordinationTrace = New-CoordinationTrace -Markers $Markers
        roleEvents = $eventEvidence
        objects = $objectEvidence
        submissionSha256 = $SubmissionSha256
    }
    $json = $evidence | ConvertTo-Json -Depth 20
    if (-not [string]::IsNullOrWhiteSpace($EvidencePath)) {
        $resolved = [IO.Path]::GetFullPath($EvidencePath)
        $directory = Split-Path -Parent $resolved
        if ($directory) {
            [void](New-Item -ItemType Directory -Force -Path $directory)
        }
        [IO.File]::WriteAllText($resolved, $json, [Text.UTF8Encoding]::new($false))
    }
    return $json
}

$resolvedCaseRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot $CaseRoot))
if ([IO.Path]::IsPathRooted($CaseRoot)) {
    $resolvedCaseRoot = [IO.Path]::GetFullPath($CaseRoot)
}
if (-not (Test-Path -LiteralPath $resolvedCaseRoot -PathType Container)) {
    throw "Live repair Case root is unavailable"
}
$caseContextPath = Join-Path ([IO.Path]::GetTempPath()) (
    "agentloom-live-case-" + [Guid]::NewGuid().ToString("N") + ".json"
)
try {
    & $venvPython @(
        "-m", "agentloom.live_repair", "prepare-case",
        "--case-root", $resolvedCaseRoot,
        "--output", $caseContextPath
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Live repair Case validation failed"
    }
    $caseContext = Get-Content -Raw -LiteralPath $caseContextPath |
        ConvertFrom-Json
}
finally {
    if (Test-Path -LiteralPath $caseContextPath -PathType Leaf) {
        Remove-Item -LiteralPath $caseContextPath -Force
    }
}

function Stage-AssignmentObject {
    param(
        [Parameter(Mandatory)][string]$TaskPrefix,
        [Parameter(Mandatory)]
        [ValidateSet("assignments/implementer.txt", "assignments/verifier.txt")]
        [string]$ObjectName,
        [Parameter(Mandatory)][string]$Text
    )

    $hostTemp = [IO.Path]::GetTempFileName()
    $containerTemp = "/tmp/agentloom-assignment-$([guid]::NewGuid().ToString('N'))"
    try {
        [IO.File]::WriteAllText(
            $hostTemp,
            $Text,
            [Text.UTF8Encoding]::new($false)
        )
        $null = Invoke-Docker -Arguments @(
            "cp", $hostTemp, "$ControllerContainer`:$containerTemp"
        )
        $null = Invoke-Docker -Arguments @(
            "exec", $ControllerContainer, "mc", "cp", $containerTemp,
            "hiclaw/$TaskPrefix$ObjectName"
        )
    }
    finally {
        if (Test-Path -LiteralPath $hostTemp -PathType Leaf) {
            Remove-Item -LiteralPath $hostTemp -Force
        }
        try {
            $null = Invoke-Docker -Arguments @(
                "exec", $ControllerContainer, "rm", "-f", $containerTemp
            )
        }
        catch {
        }
    }
}
if (@($caseContext.allowedChangedPaths).Count -ne 1) {
    throw "The initial live repair runner requires exactly one changed path"
}
$changedPath = [string]$caseContext.allowedChangedPaths[0]
$workingDirectory = [string]$caseContext.workingDirectory
$testShellCommand = [string]$caseContext.testShellCommand
$staticCheckShellCommand = [string]$caseContext.staticCheckShellCommand

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
    throw "Expected AgentLoom business Agent identities are unavailable"
}
if ($team.phase -ne "Active" -or -not $team.leaderReady) {
    throw "AgentLoom Team is not ready"
}
$roomIds = @(
    $manager.roomID,
    $investigator.roomID,
    $team.teamRoomID
)

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

$taskPrefix = "hiclaw-storage/teams/$TeamName/shared/tasks/$TaskId/"
$startedAt = [DateTimeOffset]::UtcNow
if ($Resume) {
    if ([string]::IsNullOrWhiteSpace($ResumeEvidencePath)) {
        throw "ResumeEvidencePath is required with -Resume"
    }
    try {
        $resolvedResumeEvidence = [IO.Path]::GetFullPath($ResumeEvidencePath)
        $resumeEvidenceFile = Get-Item -LiteralPath $resolvedResumeEvidence
        if ($resumeEvidenceFile.Length -gt 1MB) {
            throw "resume evidence exceeds 1 MiB"
        }
        $resumeEvidence = Get-Content -Raw -LiteralPath $resolvedResumeEvidence |
            ConvertFrom-Json
    }
    catch {
        throw "ResumeEvidencePath is not valid live repair evidence"
    }
    if (
        $resumeEvidence.schemaVersion -ne "agentloom.live-repair-run/v1alpha1" -or
        $resumeEvidence.taskId -ne $TaskId -or
        -not $resumeEvidence.strict -or
        @("REJECTED", "TIMEOUT") -notcontains $resumeEvidence.status
    ) {
        throw "Resume evidence does not authorize this task continuation"
    }
    try {
        $startedAt = ([DateTimeOffset]$resumeEvidence.startedAt).ToUniversalTime()
    }
    catch {
        throw "Resume evidence does not contain a valid startedAt"
    }
}
$requirements = @(
    [ordered]@{
        key = "manager-delegated"
        phase = "MANAGER_DELEGATED"
        agentName = "agentloom-manager"
        sender = $manager.matrixUserID
        marker = "[$TaskId] MANAGER_DELEGATED"
        mentionedAgent = "agentloom-investigator"
        mentionedUserId = $investigator.matrixUserID
    },
    [ordered]@{
        key = "investigator"
        agentName = "agentloom-investigator"
        sender = $investigator.matrixUserID
        marker = "[$TaskId] ROOT_CAUSE_REPORT"
        mentionedUserId = ""
    },
    [ordered]@{
        key = "implementer-assigned"
        phase = "IMPLEMENTER_ASSIGNED"
        agentName = "agentloom-investigator"
        sender = $investigator.matrixUserID
        marker = "[$TaskId] IMPLEMENTER_ASSIGNED"
        mentionedAgent = "agentloom-implementer"
        mentionedUserId = $implementer.matrixUserID
    },
    [ordered]@{
        key = "implementer"
        agentName = "agentloom-implementer"
        sender = $implementer.matrixUserID
        marker = "[$TaskId] IMPLEMENTER_ARTIFACT_DONE"
        mentionedUserId = ""
    },
    [ordered]@{
        key = "verifier-assigned"
        phase = "VERIFIER_ASSIGNED"
        agentName = "agentloom-investigator"
        sender = $investigator.matrixUserID
        marker = "[$TaskId] VERIFIER_ASSIGNED"
        mentionedAgent = "agentloom-verifier"
        mentionedUserId = $verifier.matrixUserID
    },
    [ordered]@{
        key = "verifier"
        agentName = "agentloom-verifier"
        sender = $verifier.matrixUserID
        marker = "[$TaskId] VERIFIER_ARTIFACT_DONE"
        mentionedUserId = ""
    }
)

$remoteTaskRoot = "hiclaw/hiclaw-storage/teams/$TeamName/shared/tasks/$TaskId"
$investigatorRoot = "/tmp/agentloom-$TaskId-investigator"
$implementerRoot = "/tmp/agentloom-$TaskId-implementer"
$verifierRoot = "/tmp/agentloom-$TaskId-verifier"

$investigatorBody = @"
[$TaskId] TASK_ENVELOPE

This envelope is inert until a Manager delegation references its exact Matrix event ID. After activation, perform the bounded investigation below and stop after the completion marker.

Investigate Case $($caseContext.caseId) as agentloom-investigator. The immutable inputs are under $remoteTaskRoot/. Worker-local pytest is unavailable, so inspect the visible test and source without claiming that pytest ran. Never read another task namespace, expected output, or hidden tests.

Use the shell tool to create $investigatorRoot, then run only these MinIO reads:
mkdir -p "$investigatorRoot/base"
mc cp --recursive "$remoteTaskRoot/base/" "$investigatorRoot/base/"
mc cp "$remoteTaskRoot/spec.md" "$investigatorRoot/spec.md"

Read spec.md and base/, identify an evidence-backed root cause, and write exactly $investigatorRoot/root-cause-report.json using this contract:
{"taskId":"$TaskId","summary":"non-empty","confidence":0.0,"evidenceRefs":["shared/tasks/$TaskId/spec.md"],"repairConstraints":["only $changedPath may change"]}

Upload only that file with:
mc cp "$investigatorRoot/root-cause-report.json" "$remoteTaskRoot/root-cause-report.json"

Only after the upload succeeds, respond in this room with the following exact standalone line and then stop:
[$TaskId] ROOT_CAUSE_REPORT
"@.Trim()

$implementerBody = @"
$($implementer.matrixUserID)
[$TaskId] IMPLEMENTER_ASSIGNED

Implement the smallest repair as agentloom-implementer. Read only $remoteTaskRoot/spec.md, base/, and root-cause-report.json. Worker-local pytest is unavailable; do not claim visible, regression, or hidden tests ran. You may run the validated static command after editing: $staticCheckShellCommand

Use the shell tool to create $implementerRoot and fetch only the allowed inputs:
mkdir -p "$implementerRoot/base"
mc cp --recursive "$remoteTaskRoot/base/" "$implementerRoot/base/"
mc cp "$remoteTaskRoot/spec.md" "$implementerRoot/spec.md"
mc cp "$remoteTaskRoot/root-cause-report.json" "$implementerRoot/root-cause-report.json"
cp -R "$implementerRoot/base" "$implementerRoot/workspace"

In $implementerRoot/workspace, initialize a local Git baseline with `git init -q`, `git add .`, and `git -c user.name=AgentLoom -c user.email=agentloom@example.invalid commit -qm baseline`; change only $changedPath and run $staticCheckShellCommand. Then generate the patch only with these commands:
git diff --check
git diff --no-ext-diff -- "$changedPath" > "$implementerRoot/repair.patch"
test -s "$implementerRoot/repair.patch"

Do not hand-write unified diff hunk headers. Compute the generated patch's lowercase SHA-256 and write $implementerRoot/patch-artifact.json using this contract:
{"taskId":"$TaskId","patchUri":"artifact://$TaskId/repair.patch","sha256":"64 lowercase hex","changedPaths":["$changedPath"],"evidenceRefs":["shared/tasks/$TaskId/repair.patch"]}

Upload exactly these two files:
mc cp "$implementerRoot/repair.patch" "$remoteTaskRoot/repair.patch"
mc cp "$implementerRoot/patch-artifact.json" "$remoteTaskRoot/patch-artifact.json"

Only after both uploads succeed, respond in this Team Room with the following exact standalone line and then stop:
[$TaskId] IMPLEMENTER_ARTIFACT_DONE
"@.Trim()

$verifierBody = @"
$($verifier.matrixUserID)
[$TaskId] VERIFIER_ASSIGNED

Review the frozen patch independently as agentloom-verifier. Read only $remoteTaskRoot/spec.md, base/, repair.patch, and patch-artifact.json. Worker-local pytest is unavailable. Do not claim visible, regression, or hidden tests ran; those checks belong to the independent AgentLoom host verifier and final governed Docker ToolCall.

Use the shell tool to create $verifierRoot and fetch only those inputs:
mkdir -p "$verifierRoot/base"
mc cp --recursive "$remoteTaskRoot/base/" "$verifierRoot/base/"
mc cp "$remoteTaskRoot/spec.md" "$verifierRoot/spec.md"
mc cp "$remoteTaskRoot/repair.patch" "$verifierRoot/repair.patch"
mc cp "$remoteTaskRoot/patch-artifact.json" "$verifierRoot/patch-artifact.json"
cp -R "$verifierRoot/base" "$verifierRoot/verifier-workspace"

In the clean verifier-workspace, initialize a local Git baseline with `git init -q`, `git add .`, and `git -c user.name=AgentLoom -c user.email=agentloom@example.invalid commit -qm baseline`; use git apply --check before applying $verifierRoot/repair.patch, apply it, verify only $changedPath changed, and run $staticCheckShellCommand. If any available check fails, report failure without the completion marker. Otherwise write these exact bounded outcomes using the patch SHA-256 from patch-artifact.json:
verification-result.json: {"schema_version":"agentloom.verification/v1alpha1","task_id":"$TaskId","patch_hash":"same 64 lowercase hex","verdict":"UNCERTAIN","checks":{"original_failure_reproduced":false,"target_tests_passed":false,"regression_tests_passed":false,"static_checks_passed":true,"unauthorized_changes":false},"evidence_refs":["shared/tasks/$TaskId/repair.patch"],"reason":"Worker-local pytest is unavailable; static review passed and host verification is required.","verifier_agent":"agentloom-verifier"}
risk-report.json: {"taskId":"$TaskId","riskLevel":"L1","verdict":"PASSED","findings":[],"evidenceRefs":["shared/tasks/$TaskId/repair.patch"]}

Upload exactly these two files:
mc cp "$verifierRoot/verification-result.json" "$remoteTaskRoot/verification-result.json"
mc cp "$verifierRoot/risk-report.json" "$remoteTaskRoot/risk-report.json"

Only after both uploads succeed, respond in this Team Room with the following exact standalone line and then stop:
[$TaskId] VERIFIER_ARTIFACT_DONE
"@.Trim()

$initialObjects = @()
$expectedInitial = @(
    @($caseContext.sourceFiles | ForEach-Object { [string]$_.objectName }) +
    @(
        "spec.md",
        "assignments/implementer.txt",
        "assignments/verifier.txt"
    )
)
if (-not $Resume) {
    $initialObjects = Get-TaskObjects -TaskPrefix $taskPrefix
    if ($initialObjects.Count -eq 0) {
        Stage-LiveRepairCase -TaskPrefix $taskPrefix `
            -SourceRoot $resolvedCaseRoot -CaseContext $caseContext
        Stage-AssignmentObject -TaskPrefix $taskPrefix `
            -ObjectName "assignments/implementer.txt" -Text $implementerBody
        Stage-AssignmentObject -TaskPrefix $taskPrefix `
            -ObjectName "assignments/verifier.txt" -Text $verifierBody
        $initialObjects = Get-TaskObjects -TaskPrefix $taskPrefix
    }
    $initialKeys = @($initialObjects | ForEach-Object { [string]$_.key })
    if ((Compare-Object $initialKeys $expectedInitial).Count -ne 0) {
        throw "Live repair task namespace is not clean"
    }
} else {
    if ($null -eq $resumeEvidence.inputObjects) {
        throw "Resume evidence lacks immutable input object fingerprints"
    }
    $initialObjects = @($resumeEvidence.inputObjects | ForEach-Object {
        [pscustomobject]@{
            key = $_.name
            size = $_.size
            etag = $_.etag
        }
    })
}
$initialInputObjects = @($initialObjects | Where-Object {
    $expectedInitial -contains [string]$_.key
})
if ($initialInputObjects.Count -ne $expectedInitial.Count) {
    throw "Immutable input object fingerprints are incomplete"
}

$verifierDispatchCommand = New-CoPawSendObjectCommand `
    -RoomId $team.teamRoomID `
    -UserId $verifier.matrixUserID `
    -ObjectPath "$remoteTaskRoot/assignments/verifier.txt"
$implementerDispatchCommand = New-CoPawSendObjectCommand `
    -RoomId $team.teamRoomID `
    -UserId $implementer.matrixUserID `
    -ObjectPath "$remoteTaskRoot/assignments/implementer.txt"

$managerDelegationBody = @"
$($investigator.matrixUserID)
[$TaskId] MANAGER_DELEGATED

Execute the referenced TASK_ENVELOPE now. The exact envelope event ID is:
ENVELOPE_EVENT_ID_PLACEHOLDER

Execute the bounded investigation and role handoff in that envelope exactly. Do not perform Implementer or Verifier duties yourself.
"@.Trim()

$startedAtMilliseconds = $startedAt.ToUnixTimeMilliseconds()
if (-not $Resume) {
    $taskEnvelopeEvent = Send-MatrixText -RoomId $investigator.roomID `
        -Text $investigatorBody -MentionUserId "" -AuthToken $authToken
    $managerDelegationBody = $managerDelegationBody.Replace(
        "ENVELOPE_EVENT_ID_PLACEHOLDER",
        [string]$taskEnvelopeEvent.eventId
    )
}
$managerDelegationCommand = New-CoPawSendCommand `
    -RoomId $investigator.roomID `
    -UserId $investigator.matrixUserID `
    -Text $managerDelegationBody

$prompt = @"
$($manager.matrixUserID) [$TaskId] Perform one bounded Manager-to-Investigator delegation for Case $($caseContext.caseId). The task envelope is already staged in the Investigator room. Do not inspect code, create task state, or contact any other Worker.

Use the shell tool exactly once to run this exact CoPaw dispatch command:
$managerDelegationCommand

After that command succeeds, stop. Do not copy the Investigator result, fabricate any completion marker, or retry with another room, task, or tool.
"@.Trim()

if (-not $Resume) {
    $null = Send-MatrixText -RoomId $manager.roomID -Text $prompt `
        -MentionUserId $manager.matrixUserID -AuthToken $authToken
}

$runDeadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
$markers = @{}

function Get-StageDeadline {
    param([ValidateRange(1, 3)][int]$RemainingStages)

    $now = [DateTimeOffset]::UtcNow
    $remainingSeconds = ($runDeadline - $now).TotalSeconds
    if ($remainingSeconds -le 0) {
        return $runDeadline
    }
    $stageSeconds = [Math]::Max(
        1,
        [Math]::Floor($remainingSeconds / $RemainingStages)
    )
    return $now.AddSeconds($stageSeconds)
}

function Wait-ForRequiredMarkers {
    param(
        [Parameter(Mandatory)][string[]]$RequiredKeys,
        [Parameter(Mandatory)][DateTimeOffset]$Deadline,
        [ValidateRange(0, 3600)][int]$ReminderAfterSeconds = 0,
        [scriptblock]$OnReminder = $null
    )

    $reminderSent = $false
    $reminderAt = [DateTimeOffset]::UtcNow.AddSeconds($ReminderAfterSeconds)
    while ([DateTimeOffset]::UtcNow -lt $Deadline) {
        $observed = Find-StrictMarkers -RoomIds $roomIds `
            -Requirements $requirements -AuthToken $authToken `
            -StartedAtMilliseconds $startedAtMilliseconds
        foreach ($key in $observed.Keys) {
            $markers[$key] = $observed[$key]
        }
        $missing = @($RequiredKeys | Where-Object { -not $markers.ContainsKey($_) })
        if ($missing.Count -eq 0) {
            return
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
}

function Stop-IfStageIncomplete {
    param(
        [Parameter(Mandatory)][string]$Stage,
        [Parameter(Mandatory)][string[]]$RequiredMarkerKeys,
        [Parameter(Mandatory)][string[]]$RequiredObjectNames
    )

    $objects = Get-TaskObjects -TaskPrefix $taskPrefix
    $missingMarkers = @($RequiredMarkerKeys | Where-Object {
        -not $markers.ContainsKey($_)
    })
    $keys = @($objects | ForEach-Object { [string]$_.key })
    $missingObjects = @($RequiredObjectNames | Where-Object { $_ -notin $keys })
    if ($missingMarkers.Count -ne 0 -or $missingObjects.Count -ne 0) {
        $status = if ($missingMarkers.Count -ne 0) { "TIMEOUT" } else { "REJECTED" }
        Save-RunEvidence -Status $status -Markers $markers -Objects $objects `
            -InputObjects $initialInputObjects
        throw "Live repair $Stage stage did not produce its required evidence"
    }
}

$investigatorCompletionBody = @"
$($investigator.matrixUserID) [$TaskId] Complete the accepted investigation. Confirm that root-cause-report.json is already uploaded. If it is absent, finish only the bounded investigation from the accepted task envelope and upload it. Then emit this exact standalone marker and stop:
[$TaskId] ROOT_CAUSE_REPORT
"@.Trim()
$investigatorCompletionDispatchCommand = New-CoPawSendCommand `
    -RoomId $investigator.roomID `
    -UserId $investigator.matrixUserID `
    -Text $investigatorCompletionBody
$investigatorManagerReminder = @"
$($manager.matrixUserID) [$TaskId] Reactivate only the accepted investigation completion. Use the shell tool exactly once to run this exact CoPaw dispatch command:
$investigatorCompletionDispatchCommand
After the command succeeds, stop. Do not inspect code or fabricate the Investigator marker.
"@.Trim()
$investigatorReminder = {
    Send-MatrixText -RoomId $manager.roomID -Text $investigatorManagerReminder `
        -MentionUserId $manager.matrixUserID -AuthToken $authToken
}
Wait-ForRequiredMarkers -RequiredKeys @("manager-delegated", "investigator") `
    -Deadline (Get-StageDeadline -RemainingStages 3) `
    -ReminderAfterSeconds 60 -OnReminder $investigatorReminder
Stop-IfStageIncomplete -Stage "investigation" `
    -RequiredMarkerKeys @("manager-delegated", "investigator") `
    -RequiredObjectNames @("root-cause-report.json")

$implementerInvestigatorPrompt = @"
$($investigator.matrixUserID) [$TaskId] Continue the accepted repair handoff. Run only the exact CoPaw dispatch command below with the shell tool:
$implementerDispatchCommand
After the command succeeds, stop. Do not implement the patch yourself.
"@.Trim()
$implementerInvestigatorDispatchCommand = New-CoPawSendCommand `
    -RoomId $investigator.roomID `
    -UserId $investigator.matrixUserID `
    -Text $implementerInvestigatorPrompt
$implementerManagerPrompt = @"
$($manager.matrixUserID) [$TaskId] Reactivate the accepted repair handoff through the Team Leader. Use the shell tool exactly once to run this exact CoPaw dispatch command:
$implementerInvestigatorDispatchCommand
After the command succeeds, stop. Do not investigate or implement the patch yourself.
"@.Trim()
if (-not $markers.ContainsKey("implementer-assigned")) {
    $null = Send-MatrixText -RoomId $manager.roomID -Text $implementerManagerPrompt `
        -MentionUserId $manager.matrixUserID -AuthToken $authToken
}
$implementerReminder = {
    if (-not $markers.ContainsKey("implementer-assigned")) {
        return Send-MatrixText -RoomId $manager.roomID `
            -Text $implementerManagerPrompt `
            -MentionUserId $manager.matrixUserID -AuthToken $authToken
    }
    $body = @"
$($implementer.matrixUserID) [$TaskId] Implementation reminder. Continue only the accepted bounded assignment. Upload the required repair.patch and patch-artifact.json before emitting this exact standalone marker:
[$TaskId] IMPLEMENTER_ARTIFACT_DONE
"@.Trim()
    Send-MatrixText -RoomId $team.teamRoomID -Text $body `
        -MentionUserId $implementer.matrixUserID -AuthToken $authToken
}
Wait-ForRequiredMarkers -RequiredKeys @(
    "implementer-assigned", "implementer"
) -Deadline (Get-StageDeadline -RemainingStages 2) `
    -ReminderAfterSeconds 60 -OnReminder $implementerReminder
Stop-IfStageIncomplete -Stage "implementation" `
    -RequiredMarkerKeys @("implementer-assigned", "implementer") `
    -RequiredObjectNames @("repair.patch", "patch-artifact.json")

$verifierInvestigatorPrompt = @"
$($investigator.matrixUserID) [$TaskId] The Implementer artifacts are frozen. Run only the exact CoPaw dispatch command below with the shell tool:
$verifierDispatchCommand
After the command succeeds, stop. Do not verify the patch yourself.
"@.Trim()
$verifierInvestigatorDispatchCommand = New-CoPawSendCommand `
    -RoomId $investigator.roomID `
    -UserId $investigator.matrixUserID `
    -Text $verifierInvestigatorPrompt
$verifierManagerPrompt = @"
$($manager.matrixUserID) [$TaskId] Reactivate the accepted independent review handoff through the Team Leader. Use the shell tool exactly once to run this exact CoPaw dispatch command:
$verifierInvestigatorDispatchCommand
After the command succeeds, stop. Do not inspect or verify the patch yourself.
"@.Trim()
if (-not $markers.ContainsKey("verifier-assigned")) {
    $null = Send-MatrixText -RoomId $manager.roomID -Text $verifierManagerPrompt `
        -MentionUserId $manager.matrixUserID -AuthToken $authToken
}
$verifierReminder = {
    if (-not $markers.ContainsKey("verifier-assigned")) {
        return Send-MatrixText -RoomId $manager.roomID `
            -Text $verifierManagerPrompt `
            -MentionUserId $manager.matrixUserID -AuthToken $authToken
    }
    $body = @"
$($verifier.matrixUserID) [$TaskId] Verification reminder. Continue only the accepted bounded review. Upload verification-result.json and risk-report.json before emitting this exact standalone marker:
[$TaskId] VERIFIER_ARTIFACT_DONE
"@.Trim()
    Send-MatrixText -RoomId $team.teamRoomID -Text $body `
        -MentionUserId $verifier.matrixUserID -AuthToken $authToken
}
Wait-ForRequiredMarkers -RequiredKeys @("verifier-assigned", "verifier") `
    -Deadline (Get-StageDeadline -RemainingStages 1) `
    -ReminderAfterSeconds 60 -OnReminder $verifierReminder
Stop-IfStageIncomplete -Stage "verification" `
    -RequiredMarkerKeys @("verifier-assigned", "verifier") `
    -RequiredObjectNames @("verification-result.json", "risk-report.json")

$objects = Get-TaskObjects -TaskPrefix $taskPrefix
$keys = @($objects | ForEach-Object { [string]$_.key })
if (@($keys | Where-Object { $_ -match "(^|/)(expected|hidden[^/]*)/" }).Count -ne 0) {
    Save-RunEvidence -Status "REJECTED" -Markers $markers -Objects $objects `
        -InputObjects $initialInputObjects
    throw "Live repair namespace contains forbidden expected or hidden objects"
}
$allowedFinalKeys = @($expectedInitial + @(
    "root-cause-report.json",
    "repair.patch",
    "patch-artifact.json",
    "verification-result.json",
    "risk-report.json"
))
if ((Compare-Object $keys $allowedFinalKeys).Count -ne 0) {
    Save-RunEvidence -Status "REJECTED" -Markers $markers -Objects $objects `
        -InputObjects $initialInputObjects
    throw "Live repair namespace contains non-allowlisted objects"
}
foreach ($immutableInput in $initialInputObjects) {
    $current = $objects | Where-Object { $_.key -eq $immutableInput.key }
    if (
        $null -eq $current -or
        [string]$current.etag -ne [string]$immutableInput.etag -or
        [int64]$current.size -ne [int64]$immutableInput.size
    ) {
        Save-RunEvidence -Status "REJECTED" -Markers $markers -Objects $objects `
            -InputObjects $initialInputObjects
        throw "Immutable live repair input object changed: $($immutableInput.key)"
    }
}
$requiredObjects = @(
    "root-cause-report.json",
    "repair.patch",
    "patch-artifact.json",
    "verification-result.json",
    "risk-report.json"
)
foreach ($name in $requiredObjects) {
    $object = $objects | Where-Object { $_.key -eq $name }
    if ($null -eq $object) {
        Save-RunEvidence -Status "REJECTED" -Markers $markers -Objects $objects `
            -InputObjects $initialInputObjects
        throw "Required live repair object is missing: $name"
    }
    if ([int64]$object.size -gt $MaxArtifactBytes) {
        Save-RunEvidence -Status "REJECTED" -Markers $markers -Objects $objects `
            -InputObjects $initialInputObjects
        throw "Live repair object exceeds 128 KiB: $name"
    }
    $lastModified = ([DateTimeOffset]$object.lastModified).ToUniversalTime()
    if ($lastModified -lt $startedAt) {
        Save-RunEvidence -Status "REJECTED" -Markers $markers -Objects $objects `
            -InputObjects $initialInputObjects
        throw "Live repair object predates the task start: $name"
    }
}
$artifactTimes = @{
    investigator = [DateTimeOffset]::MinValue
    implementer = [DateTimeOffset]::MinValue
    verifier = [DateTimeOffset]::MinValue
}
foreach ($name in @("root-cause-report.json")) {
    $artifactTimes.investigator = ([DateTimeOffset]($objects |
        Where-Object { $_.key -eq $name }).lastModified).ToUniversalTime()
}
foreach ($name in @("repair.patch", "patch-artifact.json")) {
    $time = ([DateTimeOffset]($objects |
        Where-Object { $_.key -eq $name }).lastModified).ToUniversalTime()
    if ($time -gt $artifactTimes.implementer) {
        $artifactTimes.implementer = $time
    }
}
foreach ($name in @("verification-result.json", "risk-report.json")) {
    $time = ([DateTimeOffset]($objects |
        Where-Object { $_.key -eq $name }).lastModified).ToUniversalTime()
    if ($time -gt $artifactTimes.verifier) {
        $artifactTimes.verifier = $time
    }
}
foreach ($key in @("investigator", "implementer", "verifier")) {
    $eventTime = [DateTimeOffset]::FromUnixTimeMilliseconds(
        [int64]$markers[$key].originServerTimestamp
    )
    if ($eventTime -lt $artifactTimes[$key]) {
        Save-RunEvidence -Status "REJECTED" -Markers $markers -Objects $objects `
            -InputObjects $initialInputObjects
        throw "Completion event predates its role artifacts: $key"
    }
}

if ([string]::IsNullOrWhiteSpace($SubmissionPath)) {
    $SubmissionPath = ".\artifacts\live-repair\$TaskId\submission.json"
}
$resolvedSubmission = [IO.Path]::GetFullPath($SubmissionPath)
$submissionDirectory = Split-Path -Parent $resolvedSubmission
[void](New-Item -ItemType Directory -Force -Path $submissionDirectory)
$rawArtifacts = Join-Path $submissionDirectory "raw-agent-artifacts"
if (Test-Path -LiteralPath $rawArtifacts) {
    throw "Raw Agent artifact directory already exists: $rawArtifacts"
}
[void](New-Item -ItemType Directory -Path $rawArtifacts)
$containerTempRoot = "/tmp/agentloom-live-$TaskId-$([guid]::NewGuid().ToString('N'))"
$null = Invoke-Docker -Arguments @(
    "exec", $ControllerContainer, "mkdir", "-p", $containerTempRoot
)
try {
    foreach ($name in $requiredObjects) {
        Copy-TaskObject -TaskPrefix $taskPrefix -Name $name `
            -Destination (Join-Path $rawArtifacts $name) `
            -ContainerTempRoot $containerTempRoot
    }
}
finally {
    try {
        $null = Invoke-Docker -Arguments @(
            "exec", $ControllerContainer, "rmdir", $containerTempRoot
        )
    }
    catch {
    }
}

$rootCause = Get-Content -Raw -LiteralPath `
    (Join-Path $rawArtifacts "root-cause-report.json") | ConvertFrom-Json
$patchArtifact = Get-Content -Raw -LiteralPath `
    (Join-Path $rawArtifacts "patch-artifact.json") | ConvertFrom-Json
$verification = Get-Content -Raw -LiteralPath `
    (Join-Path $rawArtifacts "verification-result.json") | ConvertFrom-Json
$risk = Get-Content -Raw -LiteralPath `
    (Join-Path $rawArtifacts "risk-report.json") | ConvertFrom-Json
Assert-TaskId -Artifact $rootCause -PropertyName "taskId" `
    -ArtifactName "RootCauseReport"
Assert-TaskId -Artifact $patchArtifact -PropertyName "taskId" `
    -ArtifactName "PatchArtifact"
Assert-TaskId -Artifact $verification -PropertyName "task_id" `
    -ArtifactName "VerificationResult"
Assert-TaskId -Artifact $risk -PropertyName "taskId" `
    -ArtifactName "RiskReport"

Add-EvidenceRef -Artifact $rootCause -PropertyName "evidenceRefs" `
    -EventId $markers.investigator.eventId
Add-EvidenceRef -Artifact $patchArtifact -PropertyName "evidenceRefs" `
    -EventId $markers.implementer.eventId
Add-EvidenceRef -Artifact $verification -PropertyName "evidence_refs" `
    -EventId $markers.verifier.eventId
Add-EvidenceRef -Artifact $risk -PropertyName "evidenceRefs" `
    -EventId $markers.verifier.eventId

$patchText = [IO.File]::ReadAllText(
    (Join-Path $rawArtifacts "repair.patch"),
    [Text.UTF8Encoding]::new($false, $true)
)
$submission = [ordered]@{
    schemaVersion = "agentloom.live-repair-submission/v1alpha1"
    taskId = $TaskId
    provider = $Provider
    model = $Model
    coordinationTrace = New-CoordinationTrace -Markers $markers
    roleEvents = @(
        [ordered]@{
            agentName = "agentloom-investigator"
            matrixUserId = $markers.investigator.sender
            roomId = $markers.investigator.roomId
            eventId = $markers.investigator.eventId
            originServerTimestamp = $markers.investigator.originServerTimestamp
        },
        [ordered]@{
            agentName = "agentloom-implementer"
            matrixUserId = $markers.implementer.sender
            roomId = $markers.implementer.roomId
            eventId = $markers.implementer.eventId
            originServerTimestamp = $markers.implementer.originServerTimestamp
        },
        [ordered]@{
            agentName = "agentloom-verifier"
            matrixUserId = $markers.verifier.sender
            roomId = $markers.verifier.roomId
            eventId = $markers.verifier.eventId
            originServerTimestamp = $markers.verifier.originServerTimestamp
        }
    )
    repairPatch = $patchText
    bundle = [ordered]@{
        rootCause = $rootCause
        patch = $patchArtifact
        verification = $verification
        risk = $risk
    }
}
$submissionJson = $submission | ConvertTo-Json -Depth 30
[IO.File]::WriteAllText(
    $resolvedSubmission,
    $submissionJson,
    [Text.UTF8Encoding]::new($false)
)
$submissionHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedSubmission).Hash.ToLowerInvariant()
Save-RunEvidence -Status "SUBMISSION_READY" -Markers $markers `
    -Objects $objects -InputObjects $initialInputObjects `
    -SubmissionSha256 $submissionHash
