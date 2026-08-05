[CmdletBinding()]
param(
    [ValidateSet("replay", "live")]
    [string]$Mode = "replay",
    [string]$TaskId = "",
    [string]$HealthEvidencePath = "",
    [string]$RunEvidencePath = "",
    [string]$VerifiedEvidencePath = "",
    [ValidateRange(60, 3600)]
    [int]$TimeoutSeconds = 1800,
    [switch]$ConfirmPaidRun,
    [switch]$NoTui
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$agentTeamsRoot = Join-Path $projectRoot "deploy\agentteams"
$agentTeamsArtifacts = Join-Path $projectRoot "artifacts\agentteams"
$liveArtifacts = Join-Path $projectRoot "artifacts\live-repair"
$caseRoot = Join-Path $projectRoot "demo\cases\pagination-boundary"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "AgentLoom is not initialized. Run .\scripts\bootstrap.ps1 -Profile lite first."
}
if ([string]::IsNullOrWhiteSpace($HealthEvidencePath)) {
    $HealthEvidencePath = Join-Path $agentTeamsArtifacts "health.json"
}

function Invoke-AgentLoom {
    param([Parameter(Mandatory)][string[]]$Arguments)

    & $python @("-m", "agentloom.cli") @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "AgentLoom command failed."
    }
}

function Read-RunIdentity {
    param([Parameter(Mandatory)][string]$Path)

    try {
        if ((Get-Item -LiteralPath $Path).Length -gt 1MB) {
            throw "oversized"
        }
        $payload = Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
    }
    catch {
        throw "A candidate live run evidence file is invalid."
    }
    if (
        $payload.schemaVersion -ne "agentloom.live-repair-run/v1alpha1" -or
        $payload.status -ne "SUBMISSION_READY" -or
        [string]$payload.taskId -notmatch "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    ) {
        throw "A candidate live run evidence file is not displayable."
    }
    return [ordered]@{
        taskId = [string]$payload.taskId
        path = [IO.Path]::GetFullPath($Path)
    }
}

function Resolve-ReplayEvidence {
    if ([string]::IsNullOrWhiteSpace($RunEvidencePath)) {
        $candidate = Get-ChildItem -LiteralPath $agentTeamsArtifacts -File `
            -Filter "live-repair-*.json" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Where-Object {
                try {
                    if ($_.Length -gt 1MB) {
                        return $false
                    }
                    $payload = Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json
                    return (
                        $payload.schemaVersion -eq "agentloom.live-repair-run/v1alpha1" -and
                        $payload.status -eq "SUBMISSION_READY"
                    )
                }
                catch {
                    return $false
                }
            } |
            Select-Object -First 1
        if ($null -eq $candidate) {
            throw "No completed live AgentTeams run evidence was found."
        }
        $runIdentity = Read-RunIdentity -Path $candidate.FullName
    }
    else {
        $runIdentity = Read-RunIdentity -Path $RunEvidencePath
    }

    $verifiedPath = $VerifiedEvidencePath
    if ([string]::IsNullOrWhiteSpace($verifiedPath)) {
        $taskRoot = Join-Path $liveArtifacts $runIdentity.taskId
        $candidate = Get-ChildItem -LiteralPath $taskRoot -Recurse -File `
            -Filter "live-repair-evidence.json" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($null -eq $candidate) {
            throw "No independent host verification evidence was found for the live run."
        }
        $verifiedPath = $candidate.FullName
    }
    return [ordered]@{
        run = $runIdentity.path
        verified = [IO.Path]::GetFullPath($verifiedPath)
    }
}

if ($Mode -eq "live") {
    if (-not $ConfirmPaidRun) {
        throw "Live mode can spend model quota. Rerun with -ConfirmPaidRun."
    }
    if ($TaskId -notmatch "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$") {
        throw "Live mode requires a safe, non-empty -TaskId."
    }
}

& (Join-Path $PSScriptRoot "health-check.ps1") -EvidencePath $HealthEvidencePath

if ($Mode -eq "live") {
    $taskRoot = Join-Path $liveArtifacts $TaskId
    $submissionPath = Join-Path $taskRoot "submission.json"
    $verificationRoot = Join-Path $taskRoot "verified"
    if ([string]::IsNullOrWhiteSpace($RunEvidencePath)) {
        $RunEvidencePath = Join-Path $agentTeamsArtifacts "live-repair-$TaskId.json"
    }
    if (
        (Test-Path -LiteralPath $RunEvidencePath) -or
        (Test-Path -LiteralPath $submissionPath) -or
        (Test-Path -LiteralPath $verificationRoot)
    ) {
        throw "Live mode refuses to overwrite an existing task or evidence path."
    }

    & (Join-Path $agentTeamsRoot "run-live-repair.ps1") `
        -TaskId $TaskId `
        -CaseRoot $caseRoot `
        -SubmissionPath $submissionPath `
        -EvidencePath $RunEvidencePath `
        -TimeoutSeconds $TimeoutSeconds
    Invoke-AgentLoom -Arguments @(
        "verify-live",
        "--submission", $submissionPath,
        "--case-root", $caseRoot,
        "--output-root", $verificationRoot
    )
    $VerifiedEvidencePath = Join-Path `
        $verificationRoot "artifacts\live-repair-evidence.json"
    $evidence = [ordered]@{
        run = [IO.Path]::GetFullPath($RunEvidencePath)
        verified = [IO.Path]::GetFullPath($VerifiedEvidencePath)
    }
}
else {
    $evidence = Resolve-ReplayEvidence
}

Invoke-AgentLoom -Arguments @(
    "inspect-live",
    "--health-evidence", ([IO.Path]::GetFullPath($HealthEvidencePath)),
    "--run-evidence", $evidence.run,
    "--verified-evidence", $evidence.verified
)

if (-not $NoTui) {
    Invoke-AgentLoom -Arguments @(
        "tui",
        "--health-evidence", ([IO.Path]::GetFullPath($HealthEvidencePath)),
        "--run-evidence", $evidence.run,
        "--verified-evidence", $evidence.verified
    )
}
