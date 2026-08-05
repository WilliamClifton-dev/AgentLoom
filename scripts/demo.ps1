[CmdletBinding()]
param(
    [ValidateSet("severity-normalization", "pagination-boundary")]
    [string]$Case = "severity-normalization",
    [string]$OutputRoot = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$caseRoot = Join-Path $projectRoot "demo\cases\$Case"
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $projectRoot "artifacts\demo\$Case"
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "AgentLoom is not initialized. Run .\scripts\bootstrap.ps1 -Profile lite first."
}
if (-not (Test-Path -LiteralPath $caseRoot -PathType Container)) {
    throw "Demo case '$Case' is missing."
}

& $python @(
    "-m", "agentloom.mock_repair",
    "--case-root", $caseRoot,
    "--output-root", ([IO.Path]::GetFullPath($OutputRoot))
)
if ($LASTEXITCODE -ne 0) {
    throw "The deterministic AgentLoom demo failed with exit code $LASTEXITCODE."
}

Write-Host "Demo passed. Evidence: $([IO.Path]::GetFullPath($OutputRoot))"
