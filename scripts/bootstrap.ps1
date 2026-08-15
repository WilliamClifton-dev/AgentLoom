[CmdletBinding()]
param(
    [ValidateSet("lite", "full")]
    [string]$Profile = "lite",
    [ValidateSet("none", "qwen", "deepseek", "stepfun", "minimax", "custom")]
    [string]$Provider = "none",
    [ValidateSet("qwen3.7-plus", "deepseek-v4-flash", "deepseek-v4-pro", "step-3.7-flash", "MiniMax-M2.5")]
    [string]$Model = "qwen3.7-plus",
    [string]$ProviderProfilePath = "",
    [string]$PythonExecutable = "",
    [string]$EvidencePath = "",
    [switch]$SkipPackageInstall,
    [switch]$SkipProviderConnectionTest,
    [switch]$RunProviderConnectionTest
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

function Get-ValidatedCustomProviderProfile {
    if ([string]::IsNullOrWhiteSpace($ProviderProfilePath)) {
        throw "The custom provider requires -ProviderProfilePath."
    }

    $validationArguments = @(
        "-ProfilePath", $ProviderProfilePath,
        "-ValidateOnly"
    )
    $validationOutput = @(
        & (Join-Path $agentTeamsRoot "configure-openai-compatible-provider.ps1") @validationArguments
    )
    if ($validationOutput.Count -eq 0) {
        throw "Provider Profile validation returned no result."
    }
    try {
        return ($validationOutput -join [Environment]::NewLine) |
            ConvertFrom-Json -AsHashtable -Depth 10
    }
    catch {
        throw "Provider Profile validation returned an invalid result."
    }
}

function Assert-FullProfilePrerequisites {
    param([Collections.IDictionary]$CustomProviderProfile)

    if ($PSVersionTable.PSVersion.Major -lt 7) {
        throw "The full profile requires PowerShell 7 or newer."
    }
    if ($Provider -eq "none") {
        throw (
            "The full profile requires -Provider qwen, deepseek, stepfun, " +
            "minimax, or custom."
        )
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
    if ($Provider -eq "minimax" -and $Model -ne "MiniMax-M2.5") {
        throw "The minimax provider requires -Model MiniMax-M2.5."
    }
    if ($Provider -ne "custom" -and
        -not [string]::IsNullOrWhiteSpace($ProviderProfilePath)) {
        throw "-ProviderProfilePath is valid only with -Provider custom."
    }
    if ($Provider -ne "custom" -and $RunProviderConnectionTest) {
        throw "-RunProviderConnectionTest is valid only with -Provider custom."
    }
    if ($Provider -eq "custom" -and
        $SkipProviderConnectionTest -and $RunProviderConnectionTest) {
        throw "Provider connection test switches conflict."
    }

    $requiredVariable = switch ($Provider) {
        "qwen" { "QWEN_API_KEY" }
        "deepseek" { "DEEPSEEK_API_KEY" }
        "stepfun" { "STEPFUN_API_KEY" }
        "minimax" { "MINIMAX_API_KEY" }
        "custom" { $CustomProviderProfile.apiKeyEnvironmentVariable }
    }
    if (-not (Test-EnvironmentVariablePresent -Name $requiredVariable)) {
        throw "Environment variable $requiredVariable is missing."
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

}

Write-Host "AgentLoom bootstrap profile: $Profile"
if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    $pythonCommand = @($venvPython)
}
else {
    $pythonCommand = @(Resolve-PythonCommand)
    Assert-Python312 -Command $pythonCommand
    $sourcePython = $pythonCommand[0]
    $sourcePrefix = @($pythonCommand | Select-Object -Skip 1)
    Invoke-Checked -FilePath $sourcePython -Arguments @(
        $sourcePrefix + @("-m", "venv", $venvRoot)
    ) -Description "Virtual environment creation"
}

Assert-Python312 -Command @($venvPython)
Invoke-Checked -FilePath $venvPython -Arguments @(
    "-m", "pip", "install", "--upgrade", "pip>=26.1.2,<27"
) -Description "pip security baseline upgrade"
if (-not $SkipPackageInstall) {
    Invoke-Checked -FilePath $venvPython -Arguments @(
        "-m", "pip", "install", "--no-cache-dir",
        "--retries", "10", "--timeout", "60", "-e", $projectRoot
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

$customProviderProfile = $null
if ($Provider -eq "custom") {
    $customProviderProfile = Get-ValidatedCustomProviderProfile
    $Model = $customProviderProfile.modelId
}
Assert-FullProfilePrerequisites -CustomProviderProfile $customProviderProfile
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
elseif ($Provider -eq "stepfun") {
    & (Join-Path $agentTeamsRoot "configure-stepfun-provider.ps1") `
        -Model $Model -SkipConnectionTest:$SkipProviderConnectionTest
}
elseif ($Provider -eq "minimax") {
    & (Join-Path $agentTeamsRoot "configure-minimax-provider.ps1") `
        -Model $Model -SkipConnectionTest:$SkipProviderConnectionTest
}
else {
    $configurationArguments = @("-ProfilePath", $ProviderProfilePath)
    if ($Provider -eq "custom" -and $RunProviderConnectionTest) {
        $configurationArguments += "-RunConnectionTest"
    }
    & (Join-Path $agentTeamsRoot "configure-openai-compatible-provider.ps1") `
        @configurationArguments
}

$healthEvidencePath = Join-Path $projectRoot "artifacts\agentteams\health.json"
& (Join-Path $PSScriptRoot "health-check.ps1") -EvidencePath $healthEvidencePath
Write-Host "Full profile ready. Element: http://127.0.0.1:18088/#/login"
