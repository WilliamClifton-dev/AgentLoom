[CmdletBinding()]
param(
    [string]$WorkspaceRoot = ".\deploy\sandbox\fixtures\passing-workspace",
    [string]$EvidenceRoot = ".\artifacts\policy-broker\evidence",
    [string]$DatabasePath = ".\artifacts\policy-broker\broker.db",
    [string]$SkillCatalogPath = ".\skills\catalog.json",
    [ValidatePattern("^(?:sha256:[a-f0-9]{64}|[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64})$")]
    [Parameter(Mandatory)][string]$SandboxImage,
    [ValidateRange(1, 65535)]
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))

function Resolve-RepoPath {
    param([Parameter(Mandatory)][string]$Path)

    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path $repoRoot $Path))
}

$resolvedWorkspace = Resolve-RepoPath -Path $WorkspaceRoot
$resolvedEvidenceRoot = Resolve-RepoPath -Path $EvidenceRoot
$resolvedDatabasePath = Resolve-RepoPath -Path $DatabasePath
$resolvedSkillCatalogPath = Resolve-RepoPath -Path $SkillCatalogPath
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $resolvedWorkspace -PathType Container)) {
    throw "The configured Policy Broker workspace does not exist"
}
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    throw "AgentLoom Python runtime was not found at .venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $resolvedSkillCatalogPath -PathType Leaf)) {
    throw "The configured Skill catalog does not exist"
}
$imageInspection = & docker image inspect $SandboxImage --format "{{.Id}}" 2>&1
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace([string]($imageInspection | Select-Object -First 1))) {
    throw "The configured immutable sandbox image is not available locally"
}

$signingKey = [Environment]::GetEnvironmentVariable("AGENTLOOM_POLICY_SIGNING_KEY", "Process")
if ([string]::IsNullOrWhiteSpace($signingKey)) {
    throw "AGENTLOOM_POLICY_SIGNING_KEY must be present in the process environment"
}
$gatewayAssertion = [Environment]::GetEnvironmentVariable("AGENTLOOM_GATEWAY_ASSERTION", "Process")
if ([string]::IsNullOrWhiteSpace($gatewayAssertion) -or $gatewayAssertion.Length -lt 32) {
    throw "AGENTLOOM_GATEWAY_ASSERTION must be present in the process environment"
}

[void](New-Item -ItemType Directory -Force -Path $resolvedEvidenceRoot)
$databaseDirectory = Split-Path -Parent $resolvedDatabasePath
if ($databaseDirectory) {
    [void](New-Item -ItemType Directory -Force -Path $databaseDirectory)
}
$databaseUrlPath = $resolvedDatabasePath.Replace("\", "/")

$env:AGENTLOOM_TOOL_WORKSPACE = $resolvedWorkspace
$env:AGENTLOOM_TOOL_EVIDENCE_ROOT = $resolvedEvidenceRoot
$env:AGENTLOOM_DATABASE_URL = "sqlite:///$databaseUrlPath"
$env:AGENTLOOM_SKILL_CATALOG = $resolvedSkillCatalogPath
$env:AGENTLOOM_SANDBOX_BACKEND = "docker"
$env:AGENTLOOM_SANDBOX_IMAGE = $SandboxImage
Remove-Item Env:AGENTLOOM_ALLOW_HOST_TEST_EXECUTION -ErrorAction SilentlyContinue
$env:AGENTLOOM_GATEWAY_ASSERTION = $gatewayAssertion
$env:AGENTLOOM_MCP_TRANSPORT = "streamable-http"
$env:AGENTLOOM_MCP_HOST = "0.0.0.0"
$env:AGENTLOOM_MCP_PORT = [string]$Port
$env:AGENTLOOM_MCP_PUBLIC_HOST = "host.docker.internal"

& $venvPython @("-m", "agentloom.policy_mcp")
if ($LASTEXITCODE -ne 0) {
    throw "Policy Broker exited with code $LASTEXITCODE"
}
