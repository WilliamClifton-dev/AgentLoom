"""Fail-closed verification for model-generated AgentTeams repair submissions."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import ConfigDict, Field, ValidationError, model_validator

from agentloom.contracts import (
    ContractModel,
    CoordinationTrace,
    RepairArtifactBundle,
    VerificationChecks,
)
from agentloom.demo_case import DemoCase, load_demo_case
from agentloom.mock_repair import (
    MockRepairError,
    _changed_paths,
    _combine_results,
    _file_hash,
    _run_case_command,
    _target_command,
    _test_results,
    _write_model,
)

AgentName = Literal[
    "agentloom-investigator",
    "agentloom-implementer",
    "agentloom-verifier",
]
ProviderName = Literal["dashscope", "deepseek", "stepfun"]
ModelName = Literal["qwen3.7-plus", "deepseek-v4-pro", "step-3.7-flash"]

_EXPECTED_AGENTS: tuple[AgentName, ...] = (
    "agentloom-investigator",
    "agentloom-implementer",
    "agentloom-verifier",
)
_PROVIDER_MODELS: dict[ProviderName, ModelName] = {
    "dashscope": "qwen3.7-plus",
    "deepseek": "deepseek-v4-pro",
    "stepfun": "step-3.7-flash",
}
_HIDDEN_WORKSPACE = ".agentloom-hidden-tests"
_MAX_PATCH_BYTES = 131_072


class LiveRepairError(RuntimeError):
    """Raised when a live AgentTeams repair cannot be independently proven."""


class AgentRoleEvent(ContractModel):
    agent_name: AgentName = Field(alias="agentName")
    matrix_user_id: str = Field(
        alias="matrixUserId",
        pattern=r"^@[^\s:]+:[^\s]+$",
    )
    room_id: str = Field(alias="roomId", pattern=r"^![^\s]+$")
    event_id: str = Field(alias="eventId", pattern=r"^\$[^\s]+$")
    origin_server_timestamp: int = Field(alias="originServerTimestamp", ge=1)


class LiveRepairSubmission(ContractModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    schema_version: Literal["agentloom.live-repair-submission/v1alpha1"] = Field(
        alias="schemaVersion"
    )
    task_id: str = Field(
        alias="taskId",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    provider: ProviderName
    model: ModelName
    coordination_trace: CoordinationTrace = Field(alias="coordinationTrace")
    role_events: list[AgentRoleEvent] = Field(alias="roleEvents")
    repair_patch: str = Field(
        alias="repairPatch",
        min_length=1,
        max_length=_MAX_PATCH_BYTES,
    )
    bundle: RepairArtifactBundle

    @model_validator(mode="after")
    def submission_is_bound_to_agents_model_and_artifacts(
        self,
    ) -> LiveRepairSubmission:
        if self.model != _PROVIDER_MODELS[self.provider]:
            raise ValueError("provider and model are not an approved live E2E pair")
        if tuple(event.agent_name for event in self.role_events) != _EXPECTED_AGENTS:
            raise ValueError(
                "roleEvents must contain the three business Agent role events "
                "in Investigator, Implementer, Verifier order"
            )
        if len({event.event_id for event in self.role_events}) != 3:
            raise ValueError("roleEvents must use three distinct Matrix event IDs")
        if self.coordination_trace.task_id != self.task_id:
            raise ValueError("coordinationTrace must match submission taskId")
        all_event_ids = {
            event.event_id for event in self.coordination_trace.events
        } | {event.event_id for event in self.role_events}
        if len(all_event_ids) != 6:
            raise ValueError("coordination and role events must use distinct event IDs")
        ordered_timestamps = [
            self.coordination_trace.events[0].origin_server_timestamp,
            self.role_events[0].origin_server_timestamp,
            self.coordination_trace.events[1].origin_server_timestamp,
            self.role_events[1].origin_server_timestamp,
            self.coordination_trace.events[2].origin_server_timestamp,
            self.role_events[2].origin_server_timestamp,
        ]
        if ordered_timestamps != sorted(ordered_timestamps) or len(
            set(ordered_timestamps)
        ) != len(ordered_timestamps):
            raise ValueError(
                "coordination and role events must follow the repair handoff order"
            )
        if "\x00" in self.repair_patch:
            raise ValueError("repairPatch must not contain NUL bytes")

        artifact_task_ids = {
            self.bundle.root_cause.task_id,
            self.bundle.patch.task_id,
            self.bundle.verification.task_id,
            self.bundle.risk.task_id,
        }
        if artifact_task_ids != {self.task_id}:
            raise ValueError("all repair artifacts must match submission taskId")
        expected_uri = f"artifact://{self.task_id}/repair.patch"
        if self.bundle.patch.patch_uri != expected_uri:
            raise ValueError("PatchArtifact patchUri is not bound to the task")
        if self.bundle.verification.verifier_agent != "agentloom-verifier":
            raise ValueError("VerificationResult must be owned by agentloom-verifier")

        event_ids = {
            event.agent_name: event.event_id for event in self.role_events
        }
        if event_ids["agentloom-investigator"] not in (
            self.bundle.root_cause.evidence_refs
        ):
            raise ValueError("RootCauseReport is not bound to the Investigator event")
        if event_ids["agentloom-implementer"] not in self.bundle.patch.evidence_refs:
            raise ValueError("PatchArtifact is not bound to the Implementer event")
        verifier_event = event_ids["agentloom-verifier"]
        if verifier_event not in self.bundle.verification.evidence_refs:
            raise ValueError("VerificationResult is not bound to the Verifier event")
        if verifier_event not in self.bundle.risk.evidence_refs:
            raise ValueError("RiskReport is not bound to the Verifier event")
        return self


@dataclass(frozen=True)
class LiveRepairResult:
    task_id: str
    provider: ProviderName
    model: ModelName
    bundle: RepairArtifactBundle
    artifacts_dir: Path


class LiveRepairVerifier:
    """Apply and independently verify one role-traced model patch."""

    def __init__(self, case_root: Path) -> None:
        self._case = load_demo_case(case_root)

    def run(
        self,
        submission_path: Path,
        output_root: Path,
    ) -> LiveRepairResult:
        submission = _load_submission(submission_path)
        patch_bytes = submission.repair_patch.encode("utf-8")
        actual_patch_hash = sha256(patch_bytes).hexdigest()
        if actual_patch_hash != submission.bundle.patch.sha256:
            raise LiveRepairError(
                "repair.patch hash does not match the submitted PatchArtifact"
            )

        patch_paths = _patch_paths(submission.repair_patch)
        declared_paths = sorted(submission.bundle.patch.changed_paths)
        if patch_paths != declared_paths:
            raise LiveRepairError(
                "repair.patch paths do not match PatchArtifact changedPaths"
            )
        allowed_paths = set(self._case.manifest.allowed_changed_paths)
        unauthorized = sorted(set(patch_paths) - allowed_paths)
        if unauthorized:
            raise LiveRepairError(
                "repair.patch changes files outside allowed paths: "
                + ", ".join(unauthorized)
            )

        root = output_root.resolve()
        if root.exists() and any(root.iterdir()):
            raise LiveRepairError(f"output directory must be empty: {root}")
        root.mkdir(parents=True, exist_ok=True)
        workspace = root / "workspace"
        verifier_workspace = root / "verifier-workspace"
        artifacts = root / "artifacts"
        shutil.copytree(self._case.source_root, workspace)
        artifacts.mkdir()
        patch_path = artifacts / "repair.patch"
        patch_path.write_bytes(patch_bytes)

        working_relative = self._case.working_directory.relative_to(
            self._case.source_root
        )
        try:
            target_results = [
                _run_case_command(
                    workspace=workspace,
                    working_relative=working_relative,
                    command=_target_command(self._case.test_command, target),
                    timeout_seconds=self._case.manifest.timeout_seconds,
                    output_limit_bytes=self._case.manifest.output_limit_bytes,
                )
                for target in self._case.manifest.target_failing_tests
            ]
        except MockRepairError as exc:
            raise LiveRepairError(str(exc)) from exc
        if any(result.returncode != 1 for result in target_results):
            raise LiveRepairError("original failure was not reproduced")
        before_tests = _combine_results(target_results)

        _apply_patch(workspace, patch_path, self._case)
        changed_paths = _changed_paths(self._case.source_root, workspace)
        if changed_paths != declared_paths:
            raise LiveRepairError(
                "applied patch changed paths do not match PatchArtifact changedPaths"
            )

        shutil.copytree(workspace, verifier_workspace)
        verifier_hidden = verifier_workspace / working_relative / _HIDDEN_WORKSPACE
        shutil.copytree(self._case.hidden_tests_root, verifier_hidden)
        try:
            after_tests = _run_case_command(
                workspace=verifier_workspace,
                working_relative=working_relative,
                command=self._case.test_command,
                timeout_seconds=self._case.manifest.timeout_seconds,
                output_limit_bytes=self._case.manifest.output_limit_bytes,
            )
            hidden_tests = _run_case_command(
                workspace=verifier_workspace,
                working_relative=working_relative,
                command=("pytest", "-q", _HIDDEN_WORKSPACE),
                timeout_seconds=self._case.manifest.timeout_seconds,
                output_limit_bytes=self._case.manifest.output_limit_bytes,
            )
            static_checks = _run_case_command(
                workspace=verifier_workspace,
                working_relative=working_relative,
                command=self._case.static_check_command,
                timeout_seconds=self._case.manifest.timeout_seconds,
                output_limit_bytes=self._case.manifest.output_limit_bytes,
            )
        except MockRepairError as exc:
            raise LiveRepairError(str(exc)) from exc
        if after_tests.returncode != 0:
            raise LiveRepairError("patched tests failed")
        if hidden_tests.returncode != 0:
            raise LiveRepairError("hidden tests failed")
        if static_checks.returncode != 0:
            raise LiveRepairError("static checks failed")

        local_checks = VerificationChecks(
            original_failure_reproduced=True,
            target_tests_passed=True,
            regression_tests_passed=True,
            static_checks_passed=True,
            unauthorized_changes=False,
        )
        if submission.bundle.verification.verdict != "PASSED":
            raise LiveRepairError("Verifier Agent did not return a PASSED verdict")
        if submission.bundle.verification.checks != local_checks:
            raise LiveRepairError(
                "Verifier Agent checks do not match independent local verification"
            )
        if submission.bundle.risk.risk_level != "L1":
            raise LiveRepairError("initial live repair E2E accepts only L1 patches")
        if submission.bundle.risk.verdict != "PASSED":
            raise LiveRepairError("Verifier Agent risk verdict is not PASSED")

        test_results_path = artifacts / "test-results.txt"
        test_results_path.write_text(
            _test_results(before_tests, after_tests, hidden_tests, static_checks),
            encoding="utf-8",
            newline="\n",
        )
        _write_model(artifacts / "root-cause-report.json", submission.bundle.root_cause)
        _write_model(artifacts / "patch-artifact.json", submission.bundle.patch)
        _write_model(
            artifacts / "verification-result.json",
            submission.bundle.verification,
        )
        _write_model(artifacts / "risk-report.json", submission.bundle.risk)
        _write_evidence(
            path=artifacts / "live-repair-evidence.json",
            submission=submission,
            case=self._case,
            submission_path=submission_path,
            test_results_path=test_results_path,
        )
        return LiveRepairResult(
            task_id=submission.task_id,
            provider=submission.provider,
            model=submission.model,
            bundle=submission.bundle,
            artifacts_dir=artifacts,
        )


def _load_submission(path: Path) -> LiveRepairSubmission:
    try:
        return LiveRepairSubmission.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise LiveRepairError(f"invalid live repair submission: {exc}") from exc


def _patch_paths(patch: str) -> list[str]:
    forbidden_markers = (
        "GIT binary patch",
        "Binary files ",
        "rename from ",
        "rename to ",
        "copy from ",
        "copy to ",
    )
    if any(marker in patch for marker in forbidden_markers):
        raise LiveRepairError("binary, rename, and copy patches are not allowed")

    lines = patch.splitlines()
    paths: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("--- "):
            index += 1
            continue
        if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
            raise LiveRepairError("repair.patch contains an incomplete file header")
        before = line[4:]
        after = lines[index + 1][4:]
        if not before.startswith("a/") or not after.startswith("b/"):
            raise LiveRepairError("repair.patch must modify existing a/ and b/ paths")
        before_path = before[2:]
        after_path = after[2:]
        if before_path != after_path:
            raise LiveRepairError("repair.patch must not rename files")
        paths.append(_safe_patch_path(before_path))
        index += 2
    if not paths:
        raise LiveRepairError("repair.patch does not contain a unified diff")
    if len(paths) != len(set(paths)):
        raise LiveRepairError("repair.patch contains duplicate file sections")
    return sorted(paths)


def _safe_patch_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or value.startswith(("/", "\\")):
        raise LiveRepairError("repair.patch contains an absolute path")
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise LiveRepairError("repair.patch contains an unsafe path")
    if "\\" in value or "\x00" in value:
        raise LiveRepairError("repair.patch contains an unsafe path")
    return path.as_posix()


def _apply_patch(workspace: Path, patch_path: Path, case: DemoCase) -> None:
    for arguments in (
        ("git", "apply", "--check", "--whitespace=error-all", str(patch_path)),
        ("git", "apply", "--whitespace=error-all", str(patch_path)),
    ):
        try:
            result = subprocess.run(
                arguments,
                cwd=workspace,
                capture_output=True,
                timeout=case.manifest.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LiveRepairError("git apply could not verify the submitted patch") from exc
        output_size = len(result.stdout) + len(result.stderr)
        if output_size > case.manifest.output_limit_bytes:
            raise LiveRepairError("git apply output exceeded the case limit")
        if result.returncode != 0:
            raise LiveRepairError("git apply rejected the submitted patch")


def _write_evidence(
    *,
    path: Path,
    submission: LiveRepairSubmission,
    case: DemoCase,
    submission_path: Path,
    test_results_path: Path,
) -> None:
    evidence = {
        "schemaVersion": "agentloom.live-repair-evidence/v1alpha1",
        "status": "PASS",
        "taskId": submission.task_id,
        "caseId": case.manifest.case_id,
        "caseSnapshotSha256": case.provenance.snapshot_sha256,
        "provider": submission.provider,
        "model": submission.model,
        "submissionSha256": _file_hash(submission_path),
        "patchSha256": submission.bundle.patch.sha256,
        "testResultsSha256": _file_hash(test_results_path),
        "roleEvents": [
            event.model_dump(mode="json", by_alias=True)
            for event in submission.role_events
        ],
        "coordinationTrace": submission.coordination_trace.model_dump(
            mode="json", by_alias=True
        ),
        "independentVerification": {
            "originalFailureReproduced": True,
            "targetTestsPassed": True,
            "regressionTestsPassed": True,
            "hiddenTestsPassed": True,
            "staticChecksPassed": True,
            "unauthorizedChanges": False,
        },
    }
    path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
