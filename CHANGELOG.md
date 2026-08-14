# Changelog

All notable changes to AgentLoom are documented in this file.

The project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Project branding asset and a timed Chinese competition-demo narration script.
- Stable Capability, Provider, and Consumer contracts with replayable causal task
  and governed ToolCall events.
- Authenticated Higress-to-Policy-Broker deployment, persistent Grant replay
  protection, and a pinned Docker pytest sandbox for untrusted tests.
- Administrator-defined, secret-free OpenAI-compatible Provider Profiles with
  model-free validation and explicit paid-probe activation.
- AgentTeams Investigator-to-Verifier governed delegation evidence using
  MiniMax and exactly one successful sandboxed ToolCall.
- Deterministic preliminary submission artifacts and aligned English/Chinese
  public repository entry points.

### Changed

- The Skill catalog now publishes `code-review-and-quality`; the other four
  imported upstream Skills remain quarantined.
- Current paid maintainer evidence uses `minimax-cn / MiniMax-M2.5`. Qwen,
  DeepSeek, and StepFun evidence is retained as historical and those paid paths
  are disabled pending quota and explicit reauthorization.

### Security

- Worker identity is enforced by Higress allowlists; Manager remains MCP-free.
- Tool execution now binds consumer, parameters, workspace, nonce consumption,
  immutable runner image, and replayable evidence digests.

### Known limitations

- Upstream PR #1141 remains open.
- The P0 package is complete, but the real recording, public upload,
  repository release/tag, and competition-page submission remain pending.
- Full bootstrap still needs validation on additional clean Windows machines.

## [0.1.0-rc.1] - 2026-08-09

### Added

- AgentTeams `v1.1.2` Manager, Investigator, Implementer, and Verifier
  collaboration with role-owned Matrix evidence.
- Governed Skill contracts, three-layer detection, signed one-time execution
  grants, Policy Broker MCP transport, and append-only evidence records.
- Deterministic offline repair cases and independent visible, hidden, static,
  patch-scope, failure, retry, and rollback verification.
- Textual operator panel for cases, roles, evidence, approvals, and rollback
  results.
- Fail-closed live repair, L2 Human approval, and rollback evidence collectors.
- Public-output replay mode that redacts local filesystem paths and does not call
  a paid model.

### Security

- Model credentials remain outside the repository and are not delegated to
  Workers.
- Tool execution is bound to short-lived grants, exact parameters, paths,
  approval state, and replay protection.
- Release gates include dependency auditing and tracked-file/history secret
  scanning.

### Known limitations

- The five imported upstream Skills remain quarantined and are not published
  runtime assets.
- Verified repair results are not yet written to a real external business
  repository as an Issue, pull request, or comment.
- Full AgentTeams bootstrap has not yet been validated on additional clean
  Windows machines and is not packaged as a standalone one-container install.
- The AgentTeams `humanMembers` fix is proposed in upstream PR #1141 and has not
  been merged by its maintainers.
- The public competition video and final submission package are not part of this
  release candidate.

[Unreleased]: https://github.com/WilliamClifton-dev/AgentLoom/compare/v0.1.0-rc.1...HEAD
[0.1.0-rc.1]: https://github.com/WilliamClifton-dev/AgentLoom/releases/tag/v0.1.0-rc.1
