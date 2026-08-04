[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet("Prepare", "Collect")]
    [string]$Phase,
    [ValidatePattern("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
    [string]$RunId = "current",
    [string]$RunRoot = ".\artifacts\l2-approval",
    [string]$DatabasePath = ".\artifacts\tui\control.db",
    [string]$PythonPath = "",
    [string]$ControllerContainer = "hiclaw-controller",
    [string]$ManagerContainer = "hiclaw-manager",
    [string]$MatrixBaseUrl = "http://127.0.0.1:18080",
    [string]$ElementUrl = "http://127.0.0.1:18088",
    [ValidateRange(1, 14)]
    [int]$LifetimeMinutes = 10
)

$ErrorActionPreference = "Stop"
$allowedMatrixHosts = @("127.0.0.1", "localhost")
try {
    $matrixUri = [Uri]$MatrixBaseUrl
}
catch {
    throw "MatrixBaseUrl must be an absolute local AgentTeams URL"
}
if (
    -not $matrixUri.IsAbsoluteUri -or
    $matrixUri.Scheme -ne "http" -or
    $matrixUri.Host -notin $allowedMatrixHosts -or
    $matrixUri.Port -ne 18080 -or
    -not [string]::IsNullOrWhiteSpace($matrixUri.UserInfo) -or
    $matrixUri.AbsolutePath -ne "/" -or
    -not [string]::IsNullOrWhiteSpace($matrixUri.Query) -or
    -not [string]::IsNullOrWhiteSpace($matrixUri.Fragment)
) {
    throw "MatrixBaseUrl must target the local AgentTeams Matrix endpoint on port 18080"
}
$MatrixBaseUrl = $matrixUri.GetLeftPart([UriPartial]::Authority)
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$resolvedRunRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot $RunRoot))
$runDirectory = Join-Path $resolvedRunRoot $RunId
$statePath = Join-Path $runDirectory "run-state.json"
$preparationPath = Join-Path $runDirectory "approval-request.json"
$submissionPath = Join-Path $runDirectory "matrix-submission.json"
$evidencePath = Join-Path $runDirectory "l2-approval-evidence.json"
$approvedTemplatePath = Join-Path $runDirectory "decision-template-approved.json"
$rejectedTemplatePath = Join-Path $runDirectory "decision-template-rejected.json"
$resolvedDatabasePath = [IO.Path]::GetFullPath((Join-Path $repoRoot $DatabasePath))

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
}
$PythonPath = [IO.Path]::GetFullPath($PythonPath)
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "AgentLoom Python runtime was not found at the configured path"
}

function Write-JsonFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][object]$Value
    )

    $directory = Split-Path -Parent $Path
    if ($directory) {
        [void](New-Item -ItemType Directory -Force -Path $directory)
    }
    $json = $Value | ConvertTo-Json -Depth 20
    [IO.File]::WriteAllText($Path, $json + "`n", [Text.UTF8Encoding]::new($false))
}

function Invoke-Docker {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $output = & docker @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed while preparing the L2 approval demo"
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
        [string]$accessToken = "",
        [object]$Body
    )

    $arguments = @{
        Method = $Method
        Uri = "$MatrixBaseUrl$Path"
        TimeoutSec = 20
    }
    if (-not [string]::IsNullOrWhiteSpace($accessToken)) {
        $arguments.Headers = @{ Authorization = "Bearer $accessToken" }
    }
    if ($null -ne $Body) {
        $arguments.ContentType = "application/json"
        $arguments.Body = $Body | ConvertTo-Json -Depth 20
    }
    return Invoke-RestMethod @arguments
}

function Get-ManagerSession {
    param([Parameter(Mandatory)]$Manager)

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
        throw "Matrix Manager credentials are unavailable"
    }

    $matrixDomain = $Manager.matrixUserID.Split(":", 2)[1]
    $matrixUserId = "@$adminUser`:$matrixDomain"
    if ($matrixUserId -ne $Manager.matrixUserID) {
        throw "Matrix admin identity is not the configured AgentTeams Manager"
    }
    $login = Invoke-Matrix -Method Post -Path "/_matrix/client/v3/login" -Body @{
        type = "m.login.password"
        identifier = @{ type = "m.id.user"; user = $matrixUserId }
        password = $adminPassword
    }
    $accessToken = $login.access_token
    if ([string]::IsNullOrWhiteSpace($accessToken)) {
        throw "Matrix login did not return a token"
    }
    return [ordered]@{ userId = $matrixUserId; token = $accessToken }
}

