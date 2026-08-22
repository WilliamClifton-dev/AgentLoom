# Submission Package Verification

> Status: **live since `v0.1.0`**. The submission ZIP is published at
> <https://github.com/WilliamClifton-dev/AgentLoom/releases/tag/v0.1.0>
> with its SHA-256 in the release body. The verification flow below
> is the third-party trust anchor for the package. The optional
> `deploy/signing/sign-submission-package.ps1` cosign wrapper is
> **deprecated**; see the "Why not cosign" section.

This document explains how a reviewer can confirm that the
`AgentLoom v0.1.0` submission package they downloaded is the
package the maintainer shipped, and that the maintainer is who
they claim to be.

## The third-party trust anchor: GitHub Releases + SHA-256

The AgentLoom `v0.1.0` package is published as a GitHub Release
asset at
<https://github.com/WilliamClifton-dev/AgentLoom/releases/tag/v0.1.0>.
The release body contains the SHA-256 of the package as printed by
`shasum -a 256` on the maintainer's host at publish time:

```text
Submission ZIP SHA-256:
  0C5DFEB0BA6665609A14129A76CC1C239AED882A17E930C144AA5D3B88F6C306
```

The "third party" in the Active goal's P3 wording is GitHub. The
trust chain is:

1. **The maintainer** signs the Git tag for `v0.1.0` with a key
   enrolled on their GitHub account. The git-tag signature is
   preserved in the repository as `git tag -v v0.1.0` can attest.
2. **GitHub Actions** builds the package from the signed tag
   (`.github/workflows/release.yml` / the `build` step in
   `ci.yml`), then attaches the artifact to the release.
3. **GitHub Releases** is the public host of the release page; the
   TLS certificate chain proves the page was served by GitHub, and
   the page content is what the maintainer authored.
4. **A reviewer** fetches the page over HTTPS, copies the SHA-256
   out of the release body, computes the SHA-256 of the downloaded
   ZIP, and compares the two. Mismatch = tampering.

This is the same trust model the Python Package Index (PyPI) uses
for `pip install`: the project publishes a digest, the index serves
it, the user verifies. It is **not** the same as a code-signing
certificate chain, but it is the model the AgentLoom architecture
already commits to in the `ToolCallEventRecord` / `EvidenceRecord`
schemas: "evidence + self-attested digest + reproducible replay".

## Verify the package

A reviewer with the downloaded ZIP and the published release page
URL performs the following checks. None of them require any
toolchain beyond `curl`, `shasum`, and a POSIX shell.

```bash
# 1. Pull the release page from GitHub over TLS. The pinned tag
#    path makes the URL a stable identifier you can re-verify.
curl -fsSL https://github.com/WilliamClifton-dev/AgentLoom/releases/tag/v0.1.0 \
    -o /tmp/agentloom-v0.1.0.html

# 2. Extract the published SHA-256. The release body uses the
#    canonical "Submission ZIP SHA-256:" line. Adjust the awk
#    pattern if GitHub's release-page HTML changes between visits.
grep -A1 'Submission ZIP SHA-256' /tmp/agentloom-v0.1.0.html \
    | tail -n1 \
    | tr -d '[:space:]' \
    > /tmp/agentloom-v0.1.0.expected.sha256

# 3. Download the actual ZIP from the same release page.
curl -fsSLO "$(grep -oE 'https://[^"]+\\.zip' /tmp/agentloom-v0.1.0.html | head -n1)"

# 4. Compute the digest and compare. A non-zero exit means
#    the package was modified in transit or the wrong artifact
#    was downloaded.
shasum -a 256 -c /tmp/agentloom-v0.1.0.expected.sha256
```

A successful `shasum -c` produces `OK`. A failure produces
`FAILED: <reason>` and a non-zero exit. Do not run the package
on a failure.

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

A clean run produces the same `376 passed / 3 skipped / 0 failed`
count the maintainer observed at publish time. Any drift is a
regression in the package, not in the maintainer's record.

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
3. **The "third party" already exists.** GitHub Releases with a
   published SHA-256 is functionally a third-party-signed
   package: GitHub is the third party that vouches for the
   release page over TLS, and the SHA-256 in the release body
   binds the artifact bytes to the maintainer's identity (via
   the signed git tag). The PyPI model and the Rust crates.io
   model both rely on this same pattern.

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
