"""Deterministic manifest-driven repair run used before live model integration."""

from __future__ import annotations

import argparse
import difflib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from agentloom.bounded_exec import BoundedExecutionError, run_bounded_python_command
from agentloom.contracts import (
    DetectionResult,
    EvidenceRecord,
    ExperienceRecord,
    Finding,
    PatchArtifact,
    RepairArtifactBundle,
    RiskReport,
    RootCauseReport,
    TaskCreate,
    TaskDetectionRecord,
    TaskEvidenceBundle,
    TaskRecord,
    VerificationChecks,
    VerificationResult,
)
from agentloom.demo_case import DemoCase, load_demo_case
from agentloom.storage import Database
from agentloom.workflow import RepairWorkflow

_HIDDEN_WORKSPACE = ".agentloom-hidden-tests"


class MockRepairError(RuntimeError):
    """Raised when the deterministic repair cannot prove its outcome."""


@dataclass(frozen=True)
class MockRepairResult:
    task: TaskRecord
    bundle: RepairArtifactBundle
    task_evidence: TaskEvidenceBundle
    artifacts_dir: Path


class MockRepairRunner:
    """Run a manifest-defined failure/patch/verification lifecycle without an LLM."""

    def __init__(self, case_root: Path) -> None:
        self._case_root = case_root.resolve()

    def run(self, output_root: Path) -> MockRepairResult:
        case = load_demo_case(self._case_root)
        root = output_root.resolve()
        if root.exists() and any(root.iterdir()):
            raise MockRepairError(f"output directory must be empty: {root}")
        root.mkdir(parents=True, exist_ok=True)
        workspace = root / "workspace"
        verifier_workspace = root / "verifier-workspace"
        artifacts = root / "artifacts"
        shutil.copytree(case.source_root, workspace)
        artifacts.mkdir()

        database = Database(f"sqlite:///{root / 'agentloom.db'}")
        database.create_schema()
        task = database.create_task(
            TaskCreate(
                title=case.manifest.title,
                repository_uri=(
                    f"{case.provenance.repository_url}"
                    f"@{case.provenance.frozen_commit}"
                ),
                issue=case.issue,
                acceptance_criteria=case.manifest.acceptance_criteria,
                allowed_paths=case.manifest.allowed_changed_paths,
            )
        )
        workflow = RepairWorkflow(database)
        workflow.start(task.task_id)

        working_relative = case.working_directory.relative_to(case.source_root)
        target_results = [
            _run_case_command(
                workspace=workspace,
                working_relative=working_relative,
                command=_target_command(case.test_command, target),
                timeout_seconds=case.manifest.timeout_seconds,
                output_limit_bytes=case.manifest.output_limit_bytes,
            )
            for target in case.manifest.target_failing_tests
        ]
        if any(result.returncode != 1 for result in target_results):
            raise MockRepairError("original failure was not reproduced")
        before_tests = _combine_results(target_results)
        workflow.record_investigation(task.task_id, sufficient=True)

        patch = _build_patch(case)
        patch_path = artifacts / "repair.patch"
        patch_path.write_text(patch, encoding="utf-8", newline="\n")
        patch_hash = _file_hash(patch_path)
        _apply_expected_files(case, workspace)
        changed_paths = _changed_paths(case.source_root, workspace)
        unauthorized_changes = sorted(
            set(changed_paths) - set(case.manifest.allowed_changed_paths)
        )
        if unauthorized_changes:
            workflow.record_implementation(task.task_id, requires_approval=False)
            workflow.record_verification(task.task_id, outcome="FAILED")
            raise MockRepairError(
                "unauthorized file changes: " + ", ".join(unauthorized_changes)
            )

        implementer_tests = _run_case_command(
            workspace=workspace,
            working_relative=working_relative,
            command=case.test_command,
            timeout_seconds=case.manifest.timeout_seconds,
            output_limit_bytes=case.manifest.output_limit_bytes,
        )
        if implementer_tests.returncode != 0:
            workflow.record_implementation(task.task_id, requires_approval=False)
            workflow.record_verification(task.task_id, outcome="FAILED")
            raise MockRepairError("implementer tests failed")
        implementer_results_path = artifacts / "implementer-test-results.txt"
        implementer_results_path.write_text(
            "IMPLEMENTER ALLOWLISTED TESTS: PASSED\n"
            f"{implementer_tests.stdout}{implementer_tests.stderr}\n",
            encoding="utf-8",
            newline="\n",
        )
        workflow.record_implementation(task.task_id, requires_approval=False)

        shutil.copytree(workspace, verifier_workspace)
        verifier_hidden = verifier_workspace / working_relative / _HIDDEN_WORKSPACE
        shutil.copytree(case.hidden_tests_root, verifier_hidden)
        after_tests = _run_case_command(
            workspace=verifier_workspace,
            working_relative=working_relative,
            command=case.test_command,
            timeout_seconds=case.manifest.timeout_seconds,
            output_limit_bytes=case.manifest.output_limit_bytes,
        )
        hidden_tests = _run_case_command(
            workspace=verifier_workspace,
            working_relative=working_relative,
            command=("pytest", "-q", _HIDDEN_WORKSPACE),
            timeout_seconds=case.manifest.timeout_seconds,
            output_limit_bytes=case.manifest.output_limit_bytes,
        )
        static_checks = _run_case_command(
            workspace=verifier_workspace,
            working_relative=working_relative,
            command=case.static_check_command,
            timeout_seconds=case.manifest.timeout_seconds,
            output_limit_bytes=case.manifest.output_limit_bytes,
        )
        if after_tests.returncode != 0:
            workflow.record_verification(task.task_id, outcome="FAILED")
            raise MockRepairError("patched tests failed")
        if hidden_tests.returncode != 0:
            workflow.record_verification(task.task_id, outcome="FAILED")
            raise MockRepairError("hidden tests failed")
        if static_checks.returncode != 0:
            workflow.record_verification(task.task_id, outcome="FAILED")
            raise MockRepairError("static checks failed")

        test_results_path = artifacts / "test-results.txt"
        test_results_path.write_text(
            _test_results(before_tests, after_tests, hidden_tests, static_checks),
            encoding="utf-8",
            newline="\n",
        )

        created_at = datetime.now(UTC)
        patch_evidence_id = f"ev-{task.task_id}-l1-static"
        dynamic_evidence_id = f"ev-{task.task_id}-l2-dynamic"
        test_evidence_id = f"ev-{task.task_id}-l3-verification"
        evidence = (
            EvidenceRecord(
                evidence_id=patch_evidence_id,
                task_id=task.task_id,
                step_id="implement-static",
                kind="STATIC_PATCH_SCAN",
                producer="agentloom-implementer",
                uri=f"artifact://{task.task_id}/repair.patch",
                sha256=patch_hash,
                summary="Patch content and changed paths passed static checks.",
                created_at=created_at,
            ),
            EvidenceRecord(
                evidence_id=dynamic_evidence_id,
                task_id=task.task_id,
                step_id="implement-dynamic",
                kind="DYNAMIC_TEST_RUN",
                producer="agentloom-implementer",
                uri=f"artifact://{task.task_id}/implementer-test-results.txt",
                sha256=_file_hash(implementer_results_path),
                summary="Allowlisted tests passed in the Implementer workspace.",
                created_at=created_at,
            ),
            EvidenceRecord(
                evidence_id=test_evidence_id,
                task_id=task.task_id,
                step_id="verify-01",
                kind="INDEPENDENT_VERIFICATION",
                producer="agentloom-verifier",
                uri=f"artifact://{task.task_id}/test-results.txt",
                sha256=_file_hash(test_results_path),
                summary=(
                    "Original failure reproduced; clean-workspace patched, hidden, "
                    "and static checks passed."
                ),
                created_at=created_at,
            ),
        )

        root_cause = RootCauseReport(
            task_id=task.task_id,
            summary=case.manifest.expected_root_cause,
            confidence=1,
            evidence_refs=[test_evidence_id],
            repair_constraints=[
                f"Only {path} may change."
                for path in case.manifest.allowed_changed_paths
            ],
        )
        patch_artifact = PatchArtifact(
            task_id=task.task_id,
            patch_uri=f"artifact://{task.task_id}/repair.patch",
            sha256=patch_hash,
            changed_paths=changed_paths,
            evidence_refs=[patch_evidence_id],
        )
        verification = VerificationResult(
            task_id=task.task_id,
            patch_hash=patch_hash,
            verdict="PASSED",
            checks=VerificationChecks(
                original_failure_reproduced=True,
                target_tests_passed=True,
                regression_tests_passed=True,
                static_checks_passed=True,
                unauthorized_changes=False,
            ),
            evidence_refs=[test_evidence_id, patch_evidence_id],
            reason=(
                "The frozen patch passed target, regression, hidden, and static checks."
            ),
            verifier_agent="agentloom-verifier",
        )
        risk = RiskReport(
            task_id=task.task_id,
            risk_level="L1",
            verdict="PASSED",
            findings=[
                Finding(
                    rule_id="PATCH_SCOPE",
                    severity="INFO",
                    message="Only manifest-allowlisted files changed.",
                    location=changed_paths[0],
                )
            ],
            evidence_refs=[patch_evidence_id, test_evidence_id],
        )
        bundle = RepairArtifactBundle(
            root_cause=root_cause,
            patch=patch_artifact,
            verification=verification,
            risk=risk,
        )
        detections = [
            TaskDetectionRecord(
                detection_id=f"detection-{task.task_id}-static",
                task_id=task.task_id,
                step_id="implement-static",
                producer_agent="agentloom-implementer",
                subject_digest=patch_hash,
                result=DetectionResult(
                    stage="STATIC",
                    verdict="PASSED",
                    findings=risk.findings,
                    evidence_refs=[patch_evidence_id],
                    detector_versions={"patch-scope": "0.1.0"},
                ),
                created_at=created_at,
            ),
            TaskDetectionRecord(
                detection_id=f"detection-{task.task_id}-dynamic",
                task_id=task.task_id,
                step_id="implement-dynamic",
                producer_agent="agentloom-implementer",
                subject_digest=patch_hash,
                result=DetectionResult(
                    stage="DYNAMIC",
                    verdict="PASSED",
                    findings=[],
                    evidence_refs=[dynamic_evidence_id],
                    detector_versions={"bounded-pytest": "0.1.0"},
                ),
                created_at=created_at,
            ),
            TaskDetectionRecord(
                detection_id=f"detection-{task.task_id}-verification",
                task_id=task.task_id,
                step_id="verify-01",
                producer_agent="agentloom-verifier",
                subject_digest=patch_hash,
                result=DetectionResult(
                    stage="VERIFICATION",
                    verdict=verification.verdict,
                    findings=risk.findings,
                    evidence_refs=[test_evidence_id],
                    detector_versions={"independent-verifier": "0.1.0"},
                ),
                created_at=created_at,
            ),
        ]
        experience = ExperienceRecord(
            experience_id=f"experience-{task.task_id}",
            task_id=task.task_id,
            outcome="SUCCEEDED",
            verdict=verification.verdict,
            skill_versions={},
            lessons=[
                "Keep static, dynamic, and independent verification evidence separate."
            ],
            evidence_refs=[
                patch_evidence_id,
                dynamic_evidence_id,
                test_evidence_id,
            ],
            created_at=created_at,
        )
        task_evidence = TaskEvidenceBundle(
            task_id=task.task_id,
            detections=detections,
            evidence=list(evidence),
            experience=experience,
        )
        _write_model(artifacts / "root-cause-report.json", root_cause)
        _write_model(artifacts / "patch-artifact.json", patch_artifact)
        _write_model(artifacts / "verification-result.json", verification)
        _write_model(artifacts / "risk-report.json", risk)
        _write_model(artifacts / "experience-record.json", experience)
        _write_model(artifacts / "task-evidence-bundle.json", task_evidence)
        (artifacts / "evidence.json").write_text(
            json.dumps(
                [item.model_dump(mode="json", by_alias=True) for item in evidence],
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        (artifacts / "result.md").write_text(
            _result_markdown(task.task_id, bundle, experience),
            encoding="utf-8",
            newline="\n",
        )

        workflow.record_verification(task.task_id, outcome="PASSED")
        final_task = workflow.finish(task.task_id, outcome="PASSED")
        return MockRepairResult(
            task=final_task,
            bundle=bundle,
            task_evidence=task_evidence,
            artifacts_dir=artifacts,
        )


def _build_patch(case: DemoCase) -> str:
    chunks: list[str] = []
    for expected in sorted(
        path for path in case.expected_patch_root.rglob("*") if path.is_file()
    ):
        relative = expected.relative_to(case.expected_patch_root)
        before_path = case.source_root / relative
        try:
            before = (
                before_path.read_text(encoding="utf-8").splitlines()
                if before_path.is_file()
                else []
            )
            after = expected.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise MockRepairError(
                f"mock patches only support UTF-8 text files: {relative.as_posix()}"
            ) from exc
        chunks.extend(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"a/{relative.as_posix()}",
                tofile=f"b/{relative.as_posix()}",
                lineterm="",
            )
        )
    if not chunks:
        raise MockRepairError("case patch is empty")
    return f"{'\n'.join(chunks)}\n"


def _apply_expected_files(case: DemoCase, workspace: Path) -> None:
    for source in case.expected_patch_root.rglob("*"):
        if not source.is_file():
            continue
        target = workspace / source.relative_to(case.expected_patch_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _run_case_command(
    *,
    workspace: Path,
    working_relative: Path,
    command: tuple[str, ...],
    timeout_seconds: int,
    output_limit_bytes: int,
) -> subprocess.CompletedProcess[str]:
    try:
        return run_bounded_python_command(
            working_directory=workspace / working_relative,
            command=command,
            timeout_seconds=timeout_seconds,
            output_limit_bytes=output_limit_bytes,
        )
    except BoundedExecutionError as exc:
        raise MockRepairError(str(exc)) from exc


def _target_command(test_command: tuple[str, ...], target: str) -> tuple[str, ...]:
    arguments = (
        test_command[3:]
        if test_command[:3] == ("python", "-m", "pytest")
        else test_command[1:]
    )
    options = tuple(argument for argument in arguments if argument.startswith("-"))
    return ("pytest", *options, target)


def _combine_results(
    results: list[subprocess.CompletedProcess[str]],
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[result.args for result in results],
        returncode=1,
        stdout="\n".join(result.stdout for result in results),
        stderr="\n".join(result.stderr for result in results),
    )


def _changed_paths(before: Path, workspace: Path) -> list[str]:
    before_files = _file_inventory(before)
    workspace_files = _file_inventory(workspace)
    return sorted(
        path
        for path in before_files.keys() | workspace_files.keys()
        if before_files.get(path) != workspace_files.get(path)
    )


def _file_inventory(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _file_hash(path)
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    }


def _test_results(
    before: subprocess.CompletedProcess[str],
    after: subprocess.CompletedProcess[str],
    hidden: subprocess.CompletedProcess[str],
    static: subprocess.CompletedProcess[str],
) -> str:
    return (
        "ORIGINAL FAILURE: REPRODUCED\n"
        f"{before.stdout}{before.stderr}\n"
        "PATCHED TESTS: PASSED\n"
        f"{after.stdout}{after.stderr}\n"
        "HIDDEN TESTS: PASSED\n"
        f"{hidden.stdout}{hidden.stderr}\n"
        "STATIC CHECKS: PASSED\n"
        f"{static.stdout}{static.stderr}\n"
    )


def _result_markdown(
    task_id: str,
    bundle: RepairArtifactBundle,
    experience: ExperienceRecord,
) -> str:
    evidence_lines = "\n".join(f"- `{ref}`" for ref in experience.evidence_refs)
    return (
        f"# Repair result: {task_id}\n\n"
        "STATUS: SUCCESS\n\n"
        f"Root cause: {bundle.root_cause.summary}\n\n"
        f"Patch SHA-256: `{bundle.patch.sha256}`\n\n"
        "Verification: PASSED\n\n"
        "Evidence:\n"
        f"{evidence_lines}\n"
    )


def _write_model(path: Path, model: object) -> None:
    if not hasattr(model, "model_dump"):
        raise TypeError("artifact model must support model_dump")
    payload = model.model_dump(mode="json", by_alias=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _file_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one deterministic manifest-driven repair case."
    )
    parser.add_argument("--case-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        result = MockRepairRunner(arguments.case_root).run(arguments.output_root)
    except (OSError, RuntimeError, ValueError, UnicodeError) as exc:
        print(f"mock repair failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "taskId": result.task.task_id,
                "status": result.task.status,
                "verificationVerdict": result.bundle.verification.verdict,
                "riskVerdict": result.bundle.risk.verdict,
                "patchSha256": result.bundle.patch.sha256,
                "artifactsDirectory": str(result.artifacts_dir),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
