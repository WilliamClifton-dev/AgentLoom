# Preliminary-plan completion specification

## Objective

Close every evidence-backed initial-stage item in
`docs/architecture/agentloom-architecture.md` without weakening its trust
boundaries or substituting local artifacts for Human/external actions.

## Authoritative completion matrix

| Design item | Current evidence | Status | Owning task |
| --- | --- | --- | --- |
| Five core Skill manifests, one original Skill, at least three real calls | Five upstream manifests exist; one is published; original audit remains a prototype; Task 17 proves one Skill-backed ToolCall | Incomplete | Task 26 |
| L1/L2/L3 DetectionResult and Evidence with Implementer/Verifier separation | Task 23 main-case bundle binds ordered STATIC/DYNAMIC/VERIFICATION results to distinct immutable Evidence; Implementer owns L1/L2 and Verifier owns L3 | Complete | Task 23 |
| Final conclusions link Evidence IDs; success/failure/uncertain ExperienceRecord | Task 23 emits a successful main-task ExperienceRecord referencing every stage; strict contracts cover failed, unsafe, and uncertain terminal outcomes without claiming unexecuted runs | Complete | Task 23 |
| Two-mode comparison and 3-5 evaluation tasks | Two deterministic cases and several live runs exist, but no one versioned comparison matrix | Incomplete | Task 24 |
| Competition video and clean Docker one-command reproduction | Recording runbook exists; real video is Human-owned; clean Docker one-command proof is missing | Partial | Task 25 + Human checkpoint |
| SQLite upgrade/downgrade, route rollback, complete migration rehearsal | Task 21 proves the deterministic five-step Alembic cycle and replay; Task 22 proves the real Provider factory sequence and byte-equivalent route rollback without executing a tool | Complete | Tasks 21-22 |
| Real GitHub PR / optional cloud Skill, Nacos, or centralized observability | Real upstream PR #1141 exists and remains open. The design explicitly rejects forced cloud/Nacos/observability integration without a necessary, verifiable use case | Engineering criterion satisfied; publication state still open | Task 27 audit |
| Final artifact, repository, recording, upload, tag, and competition submission | P0 ZIP and draft release exist; public repository/access, real video URL, tag/Release, and page submission are not proven | Human/external incomplete | Task 27 + Human checkpoint |

## Boundaries

- Always preserve AgentTeams `v1.1.2`, fail-closed policy, replayable evidence,
  Provider/Consumer scope, and current MiniMax-only maintainer paid authorization.
- Always use deterministic, model-free verification unless a task explicitly
  requires live Agent output.
- Never call Qwen, DeepSeek, or StepFun; never read or publish raw Worker logs,
  Matrix message bodies, credentials, Signed Grants, or private paths.
- Never mark recording, public upload, repository visibility, tag/Release, PR
  merge, or competition-page submission complete without direct external proof.
- Optional Alibaba Cloud Skill, Nacos, or centralized observability integration
  remains rejected unless a concrete initial-stage need and verifiable evidence
  justify the added dependency.

## Completion criteria

Every row above must be proven by current code, tests, runtime evidence, rendered
artifacts, or direct external state. The design checklist and submission
checklists may be checked only after their cited evidence is revalidated.
