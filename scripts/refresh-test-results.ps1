[CmdletBinding()]
param(
    [string]$VenvPython = "",
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrEmpty($VenvPython)) {
    $exeName = if ($env:OS -eq "Windows_NT") { "Scripts\python.exe" } else { "bin/python" }
    $VenvPython = Join-Path $projectRoot (Join-Path ".venv" $exeName)
}
if ([string]::IsNullOrEmpty($OutputPath)) {
    $OutputPath = Join-Path $projectRoot "test-results.txt"
}
if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "Python not found: $VenvPython. Run bootstrap.ps1 -Profile lite first."
}

Write-Host "[refresh-test-results] running pytest ..."
$pytestOutput = & $VenvPython -m pytest -v --tb=line 2>&1 | Out-String
$exitCode = $LASTEXITCODE

# Normalize timing so two runs that produce the same pass/skip/fail counts and
# the same per-test result order are byte-identical. This keeps
# `git diff --exit-code test-results.txt` from firing on every CI invocation.
$normalized = [regex]::Replace($pytestOutput, " in \d+\.\d+s(?: \(\d+:\d+:\d+\))?", "")
$normalized = [regex]::Replace($normalized, "platform [a-z0-9]+ -- Python [\d\.]+, pytest-[\d\.]+, pluggy-[\d\.]+", "platform normalized -- Python normalized, pytest-normalized, pluggy-normalized")
$normalized = [regex]::Replace($normalized, "^pytest-[\d\.]+; [\s\S]*?rootdir: [^\r\n]+", "pytest header normalized", "Multiline")

$summaryMatch = [regex]::Match(
    $normalized,
    "(?<passed>\d+)\s+passed(?:,\s+(?<skipped>\d+)\s+skipped)?(?:,\s+(?<failed>\d+)\s+failed)?"
)
$passedCount  = if ($summaryMatch.Success -and $summaryMatch.Groups["passed"].Success)  { [int]$summaryMatch.Groups["passed"].Value  } else { 0 }
$skippedCount = if ($summaryMatch.Success -and $summaryMatch.Groups["skipped"].Success) { [int]$summaryMatch.Groups["skipped"].Value } else { 0 }
$failedCount  = if ($summaryMatch.Success -and $summaryMatch.Groups["failed"].Success)  { [int]$summaryMatch.Groups["failed"].Value  } else { 0 }
$collectedMatch = [regex]::Match($normalized, "collected (?<count>\d+) items?")
$collectedCount = if ($collectedMatch.Success) { [int]$collectedMatch.Groups["count"].Value } else { 0 }

# Preserve the existing "Generated" timestamp if the rest of the file is byte-identical.
$existingTimestamp = ""
if (Test-Path -LiteralPath $OutputPath) {
    $existingText = Get-Content -LiteralPath $OutputPath -Raw
    foreach ($line in ($existingText -split "`n")) {
        if ($line -match '^Generated:\s+(.+)$') { $existingTimestamp = $Matches[1] }
    }
}
$timestamp = if ($existingTimestamp) { $existingTimestamp } else { Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz" }

$separator = ("=" * 72)
$headerLines = @(
    $separator,
    "AgentLoom test snapshot",
    "Generated:    $timestamp",
    "Generator:    scripts/refresh-test-results.ps1",
    "Source:       $VenvPython -m pytest -v --tb=line",
    "Exit code:    $exitCode",
    "",
    "Counts parsed from this run:",
    ("  - collected: {0}" -f $collectedCount),
    ("  - passed:    {0}" -f $passedCount),
    ("  - skipped:   {0}" -f $skippedCount),
    ("  - failed:    {0}" -f $failedCount),
    "",
    "Interpretation:",
    ("  - This local run recorded {0} passed / {1} skipped / {2} failed." -f $passedCount, $skippedCount, $failedCount),
    "    The Docker-backed tests are expected to account for the skipped cases",
    "    tests/test_docker_sandbox_live.py and need a Docker daemon.",
    "  - Public-main CI builds an immutable sandbox image and exports",
    ("    AGENTLOOM_TEST_SANDBOX_IMAGE, so all {0} collected tests are expected to run." -f $collectedCount),
    "    CI records the runner-local Full result separately from this Lite file.",
    "  - Timing, platform, and pytest versions are normalized so that two",
    "    runs that produce the same evidence are byte-identical. Only a",
    "    genuine change in pass/skip/fail results or per-test outcomes",
    "    changes this file.",
    "  - Treat this file as a point-in-time local Lite snapshot. The authoritative",
    "    result is the current pytest exit status on the working tree. The CI",
    "    workflow records its Docker-backed Full snapshot in runner-local temp",
    "    storage and does not compare it with this committed Lite file.",
    $separator,
    ""
)
$header = $headerLines -join "`n"
$newFull = $header + $normalized

# Skip the write if bodies (header minus timestamp + normalized pytest output) are unchanged
$newBody = ($newFull -split "`n" | Where-Object { $_ -notmatch '^Generated:' }) -join "`n"
$existingBody = ""
if (Test-Path -LiteralPath $OutputPath) {
    $existingText = Get-Content -LiteralPath $OutputPath -Raw
    $existingBody = ($existingText -split "`n" | Where-Object { $_ -notmatch '^Generated:' }) -join "`n"
}
if ($existingBody -and ($existingBody -eq $newBody)) {
    Write-Host "[refresh-test-results] unchanged; left $OutputPath in place"
} else {
    Set-Content -LiteralPath $OutputPath -Value $newFull -Encoding utf8 -NoNewline
    Write-Host ("[refresh-test-results] wrote {0} (collected={1} passed={2} skipped={3} failed={4} exit={5})" -f $OutputPath, $collectedCount, $passedCount, $skippedCount, $failedCount, $exitCode)
}

if ($exitCode -ne 0) {
    throw "pytest exited with $exitCode. test-results.txt was still written, but the gate is not green."
}