function Assert-AgentTeamsResources {
    $manager = Get-HiclawJson -Arguments @("get", "managers", "default")
    $team = Get-HiclawJson -Arguments @("get", "teams", "agentloom-repair")
    $human = Get-HiclawJson -Arguments @("get", "humans", "agentloom-developer")
    $humanRooms = @($human.rooms | Where-Object {
        -not [string]::IsNullOrWhiteSpace($_)
    })
    if (
        $manager.phase -ne "Running" -or
        $team.phase -ne "Active" -or
        $human.phase -ne "Active" -or
        [string]::IsNullOrWhiteSpace($manager.matrixUserID) -or
        [string]::IsNullOrWhiteSpace($team.teamRoomID) -or
        [string]::IsNullOrWhiteSpace($human.matrixUserID) -or
        $humanRooms -notcontains $team.teamRoomID
    ) {
        throw "AgentTeams Manager, Team Room, and Human must all be ready"
    }
    return [ordered]@{ manager = $manager; team = $team; human = $human }
}

function Invoke-AgentLoom {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $output = & $PythonPath -m agentloom.cli @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "AgentLoom command failed: $($output -join [Environment]::NewLine)"
    }
    return $output
}

function Send-MatrixText {
    param(
        [Parameter(Mandatory)][string]$RoomId,
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$accessToken
    )

    $roomSegment = [uri]::EscapeDataString($RoomId)
    $transactionId = [guid]::NewGuid().ToString("N")
    $response = Invoke-Matrix -Method Put `
        -Path "/_matrix/client/v3/rooms/$roomSegment/send/m.room.message/$transactionId" `
        -accessToken $accessToken -Body @{
            msgtype = "m.text"
            body = $Text
        }
    if ([string]::IsNullOrWhiteSpace($response.event_id)) {
        throw "Matrix did not return an event ID for the approval request"
    }
    return [string]$response.event_id
}

function Get-ExactMatrixEvent {
    param(
        [Parameter(Mandatory)][string]$RoomId,
        [Parameter(Mandatory)][string]$EventId,
        [Parameter(Mandatory)][string]$ExpectedSender,
        [Parameter(Mandatory)][string]$ExpectedBody,
        [Parameter(Mandatory)][string]$accessToken
    )

    $roomSegment = [uri]::EscapeDataString($RoomId)
    $eventSegment = [uri]::EscapeDataString($EventId)
    $event = Invoke-Matrix -Method Get `
        -Path "/_matrix/client/v3/rooms/$roomSegment/event/$eventSegment" `
        -accessToken $accessToken -Body $null
    if (
        $event.sender -ne $ExpectedSender -or
        $event.type -ne "m.room.message" -or
        $event.content.msgtype -ne "m.text" -or
        [string]$event.content.body -cne $ExpectedBody -or
        $null -eq $event.origin_server_ts
    ) {
        throw "Stored Matrix request event does not match the exact Manager request"
    }
    return [ordered]@{
        roomId = $RoomId
        eventId = $EventId
        sender = [string]$event.sender
        originServerTimestamp = [long]$event.origin_server_ts
        type = [string]$event.type
        content = [ordered]@{
            msgtype = [string]$event.content.msgtype
            body = [string]$event.content.body
        }
    }
}

function New-DecisionTemplate {
    param(
        [Parameter(Mandatory)]$Request,
        [Parameter(Mandatory)][ValidateSet("APPROVED", "REJECTED")][string]$Status,
        [Parameter(Mandatory)][string]$Reason
    )

    return [ordered]@{
        schemaVersion = "agentloom.l2-approval-decision/v1alpha1"
        approvalId = $Request.approvalId
        approvalVersion = $Request.approvalVersion
        taskId = $Request.taskId
        grantId = $Request.grantId
        parameterDigest = $Request.parameterDigest
        riskLevel = "L2"
        routeId = $Request.routeId
        rollbackPlanHash = $Request.rollbackPlanHash
        status = $Status
        reason = $Reason
    }
}

