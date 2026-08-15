from __future__ import annotations

import difflib
import json
import shutil
import subprocess
import sys
import tempfile
from hashlib import sha256
from pathlib import Path

import pytest

from agentloom.docker_sandbox import workspace_tree_digest
from agentloom.live_repair import (
    LiveRepairError,
    LiveRepairSubmission,
    LiveRepairVerifier,
    prepare_live_repair_case_context,
)
from agentloom.mock_repair import MockRepairRunner

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "demo" / "cases" / "severity-normalization"


@pytest.mark.parametrize(
    ("case_id", "changed_path", "visible_test"),
    [
        (
            "severity-normalization",
            "src/severity.py",
            "base/tests/test_severity.py",
        ),
        (
            "pagination-boundary",
            "lib/pagination.py",
            "base/tests/test_pagination.py",
        ),
        (
            "retry-delay-cap",
            "src/retry_policy.py",
            "base/tests/test_retry_policy.py",
        ),
    ],
)
def test_live_repair_case_context_is_manifest_driven_and_redacted(
    case_id: str,
    changed_path: str,
    visible_test: str,
) -> None:
    context = prepare_live_repair_case_context(
        ROOT / "demo" / "cases" / case_id
    )

    assert context.case_id == case_id
    assert context.allowed_changed_paths == [changed_path]
    assert visible_test in [source.object_name for source in context.source_files]
    assert context.test_shell_command.startswith("pytest ")
    assert context.static_check_shell_command.startswith("python -m compileall ")
    assert len(context.case_fingerprint) == 64
    assert all("expected" not in source.object_name for source in context.source_files)
    assert all("hidden" not in source.object_name for source in context.source_files)
    assert all(not Path(source.source_path).is_absolute() for source in context.source_files)


def test_live_repair_submission_accepts_current_minimax_pair(tmp_path: Path) -> None:
    submission = _submission(
        tmp_path,
        provider="minimax-cn",
        model="MiniMax-M2.5",
    )

    parsed = LiveRepairSubmission.model_validate_json(
        submission.read_text(encoding="utf-8")
    )

    assert parsed.provider == "minimax-cn"
    assert parsed.model == "MiniMax-M2.5"


def test_live_repair_prepare_case_cli_writes_strict_context(tmp_path: Path) -> None:
    output = tmp_path / "case-context.json"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "agentloom.live_repair",
            "prepare-case",
            "--case-root",
            str(CASE),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    context = json.loads(output.read_text(encoding="utf-8"))
    assert context["caseId"] == "severity-normalization"
    assert context["allowedChangedPaths"] == ["src/severity.py"]
    assert str(ROOT) not in output.read_text(encoding="utf-8")


def test_agentteams_repair_and_sandbox_scripts_are_case_driven() -> None:
    repair_script = (
        ROOT / "deploy" / "agentteams" / "run-live-repair.ps1"
    ).read_text(encoding="utf-8")
    sandbox_script = (
        ROOT / "deploy" / "agentteams" / "run-sandbox-e2e.ps1"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "base/lib/pagination.py",
        "base/tests/test_pagination.py",
        "page_count",
        "lib/pagination.py may change",
    ):
        assert forbidden not in repair_script
    assert '"-m", "agentloom.live_repair", "prepare-case"' in repair_script
    assert '"--case-root", $resolvedCaseRoot' in repair_script
    assert '"--case-root", $resolvedCaseRoot' in sandbox_script


def test_agentteams_repair_runner_uses_installed_transport_contracts() -> None:
    repair_script = (
        ROOT / "deploy" / "agentteams" / "run-live-repair.ps1"
    ).read_text(encoding="utf-8")

    assert "filesync" not in repair_script
    assert "mc cp" in repair_script
    assert "copaw channels send" in repair_script
    assert repair_script.count("New-CoPawSendCommand") >= 4
    assert "Worker-local pytest is unavailable" in repair_script
    assert "TASK_ENVELOPE" in repair_script
    assert "$taskEnvelopeEvent = Send-MatrixText -RoomId $investigator.roomID" in repair_script
    assert "ENVELOPE_EVENT_ID_PLACEHOLDER" in repair_script
    assert "Execute the referenced TASK_ENVELOPE now." in repair_script


