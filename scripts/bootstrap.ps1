[CmdletBinding()]
param(
    [ValidateSet("lite", "full")]
    [string]$Profile = "lite",
    [ValidateSet("none", "qwen", "deepseek", "stepfun")]
    [string]$Provider = "none",
    [ValidateSet("qwen3.7-plus", "deepseek-v4-flash", "deepseek-v4-pro", "step-3.7-flash")]
    [string]$Model = "qwen3.7-plus",
    [string]$PythonExecutable = "",
    [string]$EvidencePath = "",
    [switch]$SkipPackageInstall,
    [switch]$SkipProviderConnectionTest
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvRoot = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$agentTeamsRoot = Join-Path $projectRoot "deploy\agentteams"

function Invoke-Checked {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$Description
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

function Resolve-PythonCommand {
    if (-not [string]::IsNullOrWhiteSpace($PythonExecutable)) {
        $command = Get-Command $PythonExecutable -ErrorAction Stop
        return @($command.Source)
    }

    $launcher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($null -ne $launcher) {
        return @($launcher.Source, "-3.12")
    }

    $python = Get-Command "python" -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        return @($python.Source)
    }

    throw "Python 3.12 was not found. Install it from https://www.python.org/downloads/."
}

function Assert-Python312 {
    param([Parameter(Mandatory)][string[]]$Command)

    $filePath = $Command[0]
    $prefix = @($Command | Select-Object -Skip 1)
    $versionOutput = @(& $filePath @prefix "-c" (
        "import sys; print('.'.join(map(str, sys.version_info[:2])))"
    ) 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "The selected Python command could not start Python 3.12."
    }
    $version = ($versionOutput | Select-Object -First 1).ToString().Trim()
    if ($version -ne "3.12") {
        throw "AgentLoom requires Python 3.12; detected '$version'."
    }
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

function Assert-FullProfilePrerequisites {
    if ($PSVersionTable.PSVersion.Major -lt 7) {
        throw "The full profile requires PowerShell 7 or newer."
    }
    if ($Provider -eq "none") {
        throw "The full profile requires -Provider qwen, deepseek, or stepfun."
    }
    if ($Provider -eq "qwen" -and $Model -ne "qwen3.7-plus") {
        throw "The qwen provider requires -Model qwen3.7-plus."
    }
    if ($Provider -eq "deepseek" -and $Model -notlike "deepseek-*") {
        throw "The deepseek provider requires a supported DeepSeek model."
    }
    if ($Provider -eq "stepfun" -and $Model -ne "step-3.7-flash") {
        throw "The stepfun provider requires -Model step-3.7-flash."
    }

    $null = Get-Command "docker" -ErrorAction Stop
    $null = Invoke-Checked -FilePath "docker" -Arguments @("info") `
        -Description "Docker Desktop readiness check"
    $controllerRunning = (Invoke-Checked -FilePath "docker" -Arguments @(
        "inspect", "hiclaw-controller", "--format", "{{.State.Running}}"
    ) -Description "AgentTeams controller readiness check" | Select-Object -First 1).Trim()
    if ($controllerRunning -ne "true") {
        throw "The AgentTeams controller is not running."
    }

    $requiredVariable = switch ($Provider) {
        "qwen" { "QWEN_API_KEY" }
        "deepseek" { "DEEPSEEK_API_KEY" }
        "stepfun" { "STEPFUN_API_KEY" }
    }
    if (-not (Test-EnvironmentVariablePresent -Name $requiredVariable)) {
        throw "Environment variable $requiredVariable is missing."
    }
}

Write-Host "AgentLoom bootstrap profile: $Profile"
if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    $pythonCommand = @($venvPython)
}
else {
    $pythonCommand = Resolve-PythonCommand
    Assert-Python312 -Command $pythonCommand
    $sourcePython = $pythonCommand[0]
    $sourcePrefix = @($pythonCommand | Select-Object -Skip 1)
    Invoke-Checked -FilePath $sourcePython -Arguments @(
        $sourcePrefix + @("-m", "venv", $venvRoot)
    ) -Description "Virtual environment creation"
}

Assert-Python312 -Command @($venvPython)
if (-not $SkipPackageInstall) {
    Invoke-Checked -FilePath $venvPython -Arguments @(
        "-m", "pip", "install", "-e", $projectRoot
    ) -Description "AgentLoom package installation"
}
Push-Location $projectRoot
try {
    Invoke-Checked -FilePath $venvPython -Arguments @(
        "-m", "alembic", "-c", (Join-Path $projectRoot "alembic.ini"), "upgrade", "head"
    ) -Description "Database migration"
}
finally {
    Pop-Location
}

if ($Profile -eq "lite") {
    Write-Host "Lite profile ready. Start the control panel with:"
    Write-Host "  .\.venv\Scripts\agentloom tui"
    return
}

Assert-FullProfilePrerequisites
if ([string]::IsNullOrWhiteSpace($EvidencePath)) {
    $EvidencePath = Join-Path $projectRoot "artifacts\agentteams\deployment.json"
}

# Applying resources restores hiclaw-gateway, so provider activation must remain last.
& (Join-Path $agentTeamsRoot "deploy.ps1") -Model $Model -EvidencePath $EvidencePath
if ($Provider -eq "qwen") {
    & (Join-Path $agentTeamsRoot "configure-provider.ps1") `
        -Model $Model -SkipConnectionTest:$SkipProviderConnectionTest
}
elseif ($Provider -eq "deepseek") {
    & (Join-Path $agentTeamsRoot "configure-deepseek-provider.ps1") `
        -Model $Model -SkipConnectionTest:$SkipProviderConnectionTest
}
else {
    & (Join-Path $agentTeamsRoot "configure-stepfun-provider.ps1") `
        -Model $Model -SkipConnectionTest:$SkipProviderConnectionTest
}

$healthEvidencePath = Join-Path $projectRoot "artifacts\agentteams\health.json"
& (Join-Path $PSScriptRoot "health-check.ps1") -EvidencePath $healthEvidencePath
Write-Host "Full profile ready. Element: http://127.0.0.1:18088/#/login"
