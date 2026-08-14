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

