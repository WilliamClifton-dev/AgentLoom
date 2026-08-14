# Task evidence and ExperienceRecord binding specification

## Objective

Bind one deterministic main repair task to L1 static, L2 dynamic, and L3
independent-verification `DetectionResult` records, immutable `EvidenceRecord`
artifacts, and one terminal `ExperienceRecord`. Every final conclusion must
resolve to evidence from the same task, and Implementer/Verifier ownership must
be enforced by a strict boundary contract rather than documentation alone.

## Commands

- Focused tests: `.venv\Scripts\python -m pytest tests/test_contracts.py tests/test_mock_repair.py tests/test_detection.py`
- Main task: `.venv\Scripts\python -m agentloom.mock_repair --case-root demo/cases/severity-normalization --output-root <empty-directory>`
- Quality: `.venv\Scripts\ruff check .` and `.venv\Scripts\mypy src tests`

## Project structure

- `src/agentloom/contracts.py`: additive task-detection, bundle, and experience
  contracts.
- `src/agentloom/mock_repair.py`: real main-case L1/L2/L3 evidence production.
- `tests/test_contracts.py`: cross-task, ownership, evidence, and terminal-outcome
  rejection tests.
- `tests/test_mock_repair.py`: main-task artifact and role-separation tests.

## Contract shape

`TaskDetectionRecord` wraps the existing `DetectionResult` with a stable record
ID, task/step IDs, producer Agent, subject digest, and timestamp. L1 STATIC and
L2 DYNAMIC records must be produced by `agentloom-implementer`; L3 VERIFICATION
must be produced by `agentloom-verifier`.

`TaskEvidenceBundle` contains exactly one ordered STATIC/DYNAMIC/VERIFICATION
record, unique immutable evidence records, and one ExperienceRecord for the same
task. Every detection evidence reference must resolve inside the bundle. The
ExperienceRecord must reference the union of all three stages, so a final
conclusion cannot silently omit a failed or uncertain layer.

`ExperienceRecord` has `SUCCEEDED`, `FAILED`, and `UNCERTAIN` outcomes. Success
requires a PASSED verdict and no failure mode; failure requires FAILED/UNSAFE and
a failure mode; uncertainty requires UNCERTAIN and a failure mode. Failure and
uncertain contracts are tested without claiming that the successful main task
actually took those branches.

## Testing strategy

- RED first for missing task-bound contracts and main-task artifacts.
- Reject mixed task IDs, missing Evidence IDs, duplicate stages/evidence,
  incorrect Agent ownership, incomplete final evidence, and inconsistent
  outcome/verdict combinations.
- Run the actual trusted demo fixture: L1 checks the patch/scope, L2 runs the
  allowlisted tests in the Implementer workspace, and L3 independently replays
  in the Verifier workspace with hidden tests and static checks.
- Re-open emitted JSON through the strict contracts and hash the final bundle.

## Boundaries

- Always keep evidence append-only, SHA-256-addressed, task-bound, and free of
  secrets or host paths.
- Always keep the L3 producer and workspace independent from the Implementer.
- Never treat an absent detector, missing Evidence ID, or incomplete stage set
  as PASSED.
- Never call a model, Docker, Matrix, external network, or paid Provider in this
  task. The trusted local demo run does not replace Tasks 15-17 live evidence.
- Never claim a failed or uncertain main-task run unless such a run is actually
  executed and retained.

## Success criteria

- The main severity-normalization task emits exactly three ordered task-bound
  detection records and at least three immutable Evidence records.
- L1/L2 ownership is Implementer and L3 ownership is Verifier.
- The successful ExperienceRecord references every stage Evidence ID.
- Mixed-task, wrong-role, missing-evidence, incomplete-stage, and inconsistent
  terminal-outcome inputs fail closed.
- Focused and full gates pass with no model or external service call.
