[CmdletBinding()]
param(
    [ValidatePattern("^(?:sha256:[a-f0-9]{64}|[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64})$")]
    [Parameter(Mandatory)][string]$SandboxImage,
    [Parameter(Mandatory)][string]$CaseRoot,
    [ValidatePattern("^task[0-9]+$")]
    [string]$RunNamespace = "task16",
    [string]$WorkspaceRoot = ".\deploy\sandbox\fixtures\passing-workspace",
    [string]$RunRoot = "",
    [ValidateRange(1, 65535)]
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$verifierContainer = "hiclaw-worker-agentloom-verifier"
$implementerContainer = "hiclaw-worker-agentloom-implementer"

function Resolve-RepoPath {
    param([Parameter(Mandatory)][string]$Path)

    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path $repoRoot $Path))
}

function Invoke-AgentLoomPython {
    param([Parameter(Mandatory)][string[]]$Arguments)

    & $venvPython @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "AgentLoom fixture command failed"
    }
}

function Stop-PolicyBrokerListener {
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 1) {
        throw "Multiple listeners found on the Policy Broker port"
    }
    if ($listeners.Count -eq 0) {
        return
    }
    $listenerPid = $listeners[0].OwningProcess
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$listenerPid"
    if ($null -eq $process -or $process.CommandLine -notmatch "agentloom\.policy_mcp") {
        throw "The Policy Broker port is owned by an unexpected process"
    }
    Stop-Process -Id $listenerPid
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(15)
    while (
        (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) -and
        [DateTimeOffset]::UtcNow -lt $deadline
    ) {
        Start-Sleep -Milliseconds 200
    }
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        throw "The previous Policy Broker listener did not stop"
    }
}

