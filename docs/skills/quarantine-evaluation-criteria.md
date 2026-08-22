# Skill Quarantine and Evaluation Criteria

> Status: **2 PUBLISHED / 4 QUARANTINED** as of 2026-08-21.
>
> Published: `code-review-and-quality` (upstream), `patch-scope-validator`
> v1.0.1 (team-original).
> Quarantined: `debugging-and-error-recovery`,
> `test-driven-development`, `security-and-hardening`,
> `using-agent-skills`.
>
> This document is the authoritative reference for the entry and exit
> criteria every imported Skill must satisfy to move between the
> `SkillLifecycleState` values defined in
> `agentloom.contracts.skill.SkillManifest` (`DISCOVERED`,
> `QUARANTINED`, `SCANNED`, `EVALUATING`, `APPROVED`, `PUBLISHED`,
> `DEPRECATED`, `BLOCKED`, `REJECTED`).

## 1. Why a Skill is quarantined

A Skill is `QUARANTINED` if and only if **one or more admission gates have
not yet produced a reproducible green pass on a controlled local
reproduction**, or if the upstream source has moved in a way that
requires re-evaluation. A Skill stays `QUARANTINED` until it can prove
all of the following on the public-main gate:

1. **Source provenance.** `SkillSource` is locked: the upstream commit
   hash, content hash, and (where applicable) workspace snapshot are
   committed in `skills/catalog.json`, and the original license text
   is preserved in `THIRD_PARTY.md`.
2. **Pydantic schema round-trip.** `SkillManifest` validates the
   upstream `SKILL.md` body, including `input_schema` /
   `output_schema` paths that resolve to existing JSON-Schema files
   under `schemas/skills/`.
3. **Reproducible AgentLoom benchmark.** The Skill has at least one
   `evaluation.agentloomBenchEvidenceRefs` entry pointing to a stable
   pytest node id in the public-main test suite, and that test passes
   in the current Lite (`376 passed / 3 skipped / 0 failed`) and Full
   (`379 passed / 0 skipped / 0 failed`) gates.
4. **Pinned Tool execution.** Every `allowedTools` entry resolves to
   a bound Tool Provider with a `ToolExecutionGrant` shape (`agent`,
   `skillName`, `skillVersion`, `toolName`, `parameterDigest`) and a
   matching `RiskLevel` (`L0` / `L1` / `L2` / `L3`).
5. **Risk classification.** The Skill is either `L0` (no writes, no
   process exec) or `L1` (writes limited to a Tool Provider with
   immutable sandbox image, grant-bound nonce, and replayable
   `ToolCallEventRecord`).
6. **Failure-mode coverage.** Every entry in `failure_modes` maps to
   at least one existing `ToolExecutionResult.error_code` value, and
   the `Tool Provider` round-trips that error code in the governed
   ToolCall event stream.
7. **Source stability.** A new upstream revision is **not**
   required to keep the gate green; the benchmark fixture is
   committed in-repo and the Skill does not fetch content at runtime.

A Skill in `QUARANTINED` state is **not callable** by any governed
Agent (Investigator, Implementer, Verifier, Manager). The catalog
will not issue a `SkillExecutionGrant` for it.

## 2. State machine

```
DISCOVERED  ──►  QUARANTINED  ──►  SCANNED  ──►  EVALUATING  ──►  APPROVED  ──►  PUBLISHED
                    ▲                                                            │
                    │                                                            ▼
                    └────────────  BLOCKED / DEPRECATED / REJECTED  ◄────────────┘
```

| State | Entry condition | Exit condition |
|---|---|---|
| `DISCOVERED` | First import from a `SkillSource` repository. | Static schema + license + content hash recorded in catalog. |
| `QUARANTINED` | Imported but not yet proven on the public-main gate. | At least one AgentLoom benchmark evidence reference exists, and the corresponding test passes twice in a row on a clean checkout. |
| `SCANNED` | Provenance + content hash recorded. | Static check + dependency review + license review complete. |
| `EVALUATING` | `SCANNED` is green. | All benchmark tests pass deterministically across at least one Lite and one Full run. |
| `APPROVED` | All evaluation evidence reproducible. | Human L2 approval recorded in `l2_approval` evidence (see `docs/competition/l2-approval-and-upstream-contribution-evidence.md`). |
| `PUBLISHED` | Approved and bound to governed Agents. | First ToolCall with a fresh `SkillExecutionGrant` is recorded in the public evidence stream. |
| `BLOCKED` | Critical security or compatibility issue. | None (terminal until a new `eTag` of the upstream source replaces the broken revision). |
| `DEPRECATED` | Replaced by a newer version or a team-original Skill. | None (terminal; the catalog keeps a read-only `SkillManifest` so existing evidence remains valid). |
| `REJECTED` | Upstream license or scope is incompatible with AgentLoom governance. | None (terminal; the manifest is removed from the active catalog but stays in git history for audit). |

