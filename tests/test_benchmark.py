from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentloom.benchmark import (
    BenchmarkCell,
    BenchmarkEvidence,
    BenchmarkReport,
    BenchmarkSuiteError,
    load_benchmark_suite,
    record_governed_benchmark_result,
    run_local_benchmark,
)

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "benchmarks" / "repair-v1.json"


def _evidence(kind: str, suffix: str) -> BenchmarkEvidence:
    return BenchmarkEvidence(
        kind=kind,
        uri=f"artifact://task24/{suffix}.json",
        sha256=suffix[0] * 64,
    )


def _cell(
    *,
    case_id: str,
    fingerprint: str,
    mode: str,
    status: str = "PASSED",
) -> BenchmarkCell:
    started_at = datetime(2026, 8, 15, tzinfo=UTC)
    evidence = (
        [_evidence("LOCAL_TASK_EVIDENCE", "a-local")]
        if mode == "LOCAL_DETERMINISTIC"
        else [
            _evidence("AGENTTEAMS_REPAIR", "b-repair"),
            _evidence("INDEPENDENT_VERIFICATION", "c-independent"),
            _evidence("GOVERNED_DOCKER_TOOLCALL", "d-toolcall"),
        ]
    )
    return BenchmarkCell(
        case_id=case_id,
        case_fingerprint=fingerprint,
        mode=mode,
        status=status,
        provider="minimax-cn" if mode == "AGENTTEAMS_GOVERNED" else None,
        model="MiniMax-M2.5" if mode == "AGENTTEAMS_GOVERNED" else None,
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=1),
        elapsed_ms=1000,
        evidence=evidence,
    )


def test_load_benchmark_suite_binds_three_versioned_case_fingerprints() -> None:
    suite = load_benchmark_suite(SUITE, repository_root=ROOT)

    assert suite.manifest.suite_id == "agentloom-repair-v1"
    assert suite.manifest.version == "1.0.0"
    assert [case.manifest.case_id for case in suite.cases] == [
        "severity-normalization",
        "pagination-boundary",
        "retry-delay-cap",
    ]
    assert len(suite.suite_digest) == 64
    assert all(len(fingerprint) == 64 for fingerprint in suite.case_fingerprints)


def test_load_benchmark_suite_rejects_case_fingerprint_drift(tmp_path: Path) -> None:
    payload = json.loads(SUITE.read_text(encoding="utf-8"))
    payload["cases"][0]["caseFingerprint"] = "0" * 64
    manifest = tmp_path / "suite.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BenchmarkSuiteError, match="fingerprint mismatch"):
        load_benchmark_suite(manifest, repository_root=ROOT)


def test_benchmark_cell_rejects_mode_provider_and_evidence_mislabeling() -> None:
    fingerprint = "e" * 64

    with pytest.raises(ValidationError, match="local deterministic"):
        _cell(
            case_id="severity-normalization",
            fingerprint=fingerprint,
            mode="LOCAL_DETERMINISTIC",
        ).model_copy(update={"provider": "minimax-cn"}, deep=True).model_validate(
            {
                **_cell(
                    case_id="severity-normalization",
                    fingerprint=fingerprint,
                    mode="LOCAL_DETERMINISTIC",
                ).model_dump(by_alias=True),
                "provider": "minimax-cn",
            }
        )

    governed = _cell(
        case_id="severity-normalization",
        fingerprint=fingerprint,
        mode="AGENTTEAMS_GOVERNED",
    ).model_dump(by_alias=True)
    governed["provider"] = "deepseek"
    with pytest.raises(ValidationError, match="MiniMax"):
        BenchmarkCell.model_validate(governed)

    governed["provider"] = "minimax-cn"
    governed["evidence"] = governed["evidence"][:2]
    with pytest.raises(ValidationError, match="three required evidence kinds"):
        BenchmarkCell.model_validate(governed)


def test_not_run_cell_cannot_carry_execution_claims() -> None:
    with pytest.raises(ValidationError, match="NOT_RUN"):
        BenchmarkCell(
            case_id="severity-normalization",
            case_fingerprint="f" * 64,
            mode="AGENTTEAMS_GOVERNED",
            status="NOT_RUN",
            reason="Provider unavailable.",
            provider="minimax-cn",
            model="MiniMax-M2.5",
            evidence=[_evidence("AGENTTEAMS_REPAIR", "a-notrun")],
        )


