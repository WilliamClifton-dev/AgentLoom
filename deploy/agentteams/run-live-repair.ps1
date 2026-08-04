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
    [string]$CaseRoot = ".\demo\cases\pagination-boundary",
    [string]$SubmissionPath = "",
    [string]$EvidencePath = "",
    [switch]$Resume,
    [string]$ResumeEvidencePath = ""
)

$ErrorActionPreference = "Stop"
$MaxArtifactBytes = 131072

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
        [Parameter(Mandatory)][string]$MentionUserId,
        [Parameter(Mandatory)][string]$AuthToken
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
        -AuthToken $AuthToken -Body $body
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
                    -not $found.ContainsKey($requirement.key) -and
                    (Test-ExactMarker -event $event `
                        -ExpectedSender $requirement.sender `
                        -Marker $requirement.marker `
                        -StartedAtMilliseconds $StartedAtMilliseconds)
                ) {
                    $found[$requirement.key] = [ordered]@{
                        key = $requirement.key
                        agentName = $requirement.agentName
                        sender = $event.sender
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
        [Parameter(Mandatory)][string]$SourceRoot
    )

    $resolvedCaseRoot = [IO.Path]::GetFullPath($SourceRoot)
    $sourceFiles = @(
        [ordered]@{
            objectName = "base/lib/__init__.py"
            sourcePath = Join-Path $resolvedCaseRoot "before/lib/__init__.py"
        },
        [ordered]@{
            objectName = "base/lib/pagination.py"
            sourcePath = Join-Path $resolvedCaseRoot "before/lib/pagination.py"
        },
        [ordered]@{
            objectName = "base/tests/test_pagination.py"
            sourcePath = Join-Path $resolvedCaseRoot "before/tests/test_pagination.py"
        }
    )
    foreach ($source in $sourceFiles) {
        if (-not (Test-Path -LiteralPath $source.sourcePath -PathType Leaf)) {
            throw "Live repair Case input is missing: $($source.sourcePath)"
        }
    }

    $specTemp = [IO.Path]::GetTempFileName()
    $containerTempRoot = "/tmp/agentloom-stage-$TaskId-$([guid]::NewGuid().ToString('N'))"
    $containerFiles = @()
    try {
        $spec = @"
# AgentLoom live repair task $TaskId

Issue: page_count adds an extra page when total_items is an exact multiple of page_size.

Acceptance criteria:
- Reproduce page_count(20, 10) == 3 before patch.
- Make page_count(20, 10) == 2.
- Preserve ValueError for negative total_items or non-positive page_size.
- Only lib/pagination.py may change.
- Do not read any other shared task directory.
- Do not use hidden tests or expected patches; they are not present in this namespace.

Visible command: pytest -q
Static command: python -m compileall -q lib tests
"@.Trim()
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
            $eventEvidence += $Markers[$key]
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
        provider = "dashscope"
        model = "qwen3.7-plus"
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
        }
        inputObjects = $inputEvidence
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
$initialObjects = @()
$expectedInitial = @(
    "base/lib/__init__.py",
    "base/lib/pagination.py",
    "base/tests/test_pagination.py",
    "spec.md"
)
if (-not $Resume) {
    $initialObjects = Get-TaskObjects -TaskPrefix $taskPrefix
    if ($initialObjects.Count -eq 0) {
        Stage-LiveRepairCase -TaskPrefix $taskPrefix -SourceRoot $CaseRoot
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

$requirements = @(
    [ordered]@{
        key = "investigator"
        agentName = "agentloom-investigator"
        sender = $investigator.matrixUserID
        marker = "[$TaskId] ROOT_CAUSE_REPORT"
    },
    [ordered]@{
        key = "implementer"
        agentName = "agentloom-implementer"
        sender = $implementer.matrixUserID
        marker = "[$TaskId] IMPLEMENTER_ARTIFACT_DONE"
    },
    [ordered]@{
        key = "verifier"
        agentName = "agentloom-verifier"
        sender = $verifier.matrixUserID
        marker = "[$TaskId] VERIFIER_ARTIFACT_DONE"
    }
)

$prompt = @"
$($investigator.matrixUserID) [$TaskId] Run one real L1 repair using exactly the existing Team namespace path shared/tasks/$TaskId/. Do not create or use another task ID, taskflow subtask, global-shared path, shared/projects path, or any other shared/tasks directory.

The namespace contains only spec.md and base/. There is no expected/ directory and no hidden test directory. Never search for or create expected/ or hidden tests. Hidden tests will be injected later by the independent AgentLoom host verifier.

Required collaboration:
1. Investigator reads only spec.md and base/, reproduces the visible failure without modifying base/, writes shared/tasks/$TaskId/root-cause-report.json, then uses filesync push for exactly that one file. Never push the whole task directory. Only after the push succeeds, post an m.text message containing the exact standalone line [$TaskId] ROOT_CAUSE_REPORT.
2. Investigator directly mentions agentloom-implementer in this Team Room and does not use filesync again. Implementer first pulls only the current task inputs, copies base/ to workspace/, changes only workspace/lib/pagination.py, runs `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider -q`, creates a standard UTF-8 unified diff at shared/tasks/$TaskId/repair.patch with headers exactly --- a/lib/pagination.py and +++ b/lib/pagination.py, computes its SHA-256, writes shared/tasks/$TaskId/patch-artifact.json, then uses filesync push for exactly repair.patch and patch-artifact.json. Never push base/, workspace/, or the whole task directory. Only after both pushes succeed, post the exact standalone line [$TaskId] IMPLEMENTER_ARTIFACT_DONE from its own identity.
3. After the Implementer completion event, Investigator directly mentions agentloom-verifier and does not push or pull any artifact. Verifier independently pulls only base/, repair.patch, and patch-artifact.json, copies base/ to verifier-workspace/, applies repair.patch, runs `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider -q` and `python -m compileall -q lib tests`, checks that only lib/pagination.py changes, writes shared/tasks/$TaskId/verification-result.json and risk-report.json, then uses filesync push for exactly those two JSON files. Never push a workspace, cache, or whole task directory. Only after both pushes succeed, post the exact standalone line [$TaskId] VERIFIER_ARTIFACT_DONE from its own identity.

Use these exact JSON contracts and keep task ID $TaskId everywhere. Do not invent Matrix event IDs; AgentLoom binds actual event IDs during ingestion.
root-cause-report.json: {"taskId":"$TaskId","summary":"non-empty","confidence":0.0,"evidenceRefs":["shared/tasks/$TaskId/spec.md"],"repairConstraints":["only lib/pagination.py may change"]}
patch-artifact.json: {"taskId":"$TaskId","patchUri":"artifact://$TaskId/repair.patch","sha256":"64 lowercase hex","changedPaths":["lib/pagination.py"],"evidenceRefs":["shared/tasks/$TaskId/repair.patch"]}
verification-result.json: {"schema_version":"agentloom.verification/v1alpha1","task_id":"$TaskId","patch_hash":"same 64 lowercase hex","verdict":"PASSED","checks":{"original_failure_reproduced":true,"target_tests_passed":true,"regression_tests_passed":true,"static_checks_passed":true,"unauthorized_changes":false},"evidence_refs":["shared/tasks/$TaskId/repair.patch"],"reason":"non-empty","verifier_agent":"agentloom-verifier"}
risk-report.json: {"taskId":"$TaskId","riskLevel":"L1","verdict":"PASSED","findings":[],"evidenceRefs":["shared/tasks/$TaskId/repair.patch"]}

Do not claim hidden-test success. Stop and report failure if any visible or static check fails. Completion markers must be independent trimmed lines and must be sent by the role that owns them. Do not create `.pytest_cache` or `__pycache__` under shared/tasks.
"@.Trim()

$startedAtMilliseconds = $startedAt.ToUnixTimeMilliseconds()
if (-not $Resume) {
    Send-MatrixText -RoomId $team.teamRoomID -Text $prompt `
        -MentionUserId $investigator.matrixUserID -AuthToken $authToken
}

$deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
$markers = @{}
while ([DateTimeOffset]::UtcNow -lt $deadline) {
    $markers = Find-StrictMarkers -RoomId $team.teamRoomID `
        -Requirements $requirements -AuthToken $authToken `
        -StartedAtMilliseconds $startedAtMilliseconds
    if ($markers.Count -eq $requirements.Count) {
        break
    }
    Start-Sleep -Seconds $PollSeconds
}
if ($markers.Count -ne $requirements.Count) {
    Save-RunEvidence -Status "TIMEOUT" -Markers $markers `
        -InputObjects $initialInputObjects
    throw "Live repair role event collection timed out after $TimeoutSeconds seconds"
}

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
    provider = "dashscope"
    model = "qwen3.7-plus"
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
