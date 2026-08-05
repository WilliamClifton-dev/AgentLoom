[CmdletBinding()]
param(
    [ValidateSet("replay", "live")]
    [string]$Mode = "replay",
    [string]$TaskId = "",
    [string]$HealthEvidencePath = "",
    [string]$RollbackEvidencePath = "",
    [ValidateSet("dashscope", "deepseek", "stepfun")]
    [string]$Provider = "dashscope",
    [ValidateSet("qwen3.7-plus", "deepseek-v4-pro", "step-3.7-flash")]
    [string]$Model = "qwen3.7-plus",
    [ValidateRange(60, 3600)]
    [int]$TimeoutSeconds = 1200,
    [switch]$ConfirmPaidRun,
    [switch]$NoTui
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$agentTeamsRoot = Join-Path $projectRoot "deploy\agentteams"
$agentTeamsArtifacts = Join-Path $projectRoot "artifacts\agentteams"
$rollbackArtifacts = Join-Path $projectRoot "artifacts\live-rollback"
$caseRoot = Join-Path $projectRoot "demo\cases\pagination-boundary"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "AgentLoom is not initialized. Run .\scripts\bootstrap.ps1 -Profile lite first."
}
if ([string]::IsNullOrWhiteSpace($HealthEvidencePath)) {
    $HealthEvidencePath = Join-Path $agentTeamsArtifacts "health.json"
}
if ($Mode -eq "live") {
    if (-not $ConfirmPaidRun) {
        throw "Live rollback mode can spend model quota. Rerun with -ConfirmPaidRun."
    }
    if ($TaskId -notmatch "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$") {
        throw "Live rollback mode requires a safe, non-empty -TaskId."
    }
    $approvedPairs = @{
        dashscope = "qwen3.7-plus"
        deepseek = "deepseek-v4-pro"
        stepfun = "step-3.7-flash"
    }
    if ($approvedPairs[$Provider] -ne $Model) {
        throw "Provider and model are not an approved live E2E pair."
    }
}

function Invoke-AgentLoom {
    param([Parameter(Mandatory)][string[]]$Arguments)

    & $python @("-m", "agentloom.cli") @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "AgentLoom command failed."
    }
}

& (Join-Path $PSScriptRoot "health-check.ps1") -EvidencePath $HealthEvidencePath

if ($Mode -eq "live") {
    $taskRoot = Join-Path $rollbackArtifacts $TaskId
    $submissionPath = Join-Path $taskRoot "submission.json"
    $verificationRoot = Join-Path $taskRoot "verified"
    $runEvidencePath = Join-Path $agentTeamsArtifacts "live-rollback-$TaskId.json"
    if (
        (Test-Path -LiteralPath $submissionPath) -or
        (Test-Path -LiteralPath $verificationRoot) -or
        (Test-Path -LiteralPath $runEvidencePath)
    ) {
        throw "Live rollback mode refuses to overwrite an existing task or evidence path."
    }
    if ($Provider -eq "dashscope") {
        & (Join-Path $agentTeamsRoot "configure-provider.ps1") `
            -Model $Model -SkipConnectionTest
    }
    elseif ($Provider -eq "deepseek") {
        & (Join-Path $agentTeamsRoot "configure-deepseek-provider.ps1") `
            -Model $Model -SkipConnectionTest
    }
    else {
        & (Join-Path $agentTeamsRoot "configure-stepfun-provider.ps1") `
            -Model $Model -SkipConnectionTest
    }
    & (Join-Path $agentTeamsRoot "run-live-rollback.ps1") `
        -TaskId $TaskId `
        -CaseRoot $caseRoot `
        -SubmissionPath $submissionPath `
        -EvidencePath $runEvidencePath `
        -Provider $Provider `
        -Model $Model `
        -TimeoutSeconds $TimeoutSeconds `
        -ConfirmPaidRun
    Invoke-AgentLoom -Arguments @(
        "verify-rollback",
        "--submission", $submissionPath,
        "--case-root", $caseRoot,
        "--output-root", $verificationRoot
    )
    $RollbackEvidencePath = Join-Path `
        $verificationRoot "artifacts\live-rollback-evidence.json"
}
elseif ([string]::IsNullOrWhiteSpace($RollbackEvidencePath)) {
    $candidate = Get-ChildItem -LiteralPath $rollbackArtifacts -Recurse -File `
        -Filter "live-rollback-evidence.json" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $candidate) {
        throw "No verified live rollback evidence was found for free replay."
    }
    $RollbackEvidencePath = $candidate.FullName
}

$resolvedHealth = [IO.Path]::GetFullPath($HealthEvidencePath)
$resolvedRollback = [IO.Path]::GetFullPath($RollbackEvidencePath)
Invoke-AgentLoom -Arguments @(
    "inspect-rollback",
    "--health-evidence", $resolvedHealth,
    "--rollback-evidence", $resolvedRollback
)

if (-not $NoTui) {
    Invoke-AgentLoom -Arguments @(
        "tui",
        "--health-evidence", $resolvedHealth,
        "--rollback-evidence", $resolvedRollback
    )
}
