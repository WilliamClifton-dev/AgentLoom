[CmdletBinding()]
param(
    [string]$ControllerContainer = "hiclaw-controller",
    [string]$EvidencePath = ""
)

$ErrorActionPreference = "Stop"
$deployRoot = $PSScriptRoot
$lock = Get-Content -Raw -LiteralPath (Join-Path $deployRoot "version-lock.json") |
    ConvertFrom-Json
$runtimePath = Join-Path $deployRoot "configure-policy-broker-gateway.sh"
$gatewayAssertion = [Environment]::GetEnvironmentVariable("AGENTLOOM_GATEWAY_ASSERTION", "Process")
if ($gatewayAssertion -notmatch "^[A-Fa-f0-9]{64}$") {
    throw "AGENTLOOM_GATEWAY_ASSERTION must be a 64-character hex process secret"
}

function Invoke-Docker {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments,
        [string]$StandardInput = ""
    )

    if ([string]::IsNullOrEmpty($StandardInput)) {
        $output = & docker @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    else {
        $startInfo = [Diagnostics.ProcessStartInfo]::new()
        $startInfo.FileName = "docker"
        $startInfo.UseShellExecute = $false
        $startInfo.RedirectStandardInput = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        foreach ($argument in $Arguments) {
            [void]$startInfo.ArgumentList.Add($argument)
        }

        $process = [Diagnostics.Process]::new()
        $process.StartInfo = $startInfo
        try {
            if (-not $process.Start()) {
                throw "Unable to start docker"
            }
            $standardOutputTask = $process.StandardOutput.ReadToEndAsync()
            $standardErrorTask = $process.StandardError.ReadToEndAsync()
            $process.StandardInput.Write($StandardInput)
            $process.StandardInput.Close()
            $process.WaitForExit()
            $standardOutput = $standardOutputTask.GetAwaiter().GetResult().Trim()
            $standardError = $standardErrorTask.GetAwaiter().GetResult().Trim()
            $exitCode = $process.ExitCode
            $output = @($standardOutput, $standardError) | Where-Object {
                -not [string]::IsNullOrWhiteSpace($_)
            }
        }
        finally {
            $process.Dispose()
        }
    }
    if ($exitCode -ne 0) {
        throw "docker $($Arguments[0]) failed: $($output -join [Environment]::NewLine)"
    }
    return @($output)
}

$container = (Invoke-Docker -Arguments @(
    "inspect", $ControllerContainer, "--format", "{{.State.Running}}|{{.Config.Image}}"
) | Select-Object -First 1).Trim().Split("|", 2)
if ($container[0] -ne "true") {
    throw "$ControllerContainer is not running"
}
if ($container[1] -ne $lock.images.controller.reference) {
    throw "$ControllerContainer does not use the pinned AgentTeams controller image"
}

$actualDigest = (Invoke-Docker -Arguments @(
    "image", "inspect", $lock.images.controller.reference, "--format", "{{.Id}}"
) | Select-Object -First 1).Trim()
if ($actualDigest -ne $lock.images.controller.digest) {
    throw "AgentTeams controller image digest does not match version-lock.json"
}

$runtime = Get-Content -Raw -LiteralPath $runtimePath
$runtime = $runtime.Replace("`r`n", "`n")
$runtime = $runtime.Replace("__AGENTLOOM_GATEWAY_ASSERTION__", $gatewayAssertion)
$output = Invoke-Docker `
    -Arguments @("exec", "-i", $ControllerContainer, "bash", "-s") `
    -StandardInput $runtime
$evidenceJson = ($output | Out-String).Trim()
$evidence = $evidenceJson | ConvertFrom-Json

$expectedConsumers = @(
    "worker-agentloom-investigator",
    "worker-agentloom-implementer",
    "worker-agentloom-verifier"
)
if ($evidence.schemaVersion -ne "agentloom.higress-policy-broker/v1alpha1") {
    throw "Unexpected Higress Policy Broker evidence schema"
}
if ($evidence.managerAuthorized -ne $false) {
    throw "Manager authorization must remain disabled"
}
if ((@($evidence.allowedConsumers) | ConvertTo-Json -Compress) -cne
    ($expectedConsumers | ConvertTo-Json -Compress)) {
    throw "Higress Policy Broker consumer allowlist does not match the AgentLoom team"
}

if (-not [string]::IsNullOrWhiteSpace($EvidencePath)) {
    $resolvedEvidence = [IO.Path]::GetFullPath($EvidencePath)
    $evidenceDirectory = Split-Path -Parent $resolvedEvidence
    if ($evidenceDirectory) {
        [void](New-Item -ItemType Directory -Force -Path $evidenceDirectory)
    }
    [IO.File]::WriteAllText(
        $resolvedEvidence,
        ($evidence | ConvertTo-Json -Depth 10),
        [Text.UTF8Encoding]::new($false)
    )
}

$evidence | ConvertTo-Json -Depth 10
