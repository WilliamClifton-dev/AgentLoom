# Submission Package Verification

> Status: **live since `v0.1.0`**. The submission ZIP is published at
> <https://github.com/WilliamClifton-dev/AgentLoom/releases/tag/v0.1.0>
> with its SHA-256 in the release body. The verification flow below
> is the public artifact-integrity reference for the package. The optional
> `deploy/signing/sign-submission-package.ps1` cosign wrapper is
> **deprecated**; see the "Why not cosign" section.

This document explains how a reviewer can confirm that the
`AgentLoom v0.1.0` submission package they downloaded matches the
artifact digest published on the corresponding GitHub Release.
This flow verifies artifact integrity and release-page provenance;
it does not independently prove the maintainer's cryptographic identity.

## Release asset integrity: GitHub Releases + SHA-256

The AgentLoom `v0.1.0` package is published as a GitHub Release
asset at
<https://github.com/WilliamClifton-dev/AgentLoom/releases/tag/v0.1.0>.
The release body contains the SHA-256 of the package as printed by
`shasum -a 256` on the maintainer's host at publish time:

```text
Submission ZIP SHA-256:
  0C5DFEB0BA6665609A14129A76CC1C239AED882A17E930C144AA5D3B88F6C306
```

The actual trust statement is narrower:

1. **GitHub Releases** hosts the pinned release page and asset over
   HTTPS.
2. **The release body** contains a SHA-256 written by the maintainer
   for the published ZIP.
3. **A reviewer** downloads the pinned asset, computes its SHA-256,
   and compares it with the release-body value. A mismatch means the
   downloaded bytes are not the bytes identified by that release record.

The `v0.1.0` Git tag is annotated but is not cryptographically signed,
and this repository does not claim that the public CI workflow generated
or uploaded the historical Release asset. The digest is an integrity
check, not a code-signing certificate chain or identity attestation.

## Verify the package

A reviewer with the downloaded ZIP and the published release page
URL performs the following checks. None of them require any
toolchain beyond `curl`, `shasum`, and a POSIX shell.

```bash
# 1. Download the pinned release asset.
curl -fL \
  -o AgentLoom-v0.1.0-preliminary-submission.zip \
  https://github.com/WilliamClifton-dev/AgentLoom/releases/download/v0.1.0/AgentLoom-v0.1.0-preliminary-submission.zip

# 2. Set EXPECTED_SHA256 to the value shown on the pinned release page.
EXPECTED_SHA256=0C5DFEB0BA6665609A14129A76CC1C239AED882A17E930C144AA5D3B88F6C306
ACTUAL_SHA256=$(shasum -a 256 AgentLoom-v0.1.0-preliminary-submission.zip | awk '{print toupper($1)}')
test "$ACTUAL_SHA256" = "$EXPECTED_SHA256"
echo "SHA-256 verified: $ACTUAL_SHA256"
```

A mismatch makes `test` return non-zero. Do not extract or run the
package after a mismatch.

A reviewer who wants to additionally cross-check the build can
run the Lite gate on the unzipped contents:

```bash
unzip AgentLoom-submission-v0.1.0.zip -d /tmp/agentloom
cd /tmp/agentloom
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/mypy src tests
.venv/bin/pip-audit
```

The frozen `v0.1.0` package historically recorded `375 passed / 3 skipped`.
The current `main` checkout may contain additional tests; record the actual
count when re-running the gate instead of treating the historical number as
a release invariant.

## When to re-verify

- Every time you download the package, before extracting.
- After any mirror, CDN, or vendor copy claims to be the same
  package. Do not trust the mirror's claim; always re-run
  `shasum -a 256`.
- Before filing a bug report, to rule out a corrupted download
  on your end.

## Why not cosign

The original P3 follow-up listed "third-party digital signature"
without specifying the technology, and the first implementation
used sigstore cosign (see `deploy/signing/sign-submission-package.ps1`,
now deprecated). On design review against
`docs/architecture/agentloom-architecture.md` the choice was
revisited and the cosign path was rejected. The reasons:

1. **The architecture already specifies the trust model.** Section
   6.1 #4 of the architecture document commits to "第三方默认不可信"
   (third-party default untrusted): every Skill, repository
   content, tool description, and external API response goes
   through boundary validation and accepts a security scan
   before it is admitted. Section 12.1 (Supply Chain Security)
   enumerates what gets scanned (source, license, hash, prompt
   injection, dangerous commands, dynamic downloads, secret
   reads, obfuscation, dependency additions, schema, permission
   claims). None of these checks are tied to a Sigstore / Rekor
   identity. The architecture deliberately does not introduce a
   cosign dependency for runtime or delivery.
2. **The Skill evidence model is self-attested by design.** The
   `SkillInvocationEvidenceRecord`, `ToolCallEventRecord`, and
   `EvidenceRecord` schemas carry a `digest` field; a reviewer
   verifies the evidence by replaying the public-main gate, not
   by checking a Sigstore transparency log. Adding cosign to the
   submission-package flow would introduce a second, parallel
   trust anchor for the same artifact, doubling the surface area
   the operator has to maintain without strengthening the
   primary anchor.
3. **The current requirement is artifact integrity, not identity
   attestation.** GitHub Releases provides a stable public location
   for the page and asset, while the published SHA-256 lets reviewers
   detect byte changes. It must not be described as a signed package
   or as proof of maintainer identity.

For operators who still want a sigstore path — for example to
satisfy an internal corporate requirement — the
`deploy/signing/sign-submission-package.ps1` wrapper is kept
as an opt-in, deprecated helper. It produces a cosign signature
and certificate under `artifacts/signatures/`; the script
**must not** be wired into the public-main CI workflow. See
`deploy/signing/DEPRECATED.md` for the exact policy.

## Cross-references

- The release page: <https://github.com/WilliamClifton-dev/AgentLoom/releases/tag/v0.1.0>
- The submission manifest: `docs/competition/submission-package-manifest.json`
- The architecture's trust model: `docs/architecture/agentloom-architecture.md`
  (sections 6.1 #4, 12.1, 12.4, ADR-005)
- The second-host runbook: `docs/deployment/second-host-bootstrap.md`
- The deprecated cosign wrapper: `deploy/signing/sign-submission-package.ps1`
  and `deploy/signing/DEPRECATED.md`
