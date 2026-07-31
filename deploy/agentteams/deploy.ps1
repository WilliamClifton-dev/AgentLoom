[CmdletBinding()]
param(
    [string]$Model = "qwen3.7-plus",
    [ValidateSet("copaw", "openclaw", "hermes")]
    [string]$WorkerRuntime = "copaw",
    [string]$ControllerContainer = "hiclaw-controller",
    [int]$TimeoutSeconds = 900,
    [string]$EvidencePath = ""
)

$ErrorActionPreference = "Stop"
$deployRoot = $PSScriptRoot
$lockPath = Join-Path $deployRoot "version-lock.json"
$resourceRoot = Join-Path $deployRoot "resources"
$lock = Get-Content -Raw -LiteralPath $lockPath | ConvertFrom-Json

function Invoke-Docker {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $output = & docker @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($Arguments -join ' ') failed: $($output -join [Environment]::NewLine)"
    }
    return $output
}

function Invoke-Hiclaw {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $dockerArguments = @("exec", $ControllerContainer, "hiclaw") + $Arguments
    return Invoke-Docker -Arguments $dockerArguments
}

function Get-HiclawJson {
    param([Parameter(Mandatory)][string[]]$Arguments)

    return (Invoke-Hiclaw -Arguments ($Arguments + @("-o", "json")) | Out-String) |
        ConvertFrom-Json
}