def test_live_repair_accepts_role_traced_patch_after_independent_verification(
    tmp_path: Path,
) -> None:
    submission = _submission(tmp_path)

    result = LiveRepairVerifier(CASE).run(
        submission_path=submission,
        output_root=tmp_path / "live-run",
    )

    assert result.provider == "dashscope"
    assert result.model == "qwen3.7-plus"
    assert result.bundle.verification.verdict == "PASSED"
    assert result.bundle.verification.checks.original_failure_reproduced
    assert result.bundle.verification.checks.target_tests_passed
    assert result.bundle.verification.checks.regression_tests_passed
    assert result.bundle.verification.checks.static_checks_passed
    assert not result.bundle.verification.checks.unauthorized_changes
    assert result.bundle.patch.changed_paths == ["src/severity.py"]
    assert {
        "live-repair-evidence.json",
        "repair.patch",
        "root-cause-report.json",
        "patch-artifact.json",
        "verification-result.json",
        "risk-report.json",
        "test-results.txt",
    } <= {path.name for path in result.artifacts_dir.iterdir()}

    evidence = json.loads(
        (result.artifacts_dir / "live-repair-evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["status"] == "PASS"
    assert evidence["model"] == "qwen3.7-plus"
    assert evidence["verifiedWorkspaceDigest"] == workspace_tree_digest(
        tmp_path / "live-run" / "verifier-workspace"
    )
    assert [trace["agentName"] for trace in evidence["roleEvents"]] == [
        "agentloom-investigator",
        "agentloom-implementer",
        "agentloom-verifier",
    ]
    assert [
        event["phase"] for event in evidence["coordinationTrace"]["events"]
    ] == [
        "MANAGER_DELEGATED",
        "IMPLEMENTER_ASSIGNED",
        "VERIFIER_ASSIGNED",
    ]
    assert "password" not in json.dumps(evidence).lower()
    assert "apiKey" not in json.dumps(evidence)


def test_live_repair_applies_patch_inside_ignored_repository_directory(
    tmp_path: Path,
) -> None:
    submission = _submission(tmp_path)
    payload = json.loads(submission.read_text(encoding="utf-8"))
    patch = (
        "diff --git a/src/severity.py b/src/severity.py\n"
        "index a76842a..f3d4ee4 100644\n"
        f"{payload['repairPatch']}"
    )
    patch_hash = sha256(patch.encode("utf-8")).hexdigest()
    payload["repairPatch"] = patch
    payload["bundle"]["patch"]["sha256"] = patch_hash
    payload["bundle"]["verification"]["patch_hash"] = patch_hash
    submission.write_text(json.dumps(payload), encoding="utf-8")
    ignored_parent = ROOT / ".tmp"
    ignored_parent.mkdir(exist_ok=True)
    ignored_root = Path(tempfile.mkdtemp(prefix="live-repair-", dir=ignored_parent))
    output_root = ignored_root / "output"
    try:
        result = LiveRepairVerifier(CASE).run(
            submission_path=submission,
            output_root=output_root,
        )

        assert result.bundle.verification.verdict == "PASSED"
        assert not (output_root / "workspace" / ".git").exists()
    finally:
        shutil.rmtree(ignored_root)


def test_live_repair_resolves_truthful_agent_uncertainty_with_host_tests(
    tmp_path: Path,
) -> None:
    submission = _submission(tmp_path)
    payload = json.loads(submission.read_text(encoding="utf-8"))
    role_verification = payload["bundle"]["verification"]
    role_verification["verdict"] = "UNCERTAIN"
    role_verification["checks"] = {
        "original_failure_reproduced": False,
        "target_tests_passed": False,
        "regression_tests_passed": False,
        "static_checks_passed": True,
        "unauthorized_changes": False,
    }
    role_verification["reason"] = (
        "Worker-local pytest is unavailable; static review passed and host "
        "verification is required."
    )
    submission.write_text(json.dumps(payload), encoding="utf-8")

    result = LiveRepairVerifier(CASE).run(
        submission_path=submission,
        output_root=tmp_path / "live-run",
    )

    assert result.role_verification.verdict == "UNCERTAIN"
    assert result.bundle.verification.verdict == "PASSED"
    assert result.bundle.verification.verifier_agent == "agentloom-host-verifier"
    assert {
        "agent-verification-result.json",
        "verification-result.json",
    } <= {path.name for path in result.artifacts_dir.iterdir()}
    evidence = json.loads(
        (result.artifacts_dir / "live-repair-evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["agentVerificationVerdict"] == "UNCERTAIN"
    assert evidence["hostVerificationVerdict"] == "PASSED"


def test_live_repair_rejects_patch_hash_not_bound_to_model_output(
    tmp_path: Path,
) -> None:
    submission = _submission(tmp_path)
    payload = json.loads(submission.read_text(encoding="utf-8"))
    payload["bundle"]["patch"]["sha256"] = "0" * 64
    payload["bundle"]["verification"]["patch_hash"] = "0" * 64
    submission.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LiveRepairError, match="repair.patch hash"):
        LiveRepairVerifier(CASE).run(submission, tmp_path / "live-run")


def test_live_repair_rejects_patch_outside_manifest_allowlist(
    tmp_path: Path,
) -> None:
    submission = _submission(tmp_path)
    payload = json.loads(submission.read_text(encoding="utf-8"))
    patch = payload["repairPatch"].replace("src/severity.py", "README.md")
    patch_hash = sha256(patch.encode("utf-8")).hexdigest()
    payload["repairPatch"] = patch
    payload["bundle"]["patch"]["sha256"] = patch_hash
    payload["bundle"]["patch"]["changedPaths"] = ["README.md"]
    payload["bundle"]["verification"]["patch_hash"] = patch_hash
    submission.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LiveRepairError, match="outside allowed paths"):
        LiveRepairVerifier(CASE).run(submission, tmp_path / "live-run")


def test_live_repair_rejects_missing_business_agent_trace(tmp_path: Path) -> None:
    submission = _submission(tmp_path)
    payload = json.loads(submission.read_text(encoding="utf-8"))
    payload["roleEvents"] = payload["roleEvents"][:2]
    submission.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LiveRepairError, match="three business Agent role events"):
        LiveRepairVerifier(CASE).run(submission, tmp_path / "live-run")


def test_live_repair_rejects_coordination_with_wrong_mentioned_agent(
    tmp_path: Path,
) -> None:
    submission = _submission(tmp_path)
    payload = json.loads(submission.read_text(encoding="utf-8"))
    assignment = payload["coordinationTrace"]["events"][1]
    assignment["mentionedAgent"] = "agentloom-verifier"
    assignment["mentionedUserId"] = "@agentloom-verifier:example.test"
    submission.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LiveRepairError, match="coordination phase does not match"):
        LiveRepairVerifier(CASE).run(submission, tmp_path / "live-run")


