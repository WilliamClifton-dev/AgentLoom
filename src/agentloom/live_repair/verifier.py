"""Fail-closed verification for model-generated AgentTeams repair submissions."""

from __future__ import annotations

import shutil
from hashlib import sha256
from pathlib import Path
from typing import Literal

from agentloom.contracts import (
    RepairArtifactBundle,
    VerificationChecks,
    VerificationResult,
)
from agentloom.demo_case import load_demo_case
from agentloom.mock_repair import (
    MockRepairError,
    _changed_paths,
    _combine_results,
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
ProviderName = Literal["dashscope", "deepseek", "stepfun", "minimax-cn"]
ModelName = Literal[
    "qwen3.7-plus",
    "deepseek-v4-pro",
    "step-3.7-flash",
    "MiniMax-M2.5",
]

_EXPECTED_AGENTS: tuple[AgentName, ...] = (
    "agentloom-investigator",
    "agentloom-implementer",
    "agentloom-verifier",
)
_PROVIDER_MODELS: dict[ProviderName, ModelName] = {
    "dashscope": "qwen3.7-plus",
    "deepseek": "deepseek-v4-pro",
    "stepfun": "step-3.7-flash",
    "minimax-cn": "MiniMax-M2.5",
}
_HIDDEN_WORKSPACE = ".agentloom-hidden-tests"
_MAX_PATCH_BYTES = 131_072
_MAX_SOURCE_FILES = 64
_MAX_SOURCE_BYTES = 1_048_576




from agentloom.live_repair.case import (  # noqa: E402,F401  # noqa: E402,F401
    _apply_patch,
    _load_submission,
    _patch_paths,
    _write_evidence,
)
from agentloom.live_repair.models import (  # noqa: E402,F401
    AgentRoleEvent,
    LiveRepairCaseContext,
    LiveRepairError,
    LiveRepairSourceFile,
    LiveRepairSubmission,
)
from agentloom.live_repair.result import LiveRepairResult  # noqa: E402,F401


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
        role_verification = submission.bundle.verification
        worker_review_checks = VerificationChecks(
            original_failure_reproduced=False,
            target_tests_passed=False,
            regression_tests_passed=False,
            static_checks_passed=True,
            unauthorized_changes=False,
        )
        if role_verification.verdict == "UNCERTAIN":
            if role_verification.checks != worker_review_checks:
                raise LiveRepairError(
                    "UNCERTAIN Verifier Agent checks must describe the bounded "
                    "Worker review"
                )
        elif role_verification.verdict == "PASSED":
            if role_verification.checks != local_checks:
                raise LiveRepairError(
                    "PASSED Verifier Agent checks do not match independent "
                    "local verification"
                )
        else:
            raise LiveRepairError(
                "Verifier Agent rejected the patch before host verification"
            )
        if submission.bundle.risk.risk_level != "L1":
            raise LiveRepairError("initial live repair E2E accepts only L1 patches")
        if submission.bundle.risk.verdict != "PASSED":
            raise LiveRepairError("Verifier Agent risk verdict is not PASSED")

        host_verification = VerificationResult(
            task_id=submission.task_id,
            patch_hash=submission.bundle.patch.sha256,
            verdict="PASSED",
            checks=local_checks,
            evidence_refs=[
                *role_verification.evidence_refs,
                f"artifact://{submission.task_id}/test-results.txt",
            ],
            reason=(
                "Independent host verification reproduced the original failure "
                "and passed visible, hidden, and static checks."
            ),
            verifier_agent="agentloom-host-verifier",
        )
        verified_bundle = RepairArtifactBundle(
            root_cause=submission.bundle.root_cause,
            patch=submission.bundle.patch,
            verification=host_verification,
            risk=submission.bundle.risk,
        )

        test_results_path = artifacts / "test-results.txt"
        test_results_path.write_text(
            _test_results(before_tests, after_tests, hidden_tests, static_checks),
            encoding="utf-8",
            newline="\n",
        )
        _write_model(artifacts / "root-cause-report.json", submission.bundle.root_cause)
        _write_model(artifacts / "patch-artifact.json", submission.bundle.patch)
        _write_model(
            artifacts / "agent-verification-result.json",
            role_verification,
        )
        _write_model(artifacts / "verification-result.json", host_verification)
        _write_model(artifacts / "risk-report.json", submission.bundle.risk)
        _write_evidence(
            path=artifacts / "live-repair-evidence.json",
            submission=submission,
            case=self._case,
            submission_path=submission_path,
            test_results_path=test_results_path,
            verified_workspace=verifier_workspace,
            host_verification=host_verification,
        )
        return LiveRepairResult(
            task_id=submission.task_id,
            provider=submission.provider,
            model=submission.model,
            bundle=verified_bundle,
            role_verification=role_verification,
            artifacts_dir=artifacts,
        )