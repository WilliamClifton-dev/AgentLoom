[CmdletBinding()]
param(
    [ValidatePattern("^[a-z0-9][a-z0-9._/-]*:[a-z0-9][a-z0-9._-]*$")]
    [string]$Tag = "agentloom-pytest-runner:local",
    [string]$OutputPath = ".\artifacts\sandbox\runner-image.txt"
)

$ErrorActionPreference = "Stop"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$resolvedOutputPath = if ([IO.Path]::IsPathRooted($OutputPath)) {
    [IO.Path]::GetFullPath($OutputPath)
} else {
    [IO.Path]::GetFullPath((Join-Path $repoRoot $OutputPath))
}

& docker build --pull=false --tag $Tag --file (Join-Path $PSScriptRoot "Dockerfile") $PSScriptRoot
if ($LASTEXITCODE -ne 0) {
    throw "Sandbox runner image build failed"
}

$imageId = [string]((& docker image inspect $Tag --format "{{.Id}}" 2>&1) | Select-Object -First 1)
if ($LASTEXITCODE -ne 0 -or $imageId -notmatch "^sha256:[a-f0-9]{64}$") {
    throw "Sandbox runner image did not produce a content-addressed image ID"
}

$outputDirectory = Split-Path -Parent $resolvedOutputPath
if ($outputDirectory) {
    [void](New-Item -ItemType Directory -Force -Path $outputDirectory)
}
[IO.File]::WriteAllText(
    $resolvedOutputPath,
    "$imageId`n",
    [Text.UTF8Encoding]::new($false)
)
Write-Output $imageId