def test_report_requires_one_cell_per_case_and_mode() -> None:
    suite = load_benchmark_suite(SUITE, repository_root=ROOT)
    cells = [
        _cell(
            case_id=case.manifest.case_id,
            fingerprint=fingerprint,
            mode=mode,
        )
        for case, fingerprint in zip(
            suite.cases, suite.case_fingerprints, strict=True
        )
        for mode in ("LOCAL_DETERMINISTIC", "AGENTTEAMS_GOVERNED")
    ]

    report = BenchmarkReport(
        suite_id=suite.manifest.suite_id,
        suite_version=suite.manifest.version,
        suite_digest=suite.suite_digest,
        run_id="task24-contract-test",
        created_at=datetime(2026, 8, 15, tzinfo=UTC),
        complete=True,
        cells=cells,
    )
    assert len(report.cells) == 6

    with pytest.raises(ValidationError, match="duplicate mode/case"):
        BenchmarkReport(
            suite_id=suite.manifest.suite_id,
            suite_version=suite.manifest.version,
            suite_digest=suite.suite_digest,
            run_id="task24-duplicate-test",
            created_at=datetime(2026, 8, 15, tzinfo=UTC),
            complete=True,
            cells=[*cells[:-1], cells[0]],
        )


def test_run_local_benchmark_executes_all_three_cases_without_model(
    tmp_path: Path,
) -> None:
    suite = load_benchmark_suite(SUITE, repository_root=ROOT)

    report = run_local_benchmark(
        suite=suite,
        output_root=tmp_path / "local",
        run_id="task24-local-test",
    )

    assert not report.complete
    assert len(report.cells) == 6
    assert [cell.status for cell in report.cells[:3]] == ["PASSED"] * 3
    assert [cell.mode for cell in report.cells[:3]] == ["LOCAL_DETERMINISTIC"] * 3
    assert [cell.status for cell in report.cells[3:]] == ["NOT_RUN"] * 3
    assert all(cell.provider is None and cell.model is None for cell in report.cells)
    reopened = BenchmarkReport.model_validate_json(
        (tmp_path / "local" / "benchmark-report.json").read_text(encoding="utf-8")
    )
    assert reopened == report


def test_record_governed_result_binds_live_host_and_docker_evidence(
    tmp_path: Path,
) -> None:
    suite = load_benchmark_suite(SUITE, repository_root=ROOT)
    local = run_local_benchmark(
        suite=suite,
        output_root=tmp_path / "local",
        run_id="task24-governed-test",
    )
    case = suite.cases[0]
    fingerprint = suite.case_fingerprints[0]
    run_path, verified_path, sandbox_path = _governed_evidence_set(
        tmp_path / "governed",
        case_id=case.manifest.case_id,
        case_fingerprint=fingerprint,
    )

    updated = record_governed_benchmark_result(
        suite=suite,
        report_path=tmp_path / "local" / "benchmark-report.json",
        case_id=case.manifest.case_id,
        run_evidence_path=run_path,
        verified_evidence_path=verified_path,
        sandbox_evidence_path=sandbox_path,
        output_path=tmp_path / "benchmark-with-governed.json",
    )

    assert not updated.complete
    governed = next(
        cell
        for cell in updated.cells
        if cell.case_id == case.manifest.case_id
        and cell.mode == "AGENTTEAMS_GOVERNED"
    )
    assert governed.status == "PASSED"
    assert governed.provider == "minimax-cn"
    assert {evidence.kind for evidence in governed.evidence} == {
        "AGENTTEAMS_REPAIR",
        "INDEPENDENT_VERIFICATION",
        "GOVERNED_DOCKER_TOOLCALL",
    }
    assert local.cells[0] in updated.cells


