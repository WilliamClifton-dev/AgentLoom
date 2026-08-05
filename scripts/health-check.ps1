[CmdletBinding()]
param(
    [string]$ControllerContainer = "hiclaw-controller",
    [string]$EvidencePath = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$agentTeamsRoot = Join-Path $projectRoot "deploy\agentteams"
$lock = Get-Content -Raw -LiteralPath (Join-Path $agentTeamsRoot "version-lock.json") |
    ConvertFrom-Json
$checks = [Collections.Generic.List[object]]::new()
$failure = ""
$failureCode = ""
$stage = "startup"

if ([string]::IsNullOrWhiteSpace($EvidencePath)) {
    $EvidencePath = Join-Path $projectRoot "artifacts\agentteams\health.json"
}
$resolvedEvidencePath = [IO.Path]::GetFullPath($EvidencePath)

function Invoke-Docker {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $output = & docker @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed."
    }
    return $output
}

function Invoke-HiclawJson {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $dockerArguments = @("exec", $ControllerContainer, "hiclaw") +
        $Arguments + @("-o", "json")
    return (Invoke-Docker -Arguments $dockerArguments | Out-String) | ConvertFrom-Json
}

function Add-HealthCheck {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][bool]$Passed,
        [Parameter(Mandatory)][string]$Detail
    )

    $checks.Add([ordered]@{
        name = $Name
        passed = $Passed
        detail = $Detail
    })
}

try {
    $stage = "docker-cli"
    $null = Get-Command "docker" -ErrorAction Stop
    $stage = "docker-daemon"
    $null = Invoke-Docker -Arguments @("info")
    Add-HealthCheck -Name "docker" -Passed $true -Detail "Docker daemon is reachable."

    $stage = "controller"
    $controllerState = (Invoke-Docker -Arguments @(
        "inspect", $ControllerContainer, "--format", "{{.State.Running}}|{{.Config.Image}}"
    ) | Select-Object -First 1).Trim().Split("|", 2)
    $controllerReady = (
        $controllerState[0] -eq "true" -and
        $controllerState[1] -eq $lock.images.controller.reference
    )
    $lockedControllerImage = $controllerState[1] -eq $lock.images.controller.reference
    Add-HealthCheck -Name "controller" -Passed $controllerReady -Detail (
        "running=$($controllerState[0]); lockedImage=$lockedControllerImage"
    )

    $stage = "images"
    foreach ($image in @($lock.images.controller, $lock.images.manager_copaw)) {
        $actualDigest = (Invoke-Docker -Arguments @(
            "image", "inspect", $image.reference, "--format", "{{.Id}}"
        ) | Select-Object -First 1).Trim()
        Add-HealthCheck -Name "image-digest" -Passed ($actualDigest -eq $image.digest) `
            -Detail "reference=$($image.reference); digestMatches=$($actualDigest -eq $image.digest)"
    }

    $stage = "resources"
    $manager = Invoke-HiclawJson -Arguments @("get", "managers", "default")
    $team = Invoke-HiclawJson -Arguments @("get", "teams", "agentloom-repair")
    $workers = Invoke-HiclawJson -Arguments @(
        "get", "workers", "--team", "agentloom-repair"
    )
    $human = Invoke-HiclawJson -Arguments @("get", "humans", "agentloom-developer")

    $managerReady = $manager.phase -eq "Running"
    $teamReady = (
        $team.phase -eq "Active" -and
        $team.leaderReady -and
        $team.readyWorkers -eq 2 -and
        $team.totalWorkers -eq 2
    )
    $expectedWorkerNames = @(
        "agentloom-investigator",
        "agentloom-implementer",
        "agentloom-verifier"
    )
    $actualWorkerNames = @($workers.workers | ForEach-Object { $_.name })
    $workersReady = (
        $workers.total -eq 3 -and
        @($workers.workers | Where-Object { $_.phase -ne "Running" }).Count -eq 0 -and
        @($expectedWorkerNames | Where-Object { $_ -notin $actualWorkerNames }).Count -eq 0
    )
    $humanReady = $human.phase -eq "Active"
    $roomsReady = (
        -not [string]::IsNullOrWhiteSpace($team.teamRoomID) -and
        -not [string]::IsNullOrWhiteSpace($team.leaderDMRoomID) -and
        @($human.rooms) -contains $team.teamRoomID
    )

    Add-HealthCheck -Name "manager" -Passed $managerReady `
        -Detail "name=default; phase=$($manager.phase)"
    Add-HealthCheck -Name "team" -Passed $teamReady `
        -Detail "name=agentloom-repair; phase=$($team.phase)"
    Add-HealthCheck -Name "workers" -Passed $workersReady `
        -Detail "running=$(@($workers.workers | Where-Object { $_.phase -eq 'Running' }).Count)/3"
    Add-HealthCheck -Name "human" -Passed $humanReady `
        -Detail "name=agentloom-developer; phase=$($human.phase)"
    $roomDetail = (
        "teamRoom=$(-not [string]::IsNullOrWhiteSpace($team.teamRoomID)); " +
        "leaderDM=$(-not [string]::IsNullOrWhiteSpace($team.leaderDMRoomID)); " +
        "humanJoined=$(@($human.rooms) -contains $team.teamRoomID)"
    )
    Add-HealthCheck -Name "matrix-rooms" -Passed $roomsReady `
        -Detail $roomDetail
}
catch {
    $failure = $_.Exception.Message
    $failureCode = $stage
    $failureDetail = switch ($stage) {
        "docker-cli" { "Docker CLI is not installed or is not on PATH." }
        "docker-daemon" { "Docker daemon is not reachable." }
        "controller" { "The AgentTeams controller is missing or unreadable." }
        "images" { "A locked AgentTeams image is missing or unreadable." }
        "resources" { "AgentTeams resources could not be queried." }
        default { "A required local runtime query failed." }
    }
    Add-HealthCheck -Name $stage -Passed $false -Detail $failureDetail
}

$passed = (
    [string]::IsNullOrWhiteSpace($failure) -and
    @($checks | Where-Object { -not $_.passed }).Count -eq 0
)
$evidence = [ordered]@{
    schemaVersion = "agentloom.deployment-health/v1alpha1"
    checkedAt = [DateTimeOffset]::UtcNow.ToString("o")
    status = if ($passed) { "PASS" } else { "FAIL" }
    agentTeams = [ordered]@{
        tag = $lock.upstream.tag
        commit = $lock.upstream.commit
    }
    failureCode = $failureCode
    checks = @($checks)
}
$evidenceJson = $evidence | ConvertTo-Json -Depth 10
$evidenceDirectory = Split-Path -Parent $resolvedEvidencePath
if ($evidenceDirectory) {
    [void](New-Item -ItemType Directory -Force -Path $evidenceDirectory)
}
[IO.File]::WriteAllText(
    $resolvedEvidencePath,
    $evidenceJson,
    [Text.UTF8Encoding]::new($false)
)
$evidenceJson

if (-not $passed) {
    throw "AgentLoom health check failed. Inspect $resolvedEvidencePath."
}