if ($Phase -eq "Prepare") {
    if (Test-Path -LiteralPath $statePath) {
        throw "Run state already exists; choose a new RunId to avoid overwriting evidence"
    }
    [void](New-Item -ItemType Directory -Force -Path $runDirectory)
    $resources = Assert-AgentTeamsResources
    $session = Get-ManagerSession -Manager $resources.manager

    $null = Invoke-AgentLoom -Arguments @(
        "prepare-l2",
        "--database", $resolvedDatabasePath,
        "--output", $preparationPath,
        "--lifetime-minutes", [string]$LifetimeMinutes
    )
    $preparation = Get-Content -Raw -LiteralPath $preparationPath |
        ConvertFrom-Json
    if (
        $preparation.schemaVersion -ne
            "agentloom.l2-approval-preparation/v1alpha1" -or
        $preparation.request.transportOrigin -ne "deterministic-host"
    ) {
        throw "AgentLoom returned an invalid L2 preparation record"
    }
    $requestBody = $preparation.request | ConvertTo-Json -Depth 20 -Compress
    $requestEventId = Send-MatrixText `
        -RoomId $resources.team.teamRoomID `
        -Text $requestBody -accessToken $session.token
    $requestEvent = Get-ExactMatrixEvent `
        -RoomId $resources.team.teamRoomID `
        -EventId $requestEventId `
        -ExpectedSender $resources.manager.matrixUserID `
        -ExpectedBody $requestBody -accessToken $session.token

    Write-JsonFile -Path $approvedTemplatePath -Value (
        New-DecisionTemplate -Request $preparation.request -Status "APPROVED" `
            -Reason "Exact request, parameter digest, and rollback plan reviewed."
    )
    Write-JsonFile -Path $rejectedTemplatePath -Value (
        New-DecisionTemplate -Request $preparation.request -Status "REJECTED" `
            -Reason "External write is not approved for this demonstration."
    )
    $state = [ordered]@{
        schemaVersion = "agentloom.l2-approval-run/v1alpha1"
        phase = "PREPARED"
        runId = $RunId
        preparedAt = [DateTimeOffset]::UtcNow.ToString("o")
        databasePath = $resolvedDatabasePath
        roomId = [string]$resources.team.teamRoomID
        managerUserId = [string]$resources.manager.matrixUserID
        humanUserId = [string]$resources.human.matrixUserID
        requestEvent = $requestEvent
    }
    Write-JsonFile -Path $statePath -Value $state

    Write-Host "L2 request is ready in the AgentLoom Team Room."
    Write-Host "Open Element: $ElementUrl"
    Write-Host "Review the request, then paste exactly one chosen template as the Human:"
    Write-Host "  approve: $approvedTemplatePath"
    Write-Host "  reject:  $rejectedTemplatePath"
    Write-Host "After sending it, run this script with -Phase Collect -RunId $RunId"
    exit 0
}

if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
    throw "Prepared run state does not exist for RunId $RunId"
}
$state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
if (
    $state.schemaVersion -ne "agentloom.l2-approval-run/v1alpha1" -or
    $state.phase -ne "PREPARED" -or
    $state.databasePath -ne $resolvedDatabasePath
) {
    throw "L2 run state is not ready for collection"
}
$resources = Assert-AgentTeamsResources
if (
    $resources.team.teamRoomID -ne $state.roomId -or
    $resources.manager.matrixUserID -ne $state.managerUserId -or
    $resources.human.matrixUserID -ne $state.humanUserId
) {
    throw "AgentTeams identities or Team Room changed after preparation"
}
$session = Get-ManagerSession -Manager $resources.manager
$roomSegment = [uri]::EscapeDataString([string]$state.roomId)
$feed = Invoke-Matrix -Method Get `
    -Path "/_matrix/client/v3/rooms/$roomSegment/messages?dir=b&limit=100" `
    -accessToken $session.token -Body $null
$requestBodyObject = [string]$state.requestEvent.content.body | ConvertFrom-Json
$candidates = @()
foreach ($event in @($feed.chunk)) {
    if ($event.sender -ne $state.humanUserId) {
        continue
    }
    if ($event.origin_server_ts -le $state.requestEvent.originServerTimestamp) {
        continue
    }
    if ($event.type -ne "m.room.message" -or $event.content.msgtype -ne "m.text") {
        continue
    }
    try {
        $decision = [string]$event.content.body | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        continue
    }
    if (
        $decision.schemaVersion -ne
            "agentloom.l2-approval-decision/v1alpha1" -or
        $decision.approvalId -ne
            $requestBodyObject.approvalId
    ) {
        continue
    }
    $candidates += [ordered]@{
        roomId = [string]$state.roomId
        eventId = [string]$event.event_id
        sender = [string]$event.sender
        originServerTimestamp = [long]$event.origin_server_ts
        type = [string]$event.type
        content = [ordered]@{
            msgtype = [string]$event.content.msgtype
            body = [string]$event.content.body
        }
    }
}
if ($candidates.Count -ne 1) {
    throw "Expected exactly one fresh Human decision event; found $($candidates.Count)"
}

$submission = [ordered]@{
    schemaVersion = "agentloom.l2-approval-submission/v1alpha1"
    requestEvent = $state.requestEvent
    decisionEvent = $candidates[0]
}
Write-JsonFile -Path $submissionPath -Value $submission
$null = Invoke-AgentLoom -Arguments @(
    "verify-l2",
    "--database", $resolvedDatabasePath,
    "--submission", $submissionPath,
    "--evidence", $evidencePath,
    "--room-id", [string]$state.roomId,
    "--manager-user-id", [string]$state.managerUserId,
    "--human-user-id", [string]$state.humanUserId
)
$evidence = Get-Content -Raw -LiteralPath $evidencePath | ConvertFrom-Json
$state.phase = "COLLECTED"
$state | Add-Member -NotePropertyName collectedAt `
    -NotePropertyValue ([DateTimeOffset]::UtcNow.ToString("o"))
$state | Add-Member -NotePropertyName status -NotePropertyValue $evidence.status
$state | Add-Member -NotePropertyName evidencePath -NotePropertyValue $evidencePath
Write-JsonFile -Path $statePath -Value $state

Write-Host "Verified Human L2 decision: $($evidence.status)"
Write-Host "Redacted evidence: $evidencePath"