def test_record_governed_result_rejects_different_verified_workspace(
    tmp_path: Path,
) -> None:
    suite = load_benchmark_suite(SUITE, repository_root=ROOT)
    run_local_benchmark(
        suite=suite,
        output_root=tmp_path / "local",
        run_id="task24-workspace-mismatch",
    )
    case = suite.cases[0]
    fingerprint = suite.case_fingerprints[0]
    run_path, verified_path, sandbox_path = _governed_evidence_set(
        tmp_path / "governed",
        case_id=case.manifest.case_id,
        case_fingerprint=fingerprint,
    )
    sandbox = json.loads(sandbox_path.read_text(encoding="utf-8"))
    sandbox["workspaceDigest"] = "9" * 64
    sandbox_path.write_text(json.dumps(sandbox), encoding="utf-8")

    with pytest.raises(BenchmarkSuiteError, match="workspace digest"):
        record_governed_benchmark_result(
            suite=suite,
            report_path=tmp_path / "local" / "benchmark-report.json",
            case_id=case.manifest.case_id,
            run_evidence_path=run_path,
            verified_evidence_path=verified_path,
            sandbox_evidence_path=sandbox_path,
            output_path=tmp_path / "rejected.json",
        )


def test_record_governed_result_rejects_docker_evidence_before_run_completion(
    tmp_path: Path,
) -> None:
    suite = load_benchmark_suite(SUITE, repository_root=ROOT)
    run_local_benchmark(
        suite=suite,
        output_root=tmp_path / "local",
        run_id="task24-timestamp-mismatch",
    )
    case = suite.cases[0]
    run_path, verified_path, sandbox_path = _governed_evidence_set(
        tmp_path / "governed",
        case_id=case.manifest.case_id,
        case_fingerprint=suite.case_fingerprints[0],
    )
    sandbox = json.loads(sandbox_path.read_text(encoding="utf-8"))
    sandbox["verifiedAt"] = "2026-08-15T00:00:30Z"
    sandbox_path.write_text(json.dumps(sandbox), encoding="utf-8")

    with pytest.raises(BenchmarkSuiteError, match="timestamps"):
        record_governed_benchmark_result(
            suite=suite,
            report_path=tmp_path / "local" / "benchmark-report.json",
            case_id=case.manifest.case_id,
            run_evidence_path=run_path,
            verified_evidence_path=verified_path,
            sandbox_evidence_path=sandbox_path,
            output_path=tmp_path / "rejected.json",
        )