## 3. Exit criteria for the four currently QUARANTINED Skills

The four upstream Skills below all share the **same** evaluation
harness. Their primary scenarios are reduced to one or more pytest
fixtures under `tests/test_skill_invocations.py` (the existing
`SkillInvocationEvidenceRecord` harness), and each fixture must
pass in the public-main gate twice in a row before the Skill may
leave `QUARANTINED`. The harness is extended per Skill as the
benchmark stabilises; the test names listed below are the planned
fixture ids and will be added when the corresponding Skill is
promoted.

### 3.1 `debugging-and-error-recovery` (L0, agentloom-investigator)

| Field | Value |
|---|---|
| Upstream | `https://github.com/addyosmani/agent-skills @ 7829ffd` |
| License | MIT (preserved in `THIRD_PARTY.md`) |
| Risk | `L0` read-only repository snapshot; no network, no writes. |
| Required tools | `repository-search:repo.read`, `test-reader:tests.read`. |
| Required evidence | A deterministic root-cause fixture under `tests/test_skill_invocations.py` that reproduces one Investigator finding and asserts a complete `SkillInvocationEvidenceRecord` (`invocation_id`, `tool_call_event_id`, `grant_id`, `parameter_digest`, `digest`, and a `RiskReport` shape), plus one L1 review fixture proving the Skill never writes outside `allowedPaths = ["src/**", "tests/**", "logs/**"]`. |
| Exit gate | The two fixtures pass on a clean Lite gate twice in a row, the manifest gains a non-null `evaluation.agentloomBenchEvidenceRefs`, and the Verifier Agent re-runs `tests/test_skill_invocations.py` to confirm the patch scope and `RiskReport` shape. |

### 3.2 `test-driven-development` (L1, agentloom-implementer)

| Field | Value |
|---|---|
| Upstream | `https://github.com/addyosmani/agent-skills @ 7829ffd` |
| License | MIT |
| Risk | `L1` isolated workspace; writes restricted to `src/**` and `tests/**`. |
| Required tools | `patch-adapter:repo.patch`, `test-runner:process.exec:test` (sandbox-only). |
| Required evidence | A bounded-bug fixture under `demo/cases/tdd-bug-*/` that exercises a Skill-driven TDD loop, plus a Skill fixture that asserts: (a) failing test before, (b) Skill-written patch, (c) green test in the governed Docker sandbox, (d) replayable `ToolCallEventRecord` carrying a `SkillInvocationEvidenceRecord` with non-null `tool_call_event_id`, `grant_id`, and `parameter_digest`. |
| Exit gate | The bounded-bug fixture passes on a clean Full gate twice in a row. The Skill's `allowedTools` is tightened to forbid non-pytest `process.exec` (the sandbox `SandboxExecutionRequest.command` validator must reject every other command pattern), and `tests/test_skill_invocations.py` is extended to cover the rejection. |

### 3.3 `security-and-hardening` (L0, agentloom-verifier)

| Field | Value |
|---|---|
| Upstream | `https://github.com/addyosmani/agent-skills @ 7829ffd` |
| License | MIT |
| Risk | `L0` read-only checks; reviewed policy cannot be modified by the Skill. |
| Required tools | `repository-search:repo.read`, `static-check-adapter:scan.run`. |
| Required evidence | A two-fixture suite: (i) one fixture consumes a pinned `pip-audit` finding and asserts the Skill emits a `RiskReport` with `verdict = "UNSAFE"` and an attached `EvidenceRecord` whose `uri` resolves to the audit JSON; (ii) a second fixture asserts the same Skill returns `verdict = "PASSED"` on a clean `uv.lock`. |
| Exit gate | The two fixtures pass on a clean Full gate twice in a row, the Skill's `allowedTools` is reduced to the two read-only tool entries above, and the catalog `evaluation` block references the fixtures by stable node id. |

### 3.4 `using-agent-skills` (L0, agentloom-manager)