def test_live_repair_rejects_patch_that_only_passes_visible_tests(
    tmp_path: Path,
) -> None:
    submission = _submission(tmp_path)
    payload = json.loads(submission.read_text(encoding="utf-8"))
    before = (CASE / "before" / "src" / "severity.py").read_text(encoding="utf-8")
    after = before.replace(
        "normalized = value.upper()",
        'normalized = value.replace(" ", "").upper()',
    )
    patch = _unified_patch("src/severity.py", before, after)
    patch_hash = sha256(patch.encode("utf-8")).hexdigest()
    payload["repairPatch"] = patch
    payload["bundle"]["patch"]["sha256"] = patch_hash
    payload["bundle"]["verification"]["patch_hash"] = patch_hash
    submission.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LiveRepairError, match="hidden tests failed"):
        LiveRepairVerifier(CASE).run(submission, tmp_path / "live-run")


def _submission(
    tmp_path: Path,
    *,
    provider: str = "dashscope",
    model: str = "qwen3.7-plus",
) -> Path:
    mock = MockRepairRunner(CASE).run(tmp_path / "model-output")
    patch = (mock.artifacts_dir / "repair.patch").read_text(encoding="utf-8")
    bundle = mock.bundle.model_dump(mode="json", by_alias=True)
    task_id = mock.task.task_id
    traces = [
        {
            "agentName": "agentloom-investigator",
            "matrixUserId": "@agentloom-investigator:example.test",
            "roomId": "!repair-room:example.test",
            "eventId": "$investigator-event",
            "originServerTimestamp": 1_700_000_000_002,
        },
        {
            "agentName": "agentloom-implementer",
            "matrixUserId": "@agentloom-implementer:example.test",
            "roomId": "!repair-room:example.test",
            "eventId": "$implementer-event",
            "originServerTimestamp": 1_700_000_000_004,
        },
        {
            "agentName": "agentloom-verifier",
            "matrixUserId": "@agentloom-verifier:example.test",
            "roomId": "!repair-room:example.test",
            "eventId": "$verifier-event",
            "originServerTimestamp": 1_700_000_000_006,
        },
    ]
    coordination_trace = {
        "schemaVersion": "agentloom.coordination-trace/v1alpha1",
        "taskId": task_id,
        "events": [
            {
                "phase": "MANAGER_DELEGATED",
                "agentName": "agentloom-manager",
                "matrixUserId": "@admin:example.test",
                "mentionedAgent": "agentloom-investigator",
                "mentionedUserId": "@agentloom-investigator:example.test",
                "roomId": "!manager-room:example.test",
                "eventId": "$manager-delegated",
                "originServerTimestamp": 1_700_000_000_001,
            },
            {
                "phase": "IMPLEMENTER_ASSIGNED",
                "agentName": "agentloom-investigator",
                "matrixUserId": "@agentloom-investigator:example.test",
                "mentionedAgent": "agentloom-implementer",
                "mentionedUserId": "@agentloom-implementer:example.test",
                "roomId": "!repair-room:example.test",
                "eventId": "$implementer-assigned",
                "originServerTimestamp": 1_700_000_000_003,
            },
            {
                "phase": "VERIFIER_ASSIGNED",
                "agentName": "agentloom-investigator",
                "matrixUserId": "@agentloom-investigator:example.test",
                "mentionedAgent": "agentloom-verifier",
                "mentionedUserId": "@agentloom-verifier:example.test",
                "roomId": "!repair-room:example.test",
                "eventId": "$verifier-assigned",
                "originServerTimestamp": 1_700_000_000_005,
            },
        ],
    }
    bundle["rootCause"]["evidenceRefs"] = [traces[0]["eventId"]]
    bundle["patch"]["evidenceRefs"] = [traces[1]["eventId"]]
    bundle["verification"]["evidence_refs"] = [traces[2]["eventId"]]
    bundle["risk"]["evidenceRefs"] = [traces[2]["eventId"]]
    submission = tmp_path / "live-repair-submission.json"
    submission.write_text(
        json.dumps(
            {
                "schemaVersion": "agentloom.live-repair-submission/v1alpha1",
                "taskId": task_id,
                "provider": provider,
                "model": model,
                "coordinationTrace": coordination_trace,
                "roleEvents": traces,
                "repairPatch": patch,
                "bundle": bundle,
            }
        ),
        encoding="utf-8",
    )
    return submission


def _unified_patch(path: str, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
