from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentloom.demo_case import DemoCaseError, load_demo_case, snapshot_sha256


def _write_case(root: Path, **overrides: object) -> Path:
    (root / "before" / "src").mkdir(parents=True)
    (root / "before" / "tests").mkdir(parents=True)
    (root / "expected" / "src").mkdir(parents=True)
    (root / "hidden-tests").mkdir(parents=True)
    (root / "before" / "src" / "calculator.py").write_text(
        "def add(left: int, right: int) -> int:\n    return left - right\n",
        encoding="utf-8",
    )
    (root / "before" / "tests" / "test_calculator.py").write_text(
        "from src.calculator import add\n\n"
        "def test_add() -> None:\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    (root / "expected" / "src" / "calculator.py").write_text(
        "def add(left: int, right: int) -> int:\n    return left + right\n",
        encoding="utf-8",
    )
    (root / "hidden-tests" / "test_calculator_hidden.py").write_text(
        "from src.calculator import add\n\n"
        "def test_negative_addition() -> None:\n    assert add(-2, 3) == 1\n",
        encoding="utf-8",
    )
    (root / "issue.md").write_text("`add` subtracts its operands.\n", encoding="utf-8")
    provenance = {
        "schemaVersion": "agentloom.demo-provenance/v1alpha1",
        "repositoryUrl": "https://github.com/example/calculator",
        "frozenCommit": "a" * 40,
        "issueUrl": "https://github.com/example/calculator/issues/1",
        "license": "MIT",
        "snapshotSha256": f"sha256:{snapshot_sha256(root / 'before')}",
    }
    (root / "provenance.json").write_text(
        json.dumps(provenance), encoding="utf-8"
    )
    manifest: dict[str, object] = {
        "schemaVersion": "agentloom.demo-case/v1alpha1",
        "caseId": "calculator-addition",
        "title": "Correct integer addition",
        "issuePath": "issue.md",
        "acceptanceCriteria": [
            "The original failure is reproduced before the patch.",
            "Addition works for positive and negative operands.",
        ],
        "provenancePath": "provenance.json",
        "sourceRoot": "before",
        "expectedPatchRoot": "expected",
        "hiddenTestsPath": "hidden-tests",
        "workingDirectory": ".",
        "testCommand": ["pytest", "-q"],
        "staticCheckCommand": ["compileall", "-q", "src", "tests"],
        "targetFailingTests": ["tests/test_calculator.py::test_add"],
        "allowedChangedPaths": ["src/calculator.py"],
        "timeoutSeconds": 60,
        "outputLimitBytes": 65536,
        "runtime": {"language": "python", "version": ">=3.12,<3.13"},
        "expectedRootCause": "The add function subtracts the right operand.",
    }
    manifest.update(overrides)
    path = root / "case.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_load_demo_case_accepts_strict_manifest_and_verified_snapshot(
    tmp_path: Path,
) -> None:
    path = _write_case(tmp_path / "case")

    case = load_demo_case(path.parent)

    assert case.manifest.case_id == "calculator-addition"
    assert case.issue == "`add` subtracts its operands."
    assert case.source_root == path.parent / "before"
    assert case.test_command == ("pytest", "-q")
    assert case.provenance.frozen_commit == "a" * 40


def test_load_demo_case_rejects_unknown_fields(tmp_path: Path) -> None:
    path = _write_case(tmp_path / "case", surprise=True)

    with pytest.raises(ValidationError, match="surprise"):
        load_demo_case(path.parent)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("testCommand", "pytest -q"),
        ("testCommand", ["powershell", "-Command", "pytest"]),
        ("testCommand", ["pytest", "-q", "; Remove-Item secrets"]),
        ("testCommand", ["C:/Python312/python.exe", "-m", "pytest"]),
        ("testCommand", ["pytest", "../outside"]),
        ("workingDirectory", "../outside"),
        ("timeoutSeconds", 121),
    ],
)
def test_load_demo_case_rejects_unsafe_commands_and_limits(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    path = _write_case(tmp_path / "case", **{field: value})

    with pytest.raises((ValidationError, DemoCaseError)):
        load_demo_case(path.parent)


def test_load_demo_case_rejects_snapshot_tampering(tmp_path: Path) -> None:
    path = _write_case(tmp_path / "case")
    (path.parent / "before" / "src" / "calculator.py").write_text(
        "raise RuntimeError('tampered')\n", encoding="utf-8"
    )

    with pytest.raises(DemoCaseError, match="snapshot hash mismatch"):
        load_demo_case(path.parent)


def test_load_demo_case_rejects_hidden_tests_exposed_in_source(tmp_path: Path) -> None:
    path = _write_case(tmp_path / "case")
    exposed = path.parent / "before" / "hidden-tests"
    exposed.mkdir()
    (exposed / "test_secret.py").write_text("assert False\n", encoding="utf-8")
    provenance_path = path.parent / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["snapshotSha256"] = (
        f"sha256:{snapshot_sha256(path.parent / 'before')}"
    )
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")

    with pytest.raises(DemoCaseError, match="hidden tests are exposed"):
        load_demo_case(path.parent)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repositoryUrl", "file:///tmp/repository"),
        ("frozenCommit", "main"),
        ("issueUrl", "not-a-url"),
        ("license", "unknown license"),
    ],
)
def test_load_demo_case_rejects_invalid_provenance(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    path = _write_case(tmp_path / "case")
    provenance_path = path.parent / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance[field] = value
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_demo_case(path.parent)
