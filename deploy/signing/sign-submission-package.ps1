<#
.SYNOPSIS
    [DEPRECATED] Sign the public submission package with sigstore cosign.

.DESCRIPTION
    DEPRECATED as of 2026-08-22. The AgentLoom project's artifact-integrity
    reference for the submission package is **GitHub Releases + SHA-256**,
    not sigstore cosign. See `docs/security/signing-submission.md`
    and `deploy/signing/DEPRECATED.md` for the design rationale.

    This script is kept as an opt-in helper for operators with an
    internal corporate requirement that mandates Sigstore / Rekor. It
    must not be wired into the public-main CI workflow. If you find
    yourself wanting to do that, update `docs/security/signing-submission.md`
    instead so the architecture's trust model is preserved.

    The original implementation was committed in `b30c303` and is
    preserved here for operators who still want a cosign path. It
    wraps `cosign sign-blob` to produce a detached signature for the
    public submission ZIP referenced in
    `docs/competition/submission-package-manifest.json`. The signature
    is published alongside the package in `artifacts/signatures/`.

.PARAMETER PackagePath
    Path to the submission ZIP. Defaults to the manifest's package
    file resolved from the workspace root.

.PARAMETER SignatureOut
    Output path for the detached signature. Defaults to
    `artifacts/signatures/<package>.sig`.

.PARAMETER CertificateOut
    Output path for the optional signing certificate. Defaults to
    `artifacts/signatures/<package>.cert`.

.PARAMETER CosignBin
    Path to the cosign binary. Defaults to `cosign` on PATH.

.EXAMPLE
    pwsh -File deploy/signing/sign-submission-package.ps1 `
        -PackagePath artifacts/competition/AgentLoom-submission-v0.1.0.zip

.EXAMPLE
    # Keyless signing with Sigstore Fulcio + Rekor:
    $env:AGENTLOOM_COSIGN_KEY = "keyless://"
    pwsh -File deploy/signing/sign-submission-package.ps1
#>
[CmdletBinding()]
param(
    [string]$PackagePath = "",
    [string]$SignatureOut = "",
    [string]$CertificateOut = "",
    [string]$CosignBin = "cosign"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Write-Warning "deploy/signing/sign-submission-package.ps1 is DEPRECATED. See docs/security/signing-submission.md and deploy/signing/DEPRECATED.md. The project's artifact-integrity reference is GitHub Releases + SHA-256, not sigstore cosign. This script is kept only as an opt-in helper."

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$manifestPath = Join-Path $projectRoot "docs/competition/submission-package-manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw "Submission manifest is missing: $manifestPath"
}

# Resolve the package path. The manifest is JSON; we just look for the
# first key under "files" or "package" that ends with .zip. Operators may
# pass an explicit path to skip the search.
if ([string]::IsNullOrEmpty($PackagePath)) {
    $manifestRaw = Get-Content -LiteralPath $manifestPath -Raw
    $candidates = [regex]::Matches($manifestRaw, '"([^"]+\.zip)"') |
        ForEach-Object { $_.Groups[1].Value }
    $resolved = $candidates |
        Where-Object { Test-Path -LiteralPath (Join-Path $projectRoot $_) } |
        Select-Object -First 1
    if ($null -eq $resolved) {
        throw "No submission ZIP found next to $manifestPath. Build the package first."
    }
    $PackagePath = Join-Path $projectRoot $resolved
}
if (-not (Test-Path -LiteralPath $PackagePath)) {
    throw "Package not found: $PackagePath"
}

# Resolve signature / certificate output paths.
$packageName = Split-Path -Leaf $PackagePath
if ([string]::IsNullOrEmpty($SignatureOut)) {
    $sigDir = Join-Path $projectRoot "artifacts/signatures"
    New-Item -ItemType Directory -Path $sigDir -Force | Out-Null
    $SignatureOut = Join-Path $sigDir ($packageName + ".sig")
    $CertificateOut = Join-Path $sigDir ($packageName + ".cert")
}

# Verify cosign is available.
$cosign = Get-Command $CosignBin -ErrorAction SilentlyContinue
if ($null -eq $cosign) {
    throw "cosign not found on PATH (CosignBin='$CosignBin'). Install from https://docs.sigstore.dev/cosign/system_config/installation/ before running this script."
}

# Resolve signing key. The empty default would silently succeed without
# a real identity binding; require either an explicit path or the
# `keyless://` literal.
$key = $env:AGENTLOOM_COSIGN_KEY
if ([string]::IsNullOrEmpty($key)) {
    throw @"
AGENTLOOM_COSIGN_KEY is not set. Set it to either:
  - a path to a cosign.key file (keyed flow), or
  - the literal string 'keyless://' to sign with the Sigstore Fulcio CA.
"@
}

Write-Host "[sign-submission] cosign = $($cosign.Source)"
Write-Host "[sign-submission] package = $PackagePath"
Write-Host "[sign-submission] signature = $SignatureOut"
Write-Host "[sign-submission] certificate = $CertificateOut"
Write-Host "[sign-submission] key = $key"

# Build the cosign argument list. We deliberately pass the path as a
# separate argument, never via Invoke-Expression, so a malicious
# filename cannot inject PowerShell syntax.
$cosignArgs = @("sign-blob", "--yes", "--output-signature", $SignatureOut)
if ($key -ne "keyless://") {
    $cosignArgs += @("--key", $key)
    if (Test-Path -LiteralPath $CertificateOut -ErrorAction SilentlyContinue) {
        $cosignArgs += @("--output-certificate", $CertificateOut)
    }
}
$cosignArgs += @($PackagePath)

Write-Host "[sign-submission] running: $CosignBin $($cosignArgs -join ' ')"
& $CosignBin @cosignArgs
if ($LASTEXITCODE -ne 0) {
    throw "cosign sign-blob failed with exit code $LASTEXITCODE"
}

# Verify the signature was produced and is non-empty.
if (-not (Test-Path -LiteralPath $SignatureOut)) {
    throw "cosign did not produce a signature at $SignatureOut"
}
$sigBytes = (Get-Item -LiteralPath $SignatureOut).Length
if ($sigBytes -lt 64) {
    throw "Signature at $SignatureOut is suspiciously small ($sigBytes bytes); aborting."
}

Write-Host "[sign-submission] OK; signature is $sigBytes bytes"
Write-Host "Verify with: $CosignBin verify-blob --signature $SignatureOut --certificate $CertificateOut $PackagePath"
