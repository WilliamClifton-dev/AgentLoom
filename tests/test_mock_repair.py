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
from agentloom.demo_case import snapshot_sha256
from agentloom.mock_repair import MockRepairError, MockRepairRunner

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "demo" / "cases"
SEVERITY_CASE = CASES / "severity-normalization"


@pytest.mark.parametrize(
    ("case_id", "changed_path"),
    [
        ("severity-normalization", "src/severity.py"),
        ("pagination-boundary", "lib/pagination.py"),
    ],
)
def test_mock_repair_reproduces_failure_and_emits_verified_artifacts(
    tmp_path: Path,
    case_id: str,
    changed_path: str,
) -> None:
    result = MockRepairRunner(CASES / case_id).run(tmp_path / "run")

    assert result.task.status == "COMPLETED"
    assert result.bundle.root_cause.confidence == 1
    assert result.bundle.patch.changed_paths == [changed_path]
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
    assert not (tmp_path / "run" / "workspace" / "hidden-tests").exists()
    assert not (
        tmp_path / "run" / "workspace" / ".agentloom-hidden-tests"
    ).exists()
    assert (
        tmp_path / "run" / "verifier-workspace" / ".agentloom-hidden-tests"
    ).is_dir()


def test_mock_repair_fails_closed_if_fixture_no_longer_reproduces(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "case"
    shutil.copytree(SEVERITY_CASE, fixture)
    shutil.copy2(
        fixture / "expected" / "src" / "severity.py",
        fixture / "before" / "src" / "severity.py",
    )
    _rewrite_snapshot_hash(fixture)

    with pytest.raises(MockRepairError, match="original failure was not reproduced"):
        MockRepairRunner(fixture).run(tmp_path / "run")


def test_mock_repair_does_not_misclassify_collection_errors_as_reproduction(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "case"
    shutil.copytree(SEVERITY_CASE, fixture)
    (fixture / "before" / "src" / "severity.py").write_text(
        "this is not valid python !!!\n",
        encoding="utf-8",
    )
    _rewrite_snapshot_hash(fixture)

    with pytest.raises(MockRepairError, match="original failure was not reproduced"):
        MockRepairRunner(fixture).run(tmp_path / "run")


def test_mock_repair_does_not_accept_spoofed_target_output(tmp_path: Path) -> None:
    case = tmp_path / "case"
    shutil.copytree(SEVERITY_CASE, case)
    test_path = case / "before" / "tests" / "test_severity.py"
    test_text = test_path.read_text(encoding="utf-8").replace(
        'assert normalize_severity(" high ") == "HIGH"',
        'print("tests/test_severity.py::test_normalize_severity_accepts_'
        'surrounding_whitespace")\n    assert True',
    )
    test_text += "\n\ndef test_unrelated_failure() -> None:\n    assert False\n"
    test_path.write_text(test_text, encoding="utf-8")
    _rewrite_snapshot_hash(case)

    with pytest.raises(MockRepairError, match="original failure was not reproduced"):
        MockRepairRunner(case).run(tmp_path / "run")


def test_mock_repair_rejects_undeclared_file_modifications(tmp_path: Path) -> None:
    case = tmp_path / "case"
    shutil.copytree(SEVERITY_CASE, case)
    (case / "expected" / "README.md").write_text(
        "unauthorized change\n", encoding="utf-8"
    )

    with pytest.raises(MockRepairError, match="unauthorized file changes"):
        MockRepairRunner(case).run(tmp_path / "run")


def test_mock_repair_fails_when_hidden_tests_fail(tmp_path: Path) -> None:
    case = tmp_path / "case"
    shutil.copytree(SEVERITY_CASE, case)
    (case / "hidden-tests" / "test_severity_hidden.py").write_text(
        "def test_hidden_regression() -> None:\n    assert False\n",
        encoding="utf-8",
    )

    with pytest.raises(MockRepairError, match="hidden tests failed"):
        MockRepairRunner(case).run(tmp_path / "run")


def test_mock_repair_fails_closed_when_command_output_exceeds_limit(
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    shutil.copytree(SEVERITY_CASE, case)
    test_path = case / "before" / "tests" / "test_severity.py"
    test_path.write_text(
        test_path.read_text(encoding="utf-8").replace(
            'assert normalize_severity(" high ") == "HIGH"',
            "print('x' * 70000)\n"
            '    assert normalize_severity(" high ") == "HIGH"',
        ),
        encoding="utf-8",
    )
    manifest_path = case / "case.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["testCommand"] = ["pytest", "-q", "-s"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _rewrite_snapshot_hash(case)

    with pytest.raises(MockRepairError, match="command output exceeded"):
        MockRepairRunner(case).run(tmp_path / "run")


def test_mock_repair_fails_closed_when_command_times_out(tmp_path: Path) -> None:
    case = tmp_path / "case"
    shutil.copytree(SEVERITY_CASE, case)
    test_path = case / "before" / "tests" / "test_severity.py"
    test_path.write_text(
        test_path.read_text(encoding="utf-8").replace(
            'assert normalize_severity(" high ") == "HIGH"',
            "import time\n"
            "    time.sleep(2)\n"
            '    assert normalize_severity(" high ") == "HIGH"',
        ),
        encoding="utf-8",
    )
    manifest_path = case / "case.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["timeoutSeconds"] = 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _rewrite_snapshot_hash(case)

    with pytest.raises(MockRepairError, match="command timed out"):
        MockRepairRunner(case).run(tmp_path / "run")


def _rewrite_snapshot_hash(case: Path) -> None:
    provenance_path = case / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["snapshotSha256"] = f"sha256:{snapshot_sha256(case / 'before')}"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
