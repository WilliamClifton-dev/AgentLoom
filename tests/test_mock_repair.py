from __future__ import annotations

import json
import shutil
from hashlib import sha256
from pathlib import Path

import pytest

from agentloom.contracts import (
    PatchArtifact,
    RiskReport,
    RootCauseReport,
    VerificationResult,
)
from agentloom.mock_repair import MockRepairError, MockRepairRunner

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "demo" / "fixtures" / "severity-normalization"


def test_mock_repair_reproduces_failure_and_emits_verified_artifacts(
    tmp_path: Path,
) -> None:
    result = MockRepairRunner(FIXTURE).run(tmp_path / "run")

    assert result.task.status == "COMPLETED"
    assert result.bundle.root_cause.confidence == 1
    assert result.bundle.patch.changed_paths == ["src/severity.py"]
    assert result.bundle.verification.verdict == "PASSED"
    assert result.bundle.verification.checks.original_failure_reproduced
    assert result.bundle.verification.checks.target_tests_passed
    assert result.bundle.verification.checks.regression_tests_passed
    assert result.bundle.verification.checks.static_checks_passed
    assert not result.bundle.verification.checks.unauthorized_changes
    assert result.bundle.risk.verdict == "PASSED"

    artifacts = result.artifacts_dir
    expected_files = {
        "result.md",
        "root-cause-report.json",
        "repair.patch",
        "patch-artifact.json",
        "verification-result.json",
        "risk-report.json",
        "test-results.txt",
    }
    assert expected_files <= {path.name for path in artifacts.iterdir()}

    root_cause = RootCauseReport.model_validate_json(
        (artifacts / "root-cause-report.json").read_text(encoding="utf-8")
    )
    patch = PatchArtifact.model_validate_json(
        (artifacts / "patch-artifact.json").read_text(encoding="utf-8")
    )
    verification = VerificationResult.model_validate_json(
        (artifacts / "verification-result.json").read_text(encoding="utf-8")
    )
    risk = RiskReport.model_validate_json(
        (artifacts / "risk-report.json").read_text(encoding="utf-8")
    )
    assert {root_cause.task_id, patch.task_id, verification.task_id, risk.task_id} == {
        result.task.task_id
    }
    assert patch.sha256 == sha256((artifacts / "repair.patch").read_bytes()).hexdigest()
    assert verification.patch_hash == patch.sha256

    test_results = (artifacts / "test-results.txt").read_text(encoding="utf-8")
    assert "ORIGINAL FAILURE: REPRODUCED" in test_results
    assert "PATCHED TESTS: PASSED" in test_results
    assert "STATIC CHECKS: PASSED" in test_results
    assert json.loads((artifacts / "verification-result.json").read_text())["verdict"] == (
        "PASSED"
    )


def test_mock_repair_fails_closed_if_fixture_no_longer_reproduces(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE, fixture)
    shutil.copy2(
        fixture / "expected" / "src" / "severity.py",
        fixture / "before" / "src" / "severity.py",
    )

    with pytest.raises(MockRepairError, match="original failure was not reproduced"):
        MockRepairRunner(fixture).run(tmp_path / "run")
