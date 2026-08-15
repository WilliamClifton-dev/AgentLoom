# Preliminary submission artifacts specification

## Purpose

Generate and verify the complete AgentLoom preliminary-round P0 submission
package required by `docs/architecture/agentloom-architecture.md`. P0 materials
take priority over remaining prototype bonuses.

## Authoritative sources

Use this precedence order when facts conflict:

1. Competition handbook and official 19-slide framework.
2. Immutable local evidence and current public GitHub state.
3. `docs/competition/agentloom-preliminary-submission.md`.
4. `docs/architecture/agentloom-architecture.md`.
5. README and other repository documentation.
6. Existing PPT/PDF drafts.

## Required outputs

1. `01-AgentLoom-作品简介.pdf`: <=500 Chinese characters and covers scenario,
   solution, innovation, reuse/open value, and current verified progress.
2. `02-AgentLoom-初赛方案.pptx`: official 19-slide framework, preserved
   master/layouts, current content, and `[Sources]` speaker notes on every slide.
3. `03-AgentLoom-初赛方案.pdf`: PDF exported from the accepted PPTX with the same
   19 pages and no rendering regression.
4. `04-Agent-Identity清单.pdf`: Manager boundary and the three business Agent
   identities, including role, capabilities, inputs, outputs, dependencies,
   decision boundary, and trace fields.
5. `05-核心Skill清单.pdf`: core Skill provenance, contract, dependencies, failure
   behavior, safety boundary, reuse value, and honest lifecycle status.
6. `06-开源与第三方依赖说明.pdf`: license/provenance and the adoption decision,
   necessity, alternative, and migration cost for MCP, RAG, observability,
   official cloud Skills, and other recommended tools.
7. `07-L2审批与回滚证据.pdf`: redacted, source-backed approval and rollback
   summary. It must keep PR #1141 as `OPEN` unless a fresh read-only check proves
   otherwise.
8. `README.txt`: package index, evidence baseline, reproduction pointers, and
   honesty boundaries.
9. `AgentLoom-初赛提交包.zip`: contains only the accepted numbered outputs and
   `README.txt`; no code tree, credentials, raw Matrix export, signed Grant,
   Worker logs, cache, or private absolute path.

The public Demo link and final human-recorded video remain an external human
checkpoint when no real recording is available. They cannot be simulated.

## Presentation content baseline

- AgentTeams v1.1.2 is the collaboration runtime; AgentLoom is the governance
  control plane.
- The primary current run is Administrator -> Manager -> Investigator ->
  Verifier -> Higress -> Policy Broker -> Docker.
- MiniMax `minimax-cn / MiniMax-M2.5` is the only model Provider in that run.
- Exactly one governed Verifier ToolCall succeeded through
  `sandboxed-test-runner/docker-sandbox`.
- Full quality gate: 323 passed, 2 failed (TUI tests, non-blocking), 3 skipped; 
  Ruff, strict mypy, pip-audit, PowerShell/Bash syntax, Alembic single head, 
  diff, and secret scans passed.
- Human L2 approval was independently verified as `APPROVED`.
- `code-review-and-quality` is `PUBLISHED` with matching source and AgentLoom
  Bench evidence; the other four upstream Skills remain `QUARANTINED`. The
  original supply-chain audit Skill remains a specification/prototype rather
  than a published Skill.
- AgentTeams PR #1141 is `OPEN`; final recording and submission upload are not
  complete; the project is an MVP, not production-ready.

## Presentation fidelity and evidence rules

- Import and edit the existing official-template deck with `@oai/artifact-tool`;
  do not rebuild from a blank presentation.
- Preserve slide count, order, masters, layouts, section pages, logos, page
  numbers, typography, and safe margins.
- Do not create fake product screenshots. Use only real, redacted runtime output
  or honest native diagrams/tables tied to repository evidence.
- Every slide must contain a speaker-note `[Sources]` block. Internal claims may
  cite repository paths and immutable evidence digests; external claims cite the
  competition handbook, upstream repository, license, or public PR URL.
- Titles remain single-line; body text stays readable; no clipping, overflow,
  accidental overlap, missing glyph, or font substitution is accepted.

## Acceptance checks

- All nine outputs exist with stable names and open successfully.
- The work summary is <=500 Chinese characters by the documented count method.
- PPTX and its PDF each contain 19 pages and match visually.
- Every slide contains `[Sources]`; no stale `175`, `182`, Qwen-current-run,
  StepFun-current-run, five-Skills-quarantined, merged-PR, all-Skills-published,
  or production-ready claim.
- The PPTX passes template fidelity and overflow checks; PPTX and all PDFs are
  rendered to PNG and visually inspected.
- The ZIP inventory exactly matches the required outputs, can be extracted, and
  extracted SHA-256 values match the originals.
- Source files, final files, and ZIP members pass the high-confidence secret and
  private-path scan.
- Documentation and checklist state match the actual deliverables. Human-only
  video/upload checkpoints remain unchecked until completed by a human.
