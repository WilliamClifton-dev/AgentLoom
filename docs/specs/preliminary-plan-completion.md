# Preliminary-plan completion specification

## Objective

Close every evidence-backed initial-stage item in
`docs/architecture/agentloom-architecture.md` without weakening its trust
boundaries or substituting local artifacts for Human/external actions.

## Authoritative completion matrix

| Design item | Current evidence | Status | Owning task |
| --- | --- | --- | --- |
| Five core upstream Skill manifests, one original Skill, at least three real calls | Five upstream manifests remain provenance-bound; `patch-scope-validator` v1.0.1 is team-original and PUBLISHED; three distinct Policy Broker -> ToolProvider calls strictly reopen with SkillVersion, Agent, Grant, ToolCall, and Evidence closure | Complete | Task 26 + Task 27 security audit |
| L1/L2/L3 DetectionResult and Evidence with Implementer/Verifier separation | Task 23 main-case bundle binds ordered STATIC/DYNAMIC/VERIFICATION results to distinct immutable Evidence; Implementer owns L1/L2 and Verifier owns L3 | Complete | Task 23 |
| Final conclusions link Evidence IDs; success/failure/uncertain ExperienceRecord | Task 23 emits a successful main-task ExperienceRecord referencing every stage; strict contracts cover failed, unsafe, and uncertain terminal outcomes without claiming unexecuted runs | Complete | Task 23 |
| Two-mode comparison and 3-5 evaluation tasks | Three versioned cases each passed both LOCAL_DETERMINISTIC and AGENTTEAMS_GOVERNED modes; the strict report reopens as 6 PASSED / 0 NOT_RUN | Complete | Task 24 |
| Competition video and clean Docker one-command reproduction | The 309-second 1920x1080 Demo passed frame, decode, audio, privacy, and anonymous browser playback checks; clean-clone Lite and same-host Full passed, while Full/Docker on a second clean host remains a delivery checkpoint | Partial | Tasks 25, 29, and 30 + Human checkpoint |
| SQLite upgrade/downgrade, route rollback, complete migration rehearsal | Task 21 proves the deterministic five-step Alembic cycle and replay; Task 22 proves the real Provider factory sequence and byte-equivalent route rollback without executing a tool | Complete | Tasks 21-22 |
| Real GitHub PR / optional cloud Skill, Nacos, or centralized observability | Real upstream PR #1141 exists and remains open. The design explicitly rejects forced cloud/Nacos/observability integration without a necessary, verifiable use case | Engineering criterion satisfied; publication state still open | Task 27 audit |
| Final artifact, repository, recording, upload, tag, and competition submission | The refreshed eight-entry P0 ZIP reopens and matches its source files; the audited candidate, real Demo, annotated `v0.1.0` tag, formal Release, exact target SHA, and final video asset all passed public verification; competition-page submission remains unproven | Human/external incomplete | Tasks 27-30 + Human checkpoint |

## Boundaries

- Always preserve AgentTeams `v1.1.2`, fail-closed policy, replayable evidence,
  Provider/Consumer scope, and the MiniMax/StepFun authorization in ADR-023.
  The accepted Task 24 report remains immutable MiniMax evidence, while future
  diagnostics may use either authorized Provider with a new run ID and exact
  Provider/model binding.
- Always use deterministic, model-free verification unless a task explicitly
  requires live Agent output.
- Never call Qwen or DeepSeek; use MiniMax or StepFun only for explicit live
  Agent work with separate run IDs. Never read or publish raw Worker logs,
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