| Field | Value |
|---|---|
| Upstream | `https://github.com/addyosmani/agent-skills @ 7829ffd` |
| License | MIT |
| Risk | `L0` registry metadata read; selection does **not** grant execution. |
| Required tools | `skill-registry:skill.list`, `skill-registry:skill.read`. |
| Required evidence | A fixture that loads the current `skills/catalog.json`, invokes the Skill, and asserts: (a) every returned `SkillManifest` has `lifecycleState in {"APPROVED", "PUBLISHED", "DEPRECATED"}`, (b) no `QUARANTINED` or `BLOCKED` Skill is ever returned, and (c) the result references the catalog's `schema_version` exactly. |
| Exit gate | The fixture passes on a clean Lite gate twice in a row. A second fixture asserts the Skill rejects any request that would name a `QUARANTINED` Skill, with `error_code = "POLICY_DENIED"` and a `RiskReport` whose `verdict = "FAILED"`. |

## 4. How to evaluate a candidate

A new Skill moves through the states above via
`agentloom.skill_evidence` (`src/agentloom/skill_evidence.py`) and the
`tests/test_skill_invocations.py` harness. The operator workflow is:

1. **Pin the source.** Record the upstream `commit` and the
   `contentHash` of the Skill body in `SkillSource` and commit the
   change. Run `scripts/refresh-test-results.ps1` so the catalog hash
   is part of the gate.
2. **Author fixtures.** Add at least one pytest fixture under
   `tests/test_skill_invocations.py` that exercises the Skill's
   primary scenario. The existing fixtures
   (`test_skill_invocation_record_binds_complete_execution_closure`,
   `test_skill_invocation_record_rejects_mismatched_grant_or_tool_call`,
   `test_immutable_skill_invocation_writer_refuses_overwrite`,
   `test_immutable_skill_invocation_writer_rejects_path_escape`) are
   the template: every new fixture must call the Skill through the
   governed Tool Provider so a `SkillInvocationEvidenceRecord` is
   produced.
3. **Run the gate.** `python -m pytest -q` followed by
   `python -m pytest --tb=short tests/test_skill_invocations.py` to
   confirm the fixtures pass twice in a row. The CI workflow must
   also build the Docker sandbox image and run the same fixtures in
   the Full gate.
4. **Promote.** Update `skills/catalog.json`:
   - Set `lifecycleState = "APPROVED"`.
   - Populate `evaluation.upstreamEvidenceRefs` and
     `evaluation.agentloomBenchEvidenceRefs` with the new
     `source:sha256:…` and `test:tests/...` references.
   - Record the Human L2 approval in
     `docs/competition/l2-approval-and-upstream-contribution-evidence.md`.
5. **Publish.** Set `lifecycleState = "PUBLISHED"`. From this commit
   forward the Skill is callable by the bound `compatibleAgents`. A
   `SkillInvocationEvidenceRecord` for the first governed call must
   be produced within the same release.
6. **Record.** Add a `Skill Eval` entry to the next CHANGELOG
   section, including the bench evidence node ids and the
   `contentHash` of the catalog at publish time.

## 5. Re-evaluation triggers

A `PUBLISHED` Skill returns to `QUARANTINED` if any of the following
happens:

- The upstream `commit` advances and the catalog hash diverges.
- The AgentLoom benchmark fixture regresses (test fails on the
  public-main gate).
- A governance change (`RiskLevel`, `allowedTools`, `allowedPaths`,
  `compatibleAgents`) makes the existing `ToolExecutionGrant` shape
  invalid.
- A new `BLOCKED` or `REJECTED` upstream advisory is published.

A `QUARANTINED` Skill that stays in `QUARANTINED` for more than two
release cycles must be re-evaluated against the same exit criteria
or be moved to `DEPRECATED` with a written reason in
`docs/competition/l2-approval-and-upstream-contribution-evidence.md`.

## 6. Cross-references

- Skill contract: `agentloom.contracts.skill.SkillManifest` and
  `agentloom.contracts.skill.SkillSource` in
  `src/agentloom/contracts/skill.py`.
- Evaluation runner: `agentloom.skill_evidence` in
  `src/agentloom/skill_evidence.py` and the L1 fixtures in
  `tests/test_skill_invocations.py`.
- Catalog file: `skills/catalog.json` (the only file the runner
  consumes directly).
- L2 approval record:
  `docs/competition/l2-approval-and-upstream-contribution-evidence.md`.
- Gate definition: `.github/workflows/ci.yml` (Lite and Full pytest
  jobs), plus `scripts/refresh-test-results.ps1` for the locally
  refreshed `test-results.txt` snapshot.
