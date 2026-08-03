"""Deterministic offline repair run used before live model integration."""

from __future__ import annotations

import difflib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from agentloom.contracts import (
    EvidenceRecord,
    Finding,
    PatchArtifact,
    RepairArtifactBundle,
    RiskReport,
    RootCauseReport,
    TaskCreate,
    TaskRecord,
    VerificationChecks,
    VerificationResult,
)
from agentloom.storage import Database
from agentloom.workflow import RepairWorkflow

_FIXED_SOURCE = Path("src/severity.py")
_ALLOWED_PATHS = [_FIXED_SOURCE.as_posix()]


class MockRepairError(RuntimeError):
    """Raised when the deterministic repair cannot prove its outcome."""


@dataclass(frozen=True)
class MockRepairResult:
    task: TaskRecord
    bundle: RepairArtifactBundle
    artifacts_dir: Path


class MockRepairRunner:
    """Run a fixed failure/patch/verification lifecycle without an LLM."""

    def __init__(self, fixture_root: Path) -> None:
        self._fixture_root = fixture_root.resolve()
        self._before = self._fixture_root / "before"
        self._expected = self._fixture_root / "expected"

    def run(self, output_root: Path) -> MockRepairResult:
        self._validate_fixture()
        root = output_root.resolve()
        if root.exists() and any(root.iterdir()):
            raise MockRepairError(f"output directory must be empty: {root}")
        root.mkdir(parents=True, exist_ok=True)
        workspace = root / "workspace"
        artifacts = root / "artifacts"
        shutil.copytree(self._before, workspace)
        artifacts.mkdir()

        database = Database(f"sqlite:///{root / 'agentloom.db'}")
        database.create_schema()
        task = database.create_task(
            TaskCreate(
                title="Normalize severity values with surrounding whitespace",
                repository_uri="fixture://severity-normalization",
                issue='normalize_severity(" high ") raises ValueError.',
                acceptance_criteria=[
                    "The original failure is reproduced before the patch.",
                    "Whitespace-padded supported values normalize correctly.",
                    "Unknown values remain rejected.",
                ],
                allowed_paths=_ALLOWED_PATHS,
            )
        )
        workflow = RepairWorkflow(database)
        workflow.start(task.task_id)

        before_tests = _run_python_module(workspace, "pytest", "-q")
        if before_tests.returncode == 0:
            raise MockRepairError("original failure was not reproduced")
        workflow.record_investigation(task.task_id, sufficient=True)

        patch = self._build_patch()
        patch_path = artifacts / "repair.patch"
        patch_path.write_text(patch, encoding="utf-8", newline="\n")
        patch_hash = _file_hash(patch_path)
        self._apply_expected_files(workspace)
        changed_paths = _changed_paths(self._before, workspace)
        unauthorized_changes = changed_paths != _ALLOWED_PATHS
        workflow.record_implementation(task.task_id, requires_approval=False)

        after_tests = _run_python_module(workspace, "pytest", "-q")
        static_checks = _run_python_module(workspace, "compileall", "-q", "src", "tests")
        tests_passed = after_tests.returncode == 0
        static_passed = static_checks.returncode == 0
        if not tests_passed or not static_passed or unauthorized_changes:
            workflow.record_verification(task.task_id, outcome="FAILED")
            raise MockRepairError("patched fixture did not pass independent verification")

        test_results_path = artifacts / "test-results.txt"
        test_results_path.write_text(
            _test_results(before_tests, after_tests, static_checks),
            encoding="utf-8",
            newline="\n",
        )

        test_evidence_id = f"ev-{task.task_id}-tests"
        patch_evidence_id = f"ev-{task.task_id}-patch"
        evidence = (
            EvidenceRecord(
                evidence_id=test_evidence_id,
                task_id=task.task_id,
                step_id="verify-01",
                kind="TEST_OUTPUT",
                producer="agentloom-verifier",
                uri=f"artifact://{task.task_id}/test-results.txt",
                sha256=_file_hash(test_results_path),
                summary="Original failure reproduced; patched tests and static checks passed.",
            ),
            EvidenceRecord(
                evidence_id=patch_evidence_id,
                task_id=task.task_id,
                step_id="implement-01",
                kind="PATCH",
                producer="agentloom-implementer",
                uri=f"artifact://{task.task_id}/repair.patch",
                sha256=patch_hash,
                summary="One allowlisted source file changed.",
            ),
        )

        root_cause = RootCauseReport(
            task_id=task.task_id,
            summary="Severity normalization uppercased input without trimming whitespace.",
            confidence=1,
            evidence_refs=[test_evidence_id],
            repair_constraints=["Only src/severity.py may change."],
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
            reason="The frozen patch passed target, regression, and static checks.",
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
                    message="Only the allowlisted source file changed.",
                    location=_FIXED_SOURCE.as_posix(),
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
        _write_model(artifacts / "root-cause-report.json", root_cause)
        _write_model(artifacts / "patch-artifact.json", patch_artifact)
        _write_model(artifacts / "verification-result.json", verification)
        _write_model(artifacts / "risk-report.json", risk)
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
            _result_markdown(task.task_id, bundle),
            encoding="utf-8",
            newline="\n",
        )

        workflow.record_verification(task.task_id, outcome="PASSED")
        final_task = workflow.finish(task.task_id, outcome="PASSED")
        return MockRepairResult(
            task=final_task,
            bundle=bundle,
            artifacts_dir=artifacts,
        )

    def _validate_fixture(self) -> None:
        required = (
            self._before / _FIXED_SOURCE,
            self._before / "tests/test_severity.py",
            self._expected / _FIXED_SOURCE,
        )
        missing = [path for path in required if not path.is_file()]
        if missing:
            raise MockRepairError(f"fixture is incomplete: {missing[0]}")

    def _build_patch(self) -> str:
        before = (self._before / _FIXED_SOURCE).read_text(encoding="utf-8").splitlines()
        expected = (self._expected / _FIXED_SOURCE).read_text(
            encoding="utf-8"
        ).splitlines()
        patch = "\n".join(
            difflib.unified_diff(
                before,
                expected,
                fromfile=f"a/{_FIXED_SOURCE.as_posix()}",
                tofile=f"b/{_FIXED_SOURCE.as_posix()}",
                lineterm="",
            )
        )
        if not patch:
            raise MockRepairError("fixture patch is empty")
        return f"{patch}\n"

    def _apply_expected_files(self, workspace: Path) -> None:
        for source in self._expected.rglob("*"):
            if not source.is_file():
                continue
            target = workspace / source.relative_to(self._expected)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def _run_python_module(
    workspace: Path,
    module: str,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", module, *arguments],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _changed_paths(before: Path, workspace: Path) -> list[str]:
    before_files = {
        path.relative_to(before).as_posix(): _file_hash(path)
        for path in before.rglob("*.py")
        if "__pycache__" not in path.parts
    }
    workspace_files = {
        path.relative_to(workspace).as_posix(): _file_hash(path)
        for path in workspace.rglob("*.py")
        if "__pycache__" not in path.parts
    }
    return sorted(
        path
        for path in before_files.keys() | workspace_files.keys()
        if before_files.get(path) != workspace_files.get(path)
    )


def _test_results(
    before: subprocess.CompletedProcess[str],
    after: subprocess.CompletedProcess[str],
    static: subprocess.CompletedProcess[str],
) -> str:
    return (
        "ORIGINAL FAILURE: REPRODUCED\n"
        f"{before.stdout}{before.stderr}\n"
        "PATCHED TESTS: PASSED\n"
        f"{after.stdout}{after.stderr}\n"
        "STATIC CHECKS: PASSED\n"
        f"{static.stdout}{static.stderr}\n"
    )


def _result_markdown(task_id: str, bundle: RepairArtifactBundle) -> str:
    return (
        f"# Repair result: {task_id}\n\n"
        "STATUS: SUCCESS\n\n"
        f"Root cause: {bundle.root_cause.summary}\n\n"
        f"Patch SHA-256: `{bundle.patch.sha256}`\n\n"
        "Verification: PASSED\n"
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