def _governed_evidence_set(
    root: Path,
    *,
    case_id: str,
    case_fingerprint: str,
) -> tuple[Path, Path, Path]:
    root.mkdir(parents=True)
    task_id = f"task24-{case_id}"
    role_events = [
        {
            "agentName": "agentloom-investigator",
            "matrixUserId": "@agentloom-investigator:example.test",
            "roomId": "!repair:example.test",
            "eventId": "$investigator",
            "originServerTimestamp": 1_700_000_000_002,
        },
        {
            "agentName": "agentloom-implementer",
            "matrixUserId": "@agentloom-implementer:example.test",
            "roomId": "!repair:example.test",
            "eventId": "$implementer",
            "originServerTimestamp": 1_700_000_000_004,
        },
        {
            "agentName": "agentloom-verifier",
            "matrixUserId": "@agentloom-verifier:example.test",
            "roomId": "!repair:example.test",
            "eventId": "$verifier",
            "originServerTimestamp": 1_700_000_000_006,
        },
    ]
    coordination = {
        "schemaVersion": "agentloom.coordination-trace/v1alpha1",
        "taskId": task_id,
        "events": [
            {
                "phase": "MANAGER_DELEGATED",
                "agentName": "agentloom-manager",
                "matrixUserId": "@manager:example.test",
                "mentionedAgent": "agentloom-investigator",
                "mentionedUserId": "@agentloom-investigator:example.test",
                "roomId": "!manager:example.test",
                "eventId": "$manager-delegated",
                "originServerTimestamp": 1_700_000_000_001,
            },
            {
                "phase": "IMPLEMENTER_ASSIGNED",
                "agentName": "agentloom-investigator",
                "matrixUserId": "@agentloom-investigator:example.test",
                "mentionedAgent": "agentloom-implementer",
                "mentionedUserId": "@agentloom-implementer:example.test",
                "roomId": "!repair:example.test",
                "eventId": "$implementer-assigned",
                "originServerTimestamp": 1_700_000_000_003,
            },
            {
                "phase": "VERIFIER_ASSIGNED",
                "agentName": "agentloom-investigator",
                "matrixUserId": "@agentloom-investigator:example.test",
                "mentionedAgent": "agentloom-verifier",
                "mentionedUserId": "@agentloom-verifier:example.test",
                "roomId": "!repair:example.test",
                "eventId": "$verifier-assigned",
                "originServerTimestamp": 1_700_000_000_005,
            },
        ],
    }
    started = "2026-08-15T00:00:00Z"
    verified_at = "2026-08-15T00:01:00Z"
    workspace_digest = "8" * 64
    run_path = root / "agentteams-run.json"
    run_path.write_text(
        json.dumps(
            {
                "schemaVersion": "agentloom.live-repair-run/v1alpha1",
                "taskId": task_id,
                "caseId": case_id,
                "caseFingerprint": case_fingerprint,
                "provider": "minimax-cn",
                "model": "MiniMax-M2.5",
                "startedAt": started,
                "verifiedAt": verified_at,
                "status": "SUBMISSION_READY",
                "strict": True,
                "criteria": {
                    "senderMustMatchRole": True,
                    "eventMustFollowTaskStart": True,
                    "markerMustBeIndependentTrimmedLine": True,
                    "resultObjectsMustFollowTaskStart": True,
                    "hiddenAndExpectedObjectsForbidden": True,
                    "resultObjectsMustBeAllowlisted": True,
                    "inputObjectsRemainUnchanged": True,
                    "completionEventMustFollowArtifacts": True,
                    "coordinationEventsMustMatchMentions": True,
                },
                "inputObjects": [],
                "coordinationTrace": coordination,
                "roleEvents": [
                    {
                        "key": str(event["agentName"]).removeprefix("agentloom-"),
                        "agentName": event["agentName"],
                        "sender": event["matrixUserId"],
                        "roomId": event["roomId"],
                        "eventId": event["eventId"],
                        "originServerTimestamp": event["originServerTimestamp"],
                    }
                    for event in role_events
                ],
                "objects": [],
                "submissionSha256": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    verified_path = root / "live-repair-evidence.json"
    verified_path.write_text(
        json.dumps(
            {
                "schemaVersion": "agentloom.live-repair-evidence/v1alpha1",
                "status": "PASS",
                "taskId": task_id,
                "caseId": case_id,
                "caseFingerprint": case_fingerprint,
                "caseSnapshotSha256": "sha256:" + "7" * 64,
                "provider": "minimax-cn",
                "model": "MiniMax-M2.5",
                "submissionSha256": "a" * 64,
                "patchSha256": "b" * 64,
                "testResultsSha256": "c" * 64,
                "verifiedWorkspaceDigest": workspace_digest,
                "roleEvents": role_events,
                "coordinationTrace": coordination,
                "independentVerification": {
                    "originalFailureReproduced": True,
                    "targetTestsPassed": True,
                    "regressionTestsPassed": True,
                    "hiddenTestsPassed": True,
                    "staticChecksPassed": True,
                    "unauthorizedChanges": False,
                },
            }
        ),
        encoding="utf-8",
    )
    sandbox_path = root / "sandbox-run.json"
    sandbox_path.write_text(
        json.dumps(
            {
                "schemaVersion": "agentloom.agentteams-sandbox-e2e/v1alpha1",
                "runId": f"sandbox-{case_id}",
                "verifiedAt": "2026-08-15T00:02:00Z",
                "status": "DIRECT_PASS",
                "sandboxImage": "sha256:" + "d" * 64,
                "workspaceDigest": workspace_digest,
                "caseId": case_id,
                "caseFingerprint": case_fingerprint,
                "wrongConsumerDenied": True,
                "replayDenied": True,
                "direct": {
                    "taskId": f"sandbox-task-{case_id}",
                    "providerId": "sandboxed-test-runner/docker-sandbox",
                    "evidenceRef": f"ev-tool-{case_id}",
                    "outputDigest": "e" * 64,
                },
            }
        ),
        encoding="utf-8",
    )
    return run_path, verified_path, sandbox_path