function Test-HumanExists {
    & docker exec $ControllerContainer hiclaw get humans agentloom-developer -o json `
        1>$null 2>$null
    return $LASTEXITCODE -eq 0
}

function Assert-ImageDigest {
    param(
        [Parameter(Mandatory)][string]$Reference,
        [Parameter(Mandatory)][string]$ExpectedDigest
    )

    $actual = (Invoke-Docker -Arguments @(
        "image", "inspect", $Reference, "--format", "{{.Id}}"
    ) | Select-Object -First 1).Trim()
    if ($actual -ne $ExpectedDigest) {
        throw "Image digest mismatch for $Reference. Expected $ExpectedDigest; got $actual"
    }
}

function Wait-AgentTeamCoreReady {
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    $last = "Core resources have not been observed"

    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        try {
            $manager = Get-HiclawJson -Arguments @("get", "managers", "default")
            $team = Get-HiclawJson -Arguments @("get", "teams", "agentloom-repair")
            $workers = Get-HiclawJson -Arguments @(
                "get", "workers", "--team", "agentloom-repair"
            )
            $workerNames = @($workers.workers | ForEach-Object { $_.name })
            $expectedNames = @(
                "agentloom-investigator",
                "agentloom-implementer",
                "agentloom-verifier"
            )
            $allWorkersRunning = (
                $workers.total -eq 3 -and
                @($workers.workers | Where-Object { $_.phase -ne "Running" }).Count -eq 0 -and
                @($expectedNames | Where-Object { $_ -notin $workerNames }).Count -eq 0
            )
            $ready = (
                $manager.phase -eq "Running" -and
                $team.phase -eq "Active" -and
                $team.leaderReady -and
                $team.readyWorkers -eq 2 -and
                $team.totalWorkers -eq 2 -and
                $allWorkersRunning -and
                -not [string]::IsNullOrWhiteSpace($team.teamRoomID) -and
                -not [string]::IsNullOrWhiteSpace($team.leaderDMRoomID)
            )
            if ($ready) {
                return
            }
            $last = "manager=$($manager.phase), team=$($team.phase), workers=$($workers.total)"
        }
        catch {
            $last = $_.Exception.Message
        }
        Start-Sleep -Seconds 5
    }

    throw "Agent team core did not become ready within $TimeoutSeconds seconds. Last state: $last"
}

function Wait-AgentTeamsReady {
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    $last = "Resources have not been observed"

    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        try {
            $manager = Get-HiclawJson -Arguments @("get", "managers", "default")
            $team = Get-HiclawJson -Arguments @("get", "teams", "agentloom-repair")
            $workers = Get-HiclawJson -Arguments @(
                "get", "workers", "--team", "agentloom-repair"
            )
            $human = Get-HiclawJson -Arguments @("get", "humans", "agentloom-developer")

            $workerNames = @($workers.workers | ForEach-Object { $_.name })
            $expectedNames = @(
                "agentloom-investigator",
                "agentloom-implementer",
                "agentloom-verifier"
            )
            $allWorkersRunning = (
                $workers.total -eq 3 -and
                @($workers.workers | Where-Object { $_.phase -ne "Running" }).Count -eq 0 -and
                @($expectedNames | Where-Object { $_ -notin $workerNames }).Count -eq 0
            )
            $roomsReady = (
                -not [string]::IsNullOrWhiteSpace($team.teamRoomID) -and
                -not [string]::IsNullOrWhiteSpace($team.leaderDMRoomID) -and
                -not [string]::IsNullOrWhiteSpace($human.matrixUserID)
            )
            $validHumanRooms = @($human.rooms | Where-Object {
                -not [string]::IsNullOrWhiteSpace($_)
            })
            $ready = (
                $manager.phase -eq "Running" -and
                $team.phase -eq "Active" -and
                $team.leaderReady -and
                $team.readyWorkers -eq 2 -and
                $team.totalWorkers -eq 2 -and
                $allWorkersRunning -and
                $human.phase -eq "Active" -and
                ($validHumanRooms -contains $team.teamRoomID) -and
                $roomsReady
            )
            if ($ready) {
                return [ordered]@{
                    verifiedAt = [DateTimeOffset]::UtcNow.ToString("o")
                    agentTeams = [ordered]@{
                        tag = $lock.upstream.tag
                        commit = $lock.upstream.commit
                        controllerDigest = $lock.images.controller.digest
                        managerDigest = $lock.images.manager_copaw.digest
                    }
                    manager = [ordered]@{
                        name = $manager.name
                        phase = $manager.phase
                        model = $manager.model
                        runtime = $manager.runtime
                        matrixUserID = $manager.matrixUserID
                        roomID = $manager.roomID
                    }
                    team = [ordered]@{
                        name = $team.name
                        phase = $team.phase
                        leaderName = $team.leaderName
                        leaderReady = $team.leaderReady
                        readyWorkers = $team.readyWorkers
                        totalWorkers = $team.totalWorkers
                        teamRoomID = $team.teamRoomID
                        leaderDMRoomID = $team.leaderDMRoomID
                    }
                    workers = @($workers.workers | ForEach-Object {
                        [ordered]@{
                            name = $_.name
                            phase = $_.phase
                            role = $_.role
                            runtime = $_.runtime
                            matrixUserID = $_.matrixUserID
                            roomID = $_.roomID
                        }
                    })
                    human = [ordered]@{
                        name = $human.name
                        phase = $human.phase
                        displayName = $human.displayName
                        matrixUserID = $human.matrixUserID
                        rooms = $validHumanRooms
                    }
                }
            }
            $last = "manager=$($manager.phase), team=$($team.phase), " +
                "workers=$($workers.total), human=$($human.phase)"
        }
        catch {
            $last = $_.Exception.Message
        }
        Start-Sleep -Seconds 5
    }

    throw "AgentTeams resources did not become ready within $TimeoutSeconds seconds. Last state: $last"
}

$container = (Invoke-Docker -Arguments @(
    "inspect", $ControllerContainer, "--format", "{{.State.Running}}|{{.Config.Image}}"
) | Select-Object -First 1).Trim().Split("|", 2)
if ($container[0] -ne "true") {
    throw "$ControllerContainer is not running"
}
if ($container[1] -ne $lock.images.controller.reference) {
    throw "$ControllerContainer does not use locked image $($lock.images.controller.reference)"
}

Assert-ImageDigest -Reference $lock.images.controller.reference `
    -ExpectedDigest $lock.images.controller.digest
Assert-ImageDigest -Reference $lock.images.manager_copaw.reference `
    -ExpectedDigest $lock.images.manager_copaw.digest

$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ("agentloom-agentteams-" + [guid]::NewGuid())
[void](New-Item -ItemType Directory -Path $temporaryRoot)
$containerFiles = @()
$localFiles = @()

try {
    foreach ($name in @("manager", "team", "human")) {
        if ($name -eq "human") {
            Wait-AgentTeamCoreReady
            if (Test-HumanExists) {
                Write-Host (
                    "  human/agentloom-developer preserved. " +
                    "Human updates are not supported by AgentTeams v1.1.2."
                )
                continue
            }
        }
        $sourcePath = Join-Path $resourceRoot "$name.json"
        $resource = Get-Content -Raw -LiteralPath $sourcePath | ConvertFrom-Json
        if ($resource.kind -eq "Manager") {
            $resource.spec.model = $Model
            $resource.spec.runtime = "copaw"
        }
        elseif ($resource.kind -eq "Team") {
            $resource.spec.leader.model = $Model
            foreach ($worker in $resource.spec.workers) {
                $worker.model = $Model
                $worker.runtime = $WorkerRuntime
            }
        }

        $localPath = Join-Path $temporaryRoot "$name.json"
        [IO.File]::WriteAllText(
            $localPath,
            ($resource | ConvertTo-Json -Depth 20),
            [Text.UTF8Encoding]::new($false)
        )
        $containerPath = "/tmp/agentloom-$name.json"
        [void](Invoke-Docker -Arguments @("cp", $localPath, "${ControllerContainer}:$containerPath"))
        $containerFiles += $containerPath
        $localFiles += $localPath
        Invoke-Hiclaw -Arguments @("apply", "-f", $containerPath) | Write-Host
    }

    $evidence = Wait-AgentTeamsReady
    $evidenceJson = $evidence | ConvertTo-Json -Depth 20
    if (-not [string]::IsNullOrWhiteSpace($EvidencePath)) {
        $resolvedEvidence = [IO.Path]::GetFullPath($EvidencePath)
        $evidenceDirectory = Split-Path -Parent $resolvedEvidence
        if ($evidenceDirectory) {
            [void](New-Item -ItemType Directory -Force -Path $evidenceDirectory)
        }
        [IO.File]::WriteAllText($resolvedEvidence, $evidenceJson, [Text.UTF8Encoding]::new($false))
    }
    $evidenceJson
}
finally {
    foreach ($containerPath in $containerFiles) {
        & docker exec $ControllerContainer rm -f $containerPath 2>$null
    }
    foreach ($localPath in $localFiles) {
        Remove-Item -LiteralPath $localPath -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $temporaryRoot -Force -ErrorAction SilentlyContinue
}