function Wait-PolicyBroker {
    param([Parameter(Mandatory)][Diagnostics.Process]$Process)

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
    do {
        if ($Process.HasExited) {
            throw "Policy Broker exited during startup"
        }
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen `
            -ErrorAction SilentlyContinue
        if (-not $listener) {
            Start-Sleep -Milliseconds 250
        }
    } while (-not $listener -and [DateTimeOffset]::UtcNow -lt $deadline)
    if (-not $listener) {
        throw "Policy Broker did not open its listener"
    }
}

function Invoke-Mcporter {
    param(
        [Parameter(Mandatory)][string]$Container,
        [Parameter(Mandatory)][string]$Tool,
        [Parameter(Mandatory)][string]$ArgumentsJson
    )

    $shell = @'
payload="$(cat)"
exec mcporter call "agentloom-policy-broker.__TOOL__" --args "$payload" --output json
'@.Replace("__TOOL__", $Tool)
    $raw = $ArgumentsJson | & docker exec -i $Container sh -lc $shell 2>&1
    return [pscustomobject]@{
        ExitCode = $LASTEXITCODE
        Text = ($raw | Out-String).Trim()
    }
}

function Clear-RunSecrets {
    foreach ($name in @(
        "AGENTLOOM_POLICY_SIGNING_KEY",
        "AGENTLOOM_GATEWAY_ASSERTION"
    )) {
        [Environment]::SetEnvironmentVariable($name, $null, "Process")
    }
}

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    throw "AgentLoom Python runtime is unavailable"
}
$resolvedWorkspace = Resolve-RepoPath -Path $WorkspaceRoot
if (-not (Test-Path -LiteralPath $resolvedWorkspace -PathType Container)) {
    throw "Sandbox E2E workspace is unavailable"
}
$resolvedCaseRoot = Resolve-RepoPath -Path $CaseRoot
if (-not (Test-Path -LiteralPath $resolvedCaseRoot -PathType Container)) {
    throw "Sandbox E2E Case is unavailable"
}
$runId = "$RunNamespace-" + [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmss") + `
    "-" + [Guid]::NewGuid().ToString("N").Substring(0, 8)
$resolvedRunRoot = if ([string]::IsNullOrWhiteSpace($RunRoot)) {
    Join-Path $repoRoot "artifacts\policy-broker\$RunNamespace\$runId"
} else {
    Resolve-RepoPath -Path $RunRoot
}
if (Test-Path -LiteralPath $resolvedRunRoot) {
    throw "Sandbox E2E run root already exists"
}
[void](New-Item -ItemType Directory -Path $resolvedRunRoot)
$databasePath = Join-Path $resolvedRunRoot "broker.db"
$databaseUrlPath = $databasePath.Replace("\", "/")
$databaseUrl = "sqlite:///$databaseUrlPath"
$contextPath = Join-Path $resolvedRunRoot "context.json"
$evidenceRoot = Join-Path $resolvedRunRoot "evidence"
$brokerStdout = Join-Path $resolvedRunRoot "broker.stdout.log"
$brokerStderr = Join-Path $resolvedRunRoot "broker.stderr.log"
$directVerificationPath = Join-Path $resolvedRunRoot "direct-verification.json"
$runEvidencePath = Join-Path $resolvedRunRoot "run-evidence.json"

Invoke-AgentLoomPython -Arguments @(
    "-m", "agentloom.sandbox_e2e", "prepare",
    "--database-url", $databaseUrl,
    "--workspace", $resolvedWorkspace,
    "--skill-catalog", (Join-Path $repoRoot "skills\catalog.json"),
    "--case-root", $resolvedCaseRoot,
    "--output", $contextPath
)
$context = Get-Content -Raw -LiteralPath $contextPath | ConvertFrom-Json

Stop-PolicyBrokerListener
$signingKey = [Convert]::ToHexString(
    [Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
)
$gatewayAssertion = [Convert]::ToHexString(
    [Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
)
[Environment]::SetEnvironmentVariable(
    "AGENTLOOM_POLICY_SIGNING_KEY",
    $signingKey,
    "Process"
)
[Environment]::SetEnvironmentVariable(
    "AGENTLOOM_GATEWAY_ASSERTION",
    $gatewayAssertion,
    "Process"
)
try {
    $broker = Start-Process `
        -FilePath "powershell.exe" `
        -WindowStyle Hidden `
        -PassThru `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $brokerStdout `
        -RedirectStandardError $brokerStderr `
        -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", (Join-Path $PSScriptRoot "start-policy-broker.ps1"),
            "-WorkspaceRoot", $resolvedWorkspace,
            "-EvidenceRoot", $evidenceRoot,
            "-DatabasePath", $databasePath,
            "-SkillCatalogPath", (Join-Path $repoRoot "skills\catalog.json"),
            "-SandboxImage", $SandboxImage,
            "-Port", [string]$Port
        )
    Wait-PolicyBroker -Process $broker
    $gatewayOutput = & (Join-Path $PSScriptRoot "configure-policy-broker-gateway.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Policy Broker gateway configuration failed"
    }
    $gatewayEvidence = ($gatewayOutput | Out-String) | ConvertFrom-Json
    if ($gatewayEvidence.gatewayAssertionConfigured -ne $true) {
        throw "Policy Broker gateway assertion was not configured"
    }
}
finally {
    Clear-RunSecrets
    $signingKey = $null
    $gatewayAssertion = $null
}

$directTask = $context.tasks.direct
$issueJson = @{
    request = $directTask.issuanceRequest
} | ConvertTo-Json -Depth 30 -Compress
$issued = Invoke-Mcporter `
    -Container $verifierContainer `
    -Tool "issue_skill_execution_grant" `
    -ArgumentsJson $issueJson
if ($issued.ExitCode -ne 0) {
    throw "Verifier Grant issuance failed"
}
try {
    $signedGrant = $issued.Text | ConvertFrom-Json
}
catch {
    throw "Verifier Grant issuance returned invalid JSON"
}
$envelopeJson = @{
    request = @{
        signedGrant = $signedGrant
        toolRequest = $directTask.toolRequest
    }
} | ConvertTo-Json -Depth 50 -Compress
$wrongConsumer = Invoke-Mcporter `
    -Container $implementerContainer `
    -Tool "execute_governed_tool" `
    -ArgumentsJson $envelopeJson
if (
    $wrongConsumer.ExitCode -eq 0 -or
    $wrongConsumer.Text -notmatch "consumer is not authorized to execute"
) {
    throw "Implementer was not denied from the Verifier Grant"
}
$executed = Invoke-Mcporter `
    -Container $verifierContainer `
    -Tool "execute_governed_tool" `
    -ArgumentsJson $envelopeJson
if ($executed.ExitCode -ne 0) {
    throw "Verifier sandbox execution failed"
}
try {
    $toolResult = $executed.Text | ConvertFrom-Json
}
catch {
    throw "Verifier sandbox execution returned invalid JSON"
}
if ($toolResult.status -ne "SUCCEEDED") {
    throw "Verifier sandbox execution did not succeed"
}
$replayed = Invoke-Mcporter `
    -Container $verifierContainer `
    -Tool "execute_governed_tool" `
    -ArgumentsJson $envelopeJson
if (
    $replayed.ExitCode -eq 0 -or
    $replayed.Text -notmatch "nonce has already been used"
) {
    throw "Consumed Verifier Grant was not rejected on replay"
}
$signedGrant = $null
$envelopeJson = $null
$issued = $null
$executed = $null
$replayed = $null

Invoke-AgentLoomPython -Arguments @(
    "-m", "agentloom.sandbox_e2e", "verify",
    "--database-url", $databaseUrl,
    "--evidence-root", $evidenceRoot,
    "--context", $contextPath,
    "--expected-image", $SandboxImage,
    "--task", "direct",
    "--output", $directVerificationPath
)
$directVerification = Get-Content -Raw -LiteralPath $directVerificationPath |
    ConvertFrom-Json
$runEvidence = [ordered]@{
    schemaVersion = "agentloom.agentteams-sandbox-e2e/v1alpha1"
    runId = $runId
    verifiedAt = [DateTimeOffset]::UtcNow.ToString("o")
    status = "DIRECT_PASS"
    sandboxImage = $SandboxImage
    workspaceDigest = $context.workspaceDigest
    caseId = $context.caseId
    caseFingerprint = $context.caseFingerprint
    wrongConsumerDenied = $true
    replayDenied = $true
    direct = $directVerification.tasks.direct
}
[IO.File]::WriteAllText(
    $runEvidencePath,
    ($runEvidence | ConvertTo-Json -Depth 10),
    [Text.UTF8Encoding]::new($false)
)
$runEvidence | ConvertTo-Json -Depth 10
