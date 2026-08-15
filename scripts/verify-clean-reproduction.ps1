[CmdletBinding()]
param(
    [ValidateSet("lite", "full")]
    [string]$Profile = "lite",
    [ValidateSet("minimax", "stepfun", "custom")]
    [string]$Provider = "minimax",
    [string]$Model = "MiniMax-M2.5",
    [string]$ProviderProfilePath = "",
    [string]$EvidenceRoot = "",
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$bootstrapScript = Join-Path $PSScriptRoot "bootstrap.ps1"
$demoScript = Join-Path $PSScriptRoot "demo.ps1"
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$requiredContainers = @(
    "hiclaw-controller",
    "hiclaw-manager",
    "hiclaw-worker-agentloom-investigator",
    "hiclaw-worker-agentloom-implementer",
    "hiclaw-worker-agentloom-verifier"
)

function Invoke-Checked {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$Description
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Assert-NewDirectory {
    param([Parameter(Mandatory)][string]$Path)

    if (Test-Path -LiteralPath $Path) {
        throw "EvidenceRoot already exists; refusing to reuse prior evidence: $Path"
    }
    $null = New-Item -ItemType Directory -Path $Path
}

function Test-EnvironmentVariablePresent {
    param([Parameter(Mandatory)][string]$Name)

    foreach ($scope in @("Process", "User", "Machine")) {
        if (-not [string]::IsNullOrWhiteSpace(
            [Environment]::GetEnvironmentVariable($Name, $scope)
        )) {
            return $true
        }
    }
    return $false
}

function Assert-FullPrerequisites {
    $null = Get-Command "docker" -ErrorAction Stop
    Invoke-Checked -FilePath "docker" -Arguments @("info") `
        -Description "Docker readiness check"

    $requiredVariable = switch ($Provider) {
        "minimax" { "MINIMAX_API_KEY" }
        "stepfun" { "STEPFUN_API_KEY" }
        "custom" {
            if ([string]::IsNullOrWhiteSpace($ProviderProfilePath)) {
                throw "The custom Provider requires -ProviderProfilePath."
            }
            $profile = Get-Content -LiteralPath $ProviderProfilePath -Raw |
                ConvertFrom-Json
            $profile.apiKeyEnvironmentVariable
        }
    }
    if ([string]::IsNullOrWhiteSpace($requiredVariable) -or
        -not (Test-EnvironmentVariablePresent -Name $requiredVariable)) {
        throw "Environment variable $requiredVariable is missing."
    }
    if ($Provider -eq "minimax" -and $Model -ne "MiniMax-M2.5") {
        throw "The Task 25 MiniMax path requires MiniMax-M2.5."
    }
    if ($Provider -eq "stepfun" -and $Model -ne "step-3.7-flash") {
        throw "The Task 25 StepFun path requires step-3.7-flash."
    }
}

function Assert-AgentTeamsContainers {
    foreach ($container in $requiredContainers) {
        $running = @(
            docker inspect $container --format "{{.State.Running}}" 2>$null
        ) | Select-Object -First 1
        if ($LASTEXITCODE -ne 0 -or $running.Trim() -ne "true") {
            throw "Required AgentTeams container is not running: $container"
        }
    }
}

$pwsh = (Get-Command "pwsh" -ErrorAction Stop).Source
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7 or newer is required."
}
$null = Get-Command "git" -ErrorAction Stop

if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) {
    $runId = "clean-{0}-{1}" -f (
        [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    ), ([Guid]::NewGuid().ToString("N").Substring(0, 8))
    $EvidenceRoot = Join-Path $projectRoot "artifacts\reproduction\$runId"
}
$EvidenceRoot = [IO.Path]::GetFullPath($EvidenceRoot)
Assert-NewDirectory -Path $EvidenceRoot

if ($Profile -eq "full") {
    Assert-FullPrerequisites
}

$bootstrapArguments = @("-NoProfile", "-File", $bootstrapScript, "-Profile", $Profile)
if (-not [string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $bootstrapArguments += @("-PythonExecutable", $PythonExecutable)
}
if ($Profile -eq "full") {
    $bootstrapArguments += @("-Provider", $Provider, "-Model", $Model)
    if ($Provider -eq "custom") {
        $bootstrapArguments += @("-ProviderProfilePath", $ProviderProfilePath)
        $bootstrapArguments += "-RunProviderConnectionTest"
    }
}
Invoke-Checked -FilePath $pwsh -Arguments $bootstrapArguments `
    -Description "AgentLoom bootstrap"

Invoke-Checked -FilePath $venvPython -Arguments @(
    "-m", "pip", "install", "--no-cache-dir",
    "--retries", "10", "--timeout", "60", "-e", "$projectRoot[dev]"
) -Description "Development dependency installation"

$demoRoot = Join-Path $EvidenceRoot "demo"
Invoke-Checked -FilePath $pwsh -Arguments @(
    "-NoProfile", "-File", $demoScript,
    "-Case", "severity-normalization",
    "-OutputRoot", $demoRoot
) -Description "Deterministic Demo"

$bundlePath = Join-Path $demoRoot "artifacts\task-evidence-bundle.json"
if (-not (Test-Path -LiteralPath $bundlePath -PathType Leaf)) {
    throw "Deterministic Demo did not produce task-evidence-bundle.json."
}
$bundle = Get-Content -LiteralPath $bundlePath -Raw | ConvertFrom-Json
if ($bundle.schemaVersion -ne "agentloom.task-evidence-bundle/v1alpha1" -or
    $bundle.experience.outcome -ne "SUCCEEDED" -or
    $bundle.experience.verdict -ne "PASSED" -or
    @($bundle.detections | Where-Object { $_.result.verdict -ne "PASSED" }).Count -ne 0) {
    throw "Deterministic Demo evidence did not prove a passing run."
}

$junitPath = Join-Path $EvidenceRoot "pytest.xml"
Invoke-Checked -FilePath $venvPython -Arguments @(
    "-m", "pytest", "--tb=short", "--junitxml", $junitPath
) -Description "pytest quality gate"
[xml]$junit = Get-Content -LiteralPath $junitPath -Raw
$suite = $junit.testsuites.testsuite
$tests = [int]$suite.tests
$failures = [int]$suite.failures
$errors = [int]$suite.errors
$skipped = [int]$suite.skipped
if ($failures -ne 0 -or $errors -ne 0) {
    throw "pytest report contains failures or errors."
}
$passed = $tests - $failures - $errors - $skipped

Invoke-Checked -FilePath $venvPython -Arguments @("-m", "ruff", "check", ".") `
    -Description "Ruff quality gate"
Invoke-Checked -FilePath $venvPython -Arguments @("-m", "mypy", "src", "tests") `
    -Description "mypy quality gate"
Invoke-Checked -FilePath $venvPython -Arguments @("-m", "pip_audit") `
    -Description "dependency audit"
Invoke-Checked -FilePath $venvPython -Arguments @("-m", "pip", "check") `
    -Description "package integrity check"

$heads = @(
    & $venvPython -m alembic -c (Join-Path $projectRoot "alembic.ini") heads
)
if ($LASTEXITCODE -ne 0 -or $heads.Count -ne 1 -or $heads[0] -notmatch "^0006") {
    throw "Alembic must have exactly one 0006 head."
}

$fullEvidenceSha256 = $null
if ($Profile -eq "full") {
    Assert-AgentTeamsContainers
    $healthPath = Join-Path $projectRoot "artifacts\agentteams\health.json"
    if (-not (Test-Path -LiteralPath $healthPath -PathType Leaf)) {
        throw "Full bootstrap did not produce redacted health evidence."
    }
    $fullEvidenceSha256 = (Get-FileHash -LiteralPath $healthPath -Algorithm SHA256).Hash.ToLowerInvariant()
}

$commit = @(
    & git -C $projectRoot rev-parse HEAD
)
if ($LASTEXITCODE -ne 0 -or $commit.Count -ne 1 -or $commit[0] -notmatch "^[a-f0-9]{40}$") {
    throw "Cannot bind reproduction evidence to one Git commit."
}

$summary = [ordered]@{
    schemaVersion = "agentloom.clean-reproduction/v1alpha1"
    status = "PASSED"
    profile = $Profile
    sourceCommit = $commit[0]
    demo = [ordered]@{
        caseId = "severity-normalization"
        taskId = $bundle.taskId
        outcome = $bundle.experience.outcome
        verdict = $bundle.experience.verdict
        evidenceSha256 = (
            Get-FileHash -LiteralPath $bundlePath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
    }
    quality = [ordered]@{
        tests = $tests
        passed = $passed
        failures = $failures
        errors = $errors
        skipped = $skipped
        ruff = "PASSED"
        mypy = "PASSED"
        dependencyAudit = "PASSED"
        packageIntegrity = "PASSED"
        alembicHead = "0006"
    }
    full = if ($Profile -eq "full") {
        [ordered]@{
            provider = $Provider
            model = $Model
            healthEvidenceSha256 = $fullEvidenceSha256
        }
    }
    else {
        $null
    }
}

$summaryPath = Join-Path $EvidenceRoot "reproduction-evidence.json"
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding utf8
$summaryHash = (Get-FileHash -LiteralPath $summaryPath -Algorithm SHA256).Hash.ToLowerInvariant()

$summary | ConvertTo-Json -Depth 8
Write-Host "Evidence SHA-256: $summaryHash"
