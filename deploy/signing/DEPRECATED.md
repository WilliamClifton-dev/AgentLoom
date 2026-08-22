# Why `sign-submission-package.ps1` is deprecated

> Status: **deprecated as of 2026-08-22**. Do not wire this script
> into the public-main CI workflow. Do not sign any release
> artifact with it for `v0.1.0` or later. The script is kept in the
> tree only as an opt-in helper for operators with an internal
> corporate requirement that mandates sigstore / Rekor.

## Why it was deprecated

The original P3 follow-up listed "third-party digital signature"
without specifying the technology. The first implementation
wrapped sigstore cosign and was committed in commit `b30c303`. On
design review against `docs/architecture/agentloom-architecture.md`
the choice was revisited and the cosign path was rejected. See
`docs/security/signing-submission.md` § "Why not cosign" for the
full reasoning. The three points in short:

1. The architecture's trust model is "evidence + self-attested
   digest + reproducible replay" (sections 6.1 #4, 12.1, 12.4,
   ADR-005). Cosign is not in that model.
2. The Skill evidence schemas carry their own digest; adding
   cosign to the submission flow would duplicate the trust
   anchor for the same artifact.
3. The "third party" already exists in the form of GitHub
   Releases with a published SHA-256. The release page is the
   trust anchor; the package bytes bind to it via the SHA-256 in
   the release body.

## What this means in practice

- The third-party trust anchor for `v0.1.0` (and every future
  release) is **GitHub Releases + SHA-256**. See
  `docs/security/signing-submission.md` for the verifier flow.
- `deploy/signing/sign-submission-package.ps1` remains in the
  tree as an opt-in helper. The script still works; it just is
  not the project's official signing path.
- The CI workflow in `.github/workflows/ci.yml` **must not**
  call this script. If you find yourself wanting to, the
  correct response is to update
  `docs/security/signing-submission.md` instead so the
  architecture's trust model is preserved.

## When to delete this script

Delete `sign-submission-package.ps1` and this `DEPRECATED.md` when
no operator has asked for an opt-in cosign path in the last six
release cycles. At that point the script has been unused long
enough that deleting it is a no-op for the project's users.

## What replaces it (if anything)

Nothing. The default third-party verification flow lives in
`docs/security/signing-submission.md`. An operator with a
genuine sigstore requirement can wrap the GitHub-Releases flow
in their own tooling; they do not need a script in this
repository to do so.
