from __future__ import annotations

import difflib
import json
from hashlib import sha256
from pathlib import Path

import pytest

from agentloom.live_repair import LiveRepairError, LiveRepairVerifier
from agentloom.mock_repair import MockRepairRunner

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "demo" / "cases" / "severity-normalization"


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


def _submission(tmp_path: Path) -> Path:
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
                "provider": "dashscope",
                "model": "qwen3.7-plus",
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
