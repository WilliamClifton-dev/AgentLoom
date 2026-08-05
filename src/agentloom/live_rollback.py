"""Independent execution and verification of a role-traced live rollback."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, ValidationError, model_validator

from agentloom.contracts import ContractModel
from agentloom.demo_case import DemoCase, load_demo_case, snapshot_sha256
from agentloom.live_repair import (
    LiveRepairError,
    ModelName,
    ProviderName,
    _apply_patch,
    _patch_paths,
)
from agentloom.mock_repair import (
    MockRepairError,
    _changed_paths,
    _file_hash,
    _run_case_command,
    _target_command,
)

_MAX_SUBMISSION_BYTES = 1_048_576
_MAX_PATCH_BYTES = 131_072
_HIDDEN_WORKSPACE = ".agentloom-hidden-tests"
_PROVIDER_MODELS: dict[ProviderName, ModelName] = {
    "dashscope": "qwen3.7-plus",
    "deepseek": "deepseek-v4-pro",
}

RollbackPhase = Literal[
    "VERIFICATION_FAILED",
    "ROLLBACK_REQUESTED",
    "ROLLBACK_EXECUTED",
    "ROLLBACK_VERIFIED",
]
RollbackAgentName = Literal[
    "agentloom-manager",
    "agentloom-implementer",
    "agentloom-verifier",
]
_EXPECTED_EVENT_FLOW: tuple[tuple[RollbackPhase, RollbackAgentName], ...] = (
    ("VERIFICATION_FAILED", "agentloom-verifier"),
    ("ROLLBACK_REQUESTED", "agentloom-manager"),
    ("ROLLBACK_EXECUTED", "agentloom-implementer"),
    ("ROLLBACK_VERIFIED", "agentloom-verifier"),
)


class LiveRollbackError(RuntimeError):
    """Raised when a rollback cannot be independently proven."""


class RollbackRoleEvent(ContractModel):
    phase: RollbackPhase
    agent_name: RollbackAgentName = Field(alias="agentName")
    matrix_user_id: str = Field(
        alias="matrixUserId", pattern=r"^@[^\s:]+:[^\s]+$"
    )
    room_id: str = Field(alias="roomId", pattern=r"^![^\s]+$")
    event_id: str = Field(alias="eventId", pattern=r"^\$[^\s]+$")
    origin_server_timestamp: int = Field(alias="originServerTimestamp", ge=1)


class RollbackPlan(ContractModel):
    strategy: Literal["RESTORE_APPROVED_SNAPSHOT"]
    allowed_changed_paths: list[str] = Field(
        alias="allowedChangedPaths", min_length=1, max_length=32
    )
    reason: str = Field(min_length=1, max_length=500)


class LiveRollbackSubmission(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=False,
    )

    schema_version: Literal[
        "agentloom.live-rollback-submission/v1alpha1"
    ] = Field(alias="schemaVersion")
    task_id: str = Field(
        alias="taskId", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    case_id: str = Field(alias="caseId", pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    provider: ProviderName
    model: ModelName
    failed_patch: str = Field(
        alias="failedPatch", min_length=1, max_length=_MAX_PATCH_BYTES
    )
    failed_patch_sha256: str = Field(
        alias="failedPatchSha256", pattern=r"^[a-f0-9]{64}$"
    )
    rollback_plan: RollbackPlan = Field(alias="rollbackPlan")
    role_events: list[RollbackRoleEvent] = Field(
        alias="roleEvents", min_length=4, max_length=4
    )

    @model_validator(mode="after")
    def evidence_chain_is_ordered_and_bound(self) -> LiveRollbackSubmission:
        if self.model != _PROVIDER_MODELS[self.provider]:
            raise ValueError("provider and model are not an approved live E2E pair")
        flow = tuple((event.phase, event.agent_name) for event in self.role_events)
        if flow != _EXPECTED_EVENT_FLOW:
            raise ValueError("role events do not match the required rollback flow")
        if len({event.event_id for event in self.role_events}) != 4:
            raise ValueError("role events must use distinct Matrix event IDs")
        if len({event.room_id for event in self.role_events}) != 1:
            raise ValueError("role events must belong to one Team Room")
        timestamps = [event.origin_server_timestamp for event in self.role_events]
        if timestamps != sorted(timestamps) or len(set(timestamps)) != 4:
            raise ValueError("role events must be strictly chronological")
        verifier_ids = {
            event.matrix_user_id
            for event in self.role_events
            if event.agent_name == "agentloom-verifier"
        }
        if len(verifier_ids) != 1:
            raise ValueError("Verifier events must use one Matrix identity")
        if "\x00" in self.failed_patch:
            raise ValueError("failedPatch must not contain NUL bytes")
        return self


@dataclass(frozen=True)
class LiveRollbackResult:
    task_id: str
    case_id: str
    provider: ProviderName
    model: ModelName
    failed_patch_sha256: str
    failed_snapshot_sha256: str
    approved_snapshot_sha256: str
    failure_reproduced: bool
    rollback_executed: bool
    post_rollback_tests_passed: bool
    role_event_ids: tuple[str, ...]
    workspace: Path
    artifacts_dir: Path


class LiveRollbackVerifier:
    """Exercise a failed candidate and restore the last approved snapshot."""

    def __init__(self, case_root: Path) -> None:
        self._case = load_demo_case(case_root)

    def run(self, submission_path: Path, output_root: Path) -> LiveRollbackResult:
        submission = _load_submission(submission_path)
        if submission.case_id != self._case.manifest.case_id:
            raise LiveRollbackError("rollback submission does not match the demo case")

        patch_bytes = submission.failed_patch.encode("utf-8")
        if not _constant_hash_matches(patch_bytes, submission.failed_patch_sha256):
            raise LiveRollbackError("failed patch hash does not match the submission")
        try:
            patch_paths = _patch_paths(submission.failed_patch)
        except LiveRepairError as exc:
            raise LiveRollbackError(str(exc)) from exc
        allowed_paths = sorted(self._case.manifest.allowed_changed_paths)
        if sorted(submission.rollback_plan.allowed_changed_paths) != allowed_paths:
            raise LiveRollbackError("rollback plan does not match the case allowlist")
        if patch_paths != allowed_paths:
            raise LiveRollbackError("failed patch does not match the rollback allowlist")

        root = output_root.resolve()
        if root.exists() and any(root.iterdir()):
            raise LiveRollbackError(f"output directory must be empty: {root}")
        root.mkdir(parents=True, exist_ok=True)
        approved = root / "approved-snapshot"
        workspace = root / "workspace"
        artifacts = root / "artifacts"
        _build_approved_snapshot(self._case, approved)
        shutil.copytree(approved, workspace)
        artifacts.mkdir()

        approved_hash = snapshot_sha256(approved)
        baseline_results = _run_approved_checks(
            self._case, approved, root / "baseline-verifier"
        )
        if any(result.returncode != 0 for result in baseline_results):
            raise LiveRollbackError("the approved snapshot does not pass its checks")

        patch_path = artifacts / "failed.patch"
        patch_path.write_bytes(patch_bytes)
        try:
            _apply_patch(workspace, patch_path, self._case)
        except LiveRepairError as exc:
            raise LiveRollbackError(str(exc)) from exc
        if _changed_paths(approved, workspace) != allowed_paths:
            raise LiveRollbackError("failed candidate changed files outside the plan")
        failed_hash = snapshot_sha256(workspace)
        failure_results = _run_target_checks(self._case, workspace)
        if any(result.returncode != 1 for result in failure_results):
            raise LiveRollbackError("submitted candidate failure was not reproduced")

        shutil.rmtree(workspace)
        shutil.copytree(approved, workspace)
        if snapshot_sha256(workspace) != approved_hash:
            raise LiveRollbackError("rollback did not restore the approved snapshot")
        rollback_results = _run_approved_checks(
            self._case, workspace, root / "rollback-verifier"
        )
        if any(result.returncode != 0 for result in rollback_results):
            raise LiveRollbackError("post-rollback checks did not pass")

        results_path = artifacts / "rollback-test-results.txt"
        results_path.write_text(
            _render_results(baseline_results, failure_results, rollback_results),
            encoding="utf-8",
            newline="\n",
        )
        evidence_path = artifacts / "live-rollback-evidence.json"
        _write_evidence(
            evidence_path,
            submission=submission,
            submission_path=submission_path,
            results_path=results_path,
            failed_snapshot_sha256=failed_hash,
            approved_snapshot_sha256=approved_hash,
        )
        return LiveRollbackResult(
            task_id=submission.task_id,
            case_id=submission.case_id,
            provider=submission.provider,
            model=submission.model,
            failed_patch_sha256=submission.failed_patch_sha256,
            failed_snapshot_sha256=failed_hash,
            approved_snapshot_sha256=approved_hash,
            failure_reproduced=True,
            rollback_executed=True,
            post_rollback_tests_passed=True,
            role_event_ids=tuple(event.event_id for event in submission.role_events),
            workspace=workspace,
            artifacts_dir=artifacts,
        )


def _load_submission(path: Path) -> LiveRollbackSubmission:
    try:
        if path.stat().st_size > _MAX_SUBMISSION_BYTES:
            raise LiveRollbackError("live rollback submission exceeds the size limit")
        return LiveRollbackSubmission.model_validate_json(
            path.read_bytes().decode("utf-8", errors="strict")
        )
    except LiveRollbackError:
        raise
    except (OSError, UnicodeError, ValidationError) as exc:
        raise LiveRollbackError("invalid live rollback submission") from exc


def _constant_hash_matches(content: bytes, expected: str) -> bool:
    import hmac

    return hmac.compare_digest(sha256(content).hexdigest(), expected)


def _build_approved_snapshot(case: DemoCase, destination: Path) -> None:
    shutil.copytree(case.source_root, destination)
    for source in case.expected_patch_root.rglob("*"):
        if not source.is_file():
            continue
        target = destination / source.relative_to(case.expected_patch_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _run_target_checks(
    case: DemoCase, workspace: Path
) -> list[subprocess.CompletedProcess[str]]:
    working_relative = case.working_directory.relative_to(case.source_root)
    try:
        return [
            _run_case_command(
                workspace=workspace,
                working_relative=working_relative,
                command=_target_command(case.test_command, target),
                timeout_seconds=case.manifest.timeout_seconds,
                output_limit_bytes=case.manifest.output_limit_bytes,
            )
            for target in case.manifest.target_failing_tests
        ]
    except MockRepairError as exc:
        raise LiveRollbackError(str(exc)) from exc


def _run_approved_checks(
    case: DemoCase, snapshot: Path, verifier_workspace: Path
) -> list[subprocess.CompletedProcess[str]]:
    shutil.copytree(snapshot, verifier_workspace)
    working_relative = case.working_directory.relative_to(case.source_root)
    hidden = verifier_workspace / working_relative / _HIDDEN_WORKSPACE
    shutil.copytree(case.hidden_tests_root, hidden)
    try:
        return [
            _run_case_command(
                workspace=verifier_workspace,
                working_relative=working_relative,
                command=case.test_command,
                timeout_seconds=case.manifest.timeout_seconds,
                output_limit_bytes=case.manifest.output_limit_bytes,
            ),
            _run_case_command(
                workspace=verifier_workspace,
                working_relative=working_relative,
                command=("pytest", "-q", _HIDDEN_WORKSPACE),
                timeout_seconds=case.manifest.timeout_seconds,
                output_limit_bytes=case.manifest.output_limit_bytes,
            ),
            _run_case_command(
                workspace=verifier_workspace,
                working_relative=working_relative,
                command=case.static_check_command,
                timeout_seconds=case.manifest.timeout_seconds,
                output_limit_bytes=case.manifest.output_limit_bytes,
            ),
        ]
    except MockRepairError as exc:
        raise LiveRollbackError(str(exc)) from exc


def _render_results(
    baseline: list[subprocess.CompletedProcess[str]],
    failure: list[subprocess.CompletedProcess[str]],
    rollback: list[subprocess.CompletedProcess[str]],
) -> str:
    def output(results: list[subprocess.CompletedProcess[str]]) -> str:
        return "".join(
            f"{result.stdout}{result.stderr}"
            for result in results
        )

    return (
        "APPROVED BASELINE: PASSED\n"
        f"{output(baseline)}\n"
        "FAILED CANDIDATE: FAILURE REPRODUCED\n"
        f"{output(failure)}\n"
        "ROLLBACK: APPROVED SNAPSHOT RESTORED\n"
        f"{output(rollback)}\n"
    )


def _write_evidence(
    path: Path,
    *,
    submission: LiveRollbackSubmission,
    submission_path: Path,
    results_path: Path,
    failed_snapshot_sha256: str,
    approved_snapshot_sha256: str,
) -> None:
    evidence = {
        "schemaVersion": "agentloom.live-rollback-evidence/v1alpha1",
        "evidenceKind": "LIVE_AGENTTEAMS_HOST_VERIFIED_ROLLBACK",
        "status": "PASS",
        "taskId": submission.task_id,
        "caseId": submission.case_id,
        "provider": submission.provider,
        "model": submission.model,
        "submissionSha256": _file_hash(submission_path),
        "failedPatchSha256": submission.failed_patch_sha256,
        "testResultsSha256": _file_hash(results_path),
        "roleEvents": [
            event.model_dump(mode="json", by_alias=True)
            for event in submission.role_events
        ],
        "rollbackPlan": submission.rollback_plan.model_dump(
            mode="json", by_alias=True
        ),
        "failure": {
            "reproduced": True,
            "failedSnapshotSha256": failed_snapshot_sha256,
        },
        "rollback": {
            "executed": True,
            "approvedSnapshotSha256": approved_snapshot_sha256,
            "approvedSnapshotRestored": True,
            "visibleTestsPassed": True,
            "hiddenTestsPassed": True,
            "staticChecksPassed": True,
        },
    }
    path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
