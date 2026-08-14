"""Versioned, evidence-bound comparison of AgentLoom repair execution modes."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, field_validator, model_validator

from agentloom.contracts import ContractModel
from agentloom.demo_case import DemoCase, load_demo_case, snapshot_sha256
from agentloom.mock_repair import MockRepairRunner

BenchmarkMode = Literal["LOCAL_DETERMINISTIC", "AGENTTEAMS_GOVERNED"]
BenchmarkStatus = Literal["PASSED", "FAILED", "NOT_RUN"]
BenchmarkEvidenceKind = Literal[
    "LOCAL_TASK_EVIDENCE",
    "AGENTTEAMS_REPAIR",
    "INDEPENDENT_VERIFICATION",
    "GOVERNED_DOCKER_TOOLCALL",
    "RUNTIME_MEASUREMENTS",
]

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_GOVERNED_EVIDENCE = {
    "AGENTTEAMS_REPAIR",
    "INDEPENDENT_VERIFICATION",
    "GOVERNED_DOCKER_TOOLCALL",
}


class BenchmarkSuiteError(RuntimeError):
    """Raised when a benchmark suite no longer matches its frozen Cases."""


class BenchmarkCaseRef(ContractModel):
    case_id: str = Field(alias="caseId", pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    case_root: str = Field(alias="caseRoot", min_length=1, max_length=300)
    case_fingerprint: str = Field(
        alias="caseFingerprint", pattern=r"^[a-f0-9]{64}$"
    )

    @field_validator("case_root")
    @classmethod
    def case_root_is_safe(cls, value: str) -> str:
        if "\\" in value or "\x00" in value:
            raise ValueError("caseRoot must use safe POSIX syntax")
        path = PurePosixPath(value)
        if path.is_absolute() or value in {"", "."} or ".." in path.parts:
            raise ValueError("caseRoot must be a normalized repository-relative path")
        if path.as_posix() != value:
            raise ValueError("caseRoot must be normalized")
        return value


class BenchmarkSuiteManifest(ContractModel):
    schema_version: Literal["agentloom.repair-benchmark-suite/v1alpha1"] = Field(
        alias="schemaVersion"
    )
    suite_id: str = Field(
        alias="suiteId", pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )
    version: str
    cases: list[BenchmarkCaseRef] = Field(min_length=3, max_length=5)

    @field_validator("version")
    @classmethod
    def version_is_semver(cls, value: str) -> str:
        if not _SEMVER.fullmatch(value):
            raise ValueError("benchmark version must be MAJOR.MINOR.PATCH")
        return value

    @model_validator(mode="after")
    def cases_are_unique(self) -> BenchmarkSuiteManifest:
        case_ids = [case.case_id for case in self.cases]
        roots = [case.case_root for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("benchmark case IDs must be unique")
        if len(roots) != len(set(roots)):
            raise ValueError("benchmark case roots must be unique")
        return self


@dataclass(frozen=True)
class LoadedBenchmarkSuite:
    manifest: BenchmarkSuiteManifest
    cases: tuple[DemoCase, ...]
    case_fingerprints: tuple[str, ...]
    suite_digest: str


class BenchmarkEvidence(ContractModel):
    kind: BenchmarkEvidenceKind
    uri: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("uri")
    @classmethod
    def uri_is_redacted_artifact_reference(cls, value: str) -> str:
        prefix = "artifact://"
        if not value.startswith(prefix) or "\\" in value or "\x00" in value:
            raise ValueError("benchmark Evidence URI must use artifact://")
        path = PurePosixPath(value.removeprefix(prefix))
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise ValueError("benchmark Evidence URI is unsafe")
        return value


class BenchmarkCell(ContractModel):
    case_id: str = Field(alias="caseId", pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    case_fingerprint: str = Field(
        alias="caseFingerprint", pattern=r"^[a-f0-9]{64}$"
    )
    mode: BenchmarkMode
    status: BenchmarkStatus
    provider: str | None = None
    model: str | None = None
    started_at: datetime | None = Field(default=None, alias="startedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")
    elapsed_ms: int | None = Field(default=None, alias="elapsedMs", ge=0)
    llm_latency_ms: int | None = Field(default=None, alias="llmLatencyMs", ge=0)
    tool_latency_ms: int | None = Field(default=None, alias="toolLatencyMs", ge=0)
    input_tokens: int | None = Field(default=None, alias="inputTokens", ge=0)
    output_tokens: int | None = Field(default=None, alias="outputTokens", ge=0)
    estimated_cost_usd: float | None = Field(
        default=None, alias="estimatedCostUsd", ge=0
    )
    evidence: list[BenchmarkEvidence] = Field(default_factory=list)
    reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def claims_match_execution_mode(self) -> BenchmarkCell:
        advanced_metrics = (
            self.llm_latency_ms,
            self.tool_latency_ms,
            self.input_tokens,
            self.output_tokens,
            self.estimated_cost_usd,
        )
        evidence_kinds = {item.kind for item in self.evidence}
        if self.status == "NOT_RUN":
            if self.reason is None:
                raise ValueError("NOT_RUN requires a reason")
            if any(
                value is not None
                for value in (
                    self.provider,
                    self.model,
                    self.started_at,
                    self.finished_at,
                    self.elapsed_ms,
                    *advanced_metrics,
                )
            ) or self.evidence:
                raise ValueError("NOT_RUN cannot carry execution claims")
            return self

        if (
            self.started_at is None
            or self.finished_at is None
            or self.elapsed_ms is None
        ):
            raise ValueError("executed benchmark cells require measured timing")
        if self.finished_at < self.started_at:
            raise ValueError("benchmark finish time precedes start time")
        if self.status == "PASSED" and self.reason is not None:
            raise ValueError("PASSED benchmark cells cannot carry a failure reason")
        if self.status == "FAILED" and self.reason is None:
            raise ValueError("FAILED benchmark cells require a reason")
        if any(value is not None for value in advanced_metrics) and (
            "RUNTIME_MEASUREMENTS" not in evidence_kinds
        ):
            raise ValueError("optional runtime metrics require measurement Evidence")

        if self.mode == "LOCAL_DETERMINISTIC":
            if self.provider is not None or self.model is not None:
                raise ValueError("local deterministic cells cannot claim a Provider")
            if any(
                value is not None
                for value in (
                    self.llm_latency_ms,
                    self.input_tokens,
                    self.output_tokens,
                    self.estimated_cost_usd,
                )
            ):
                raise ValueError("local deterministic cells cannot claim LLM metrics")
            if self.status == "PASSED" and "LOCAL_TASK_EVIDENCE" not in evidence_kinds:
                raise ValueError("local deterministic PASS requires task Evidence")
            return self

        if self.provider != "minimax-cn" or self.model != "MiniMax-M2.5":
            raise ValueError("executed governed cells require the authorized MiniMax pair")
        if self.status == "PASSED" and not _GOVERNED_EVIDENCE <= evidence_kinds:
            raise ValueError("governed PASS requires the three required evidence kinds")
        return self


class BenchmarkReport(ContractModel):
    schema_version: Literal["agentloom.repair-benchmark/v1alpha1"] = Field(
        default="agentloom.repair-benchmark/v1alpha1", alias="schemaVersion"
    )
    suite_id: str = Field(
        alias="suiteId", pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )
    suite_version: str = Field(alias="suiteVersion")
    suite_digest: str = Field(alias="suiteDigest", pattern=r"^[a-f0-9]{64}$")
    run_id: str = Field(alias="runId", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    created_at: datetime = Field(alias="createdAt")
    complete: bool
    cells: list[BenchmarkCell] = Field(min_length=6, max_length=10)

    @model_validator(mode="after")
    def matrix_is_complete_and_unmixed(self) -> BenchmarkReport:
        keys = [(cell.case_id, cell.mode) for cell in self.cells]
        if len(keys) != len(set(keys)):
            raise ValueError("benchmark report contains a duplicate mode/case cell")
        case_ids = {cell.case_id for cell in self.cells}
        if not 3 <= len(case_ids) <= 5:
            raise ValueError("benchmark report must cover 3-5 cases")
        expected = {
            (case_id, mode)
            for case_id in case_ids
            for mode in ("LOCAL_DETERMINISTIC", "AGENTTEAMS_GOVERNED")
        }
        if set(keys) != expected:
            raise ValueError("benchmark report must contain both modes for every case")
        fingerprints: dict[str, set[str]] = {}
        for cell in self.cells:
            fingerprints.setdefault(cell.case_id, set()).add(cell.case_fingerprint)
        if any(len(values) != 1 for values in fingerprints.values()):
            raise ValueError("benchmark report mixes Case fingerprints")
        actually_complete = all(cell.status != "NOT_RUN" for cell in self.cells)
        if self.complete != actually_complete:
            raise ValueError("benchmark complete flag does not match cell execution state")
        return self


def benchmark_case_fingerprint(case: DemoCase) -> str:
    """Hash every trusted input that can affect one benchmark outcome."""

    digest = sha256()
    manifest = json.dumps(
        case.manifest.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    provenance = json.dumps(
        case.provenance.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    issue = case.issue.replace("\r\n", "\n").encode("utf-8")
    parts = (
        ("manifest", manifest),
        ("provenance", provenance),
        ("issue", issue),
        ("source", snapshot_sha256(case.source_root).encode("ascii")),
        ("expected", snapshot_sha256(case.expected_patch_root).encode("ascii")),
        ("hidden", snapshot_sha256(case.hidden_tests_root).encode("ascii")),
    )
    for label, content in parts:
        label_bytes = label.encode("ascii")
        digest.update(len(label_bytes).to_bytes(8, "big"))
        digest.update(label_bytes)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def load_benchmark_suite(
    manifest_path: Path,
    *,
    repository_root: Path,
) -> LoadedBenchmarkSuite:
    """Open one frozen suite and fail if any Case identity has drifted."""

    root = repository_root.resolve()
    try:
        manifest = BenchmarkSuiteManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except OSError as exc:
        raise BenchmarkSuiteError("benchmark suite manifest is unavailable") from exc
    cases: list[DemoCase] = []
    fingerprints: list[str] = []
    for reference in manifest.cases:
        case_root = (root / reference.case_root).resolve()
        if not case_root.is_relative_to(root):
            raise BenchmarkSuiteError("benchmark Case escapes the repository root")
        case = load_demo_case(case_root)
        if case.manifest.case_id != reference.case_id:
            raise BenchmarkSuiteError(
                f"benchmark Case ID mismatch for {reference.case_id}"
            )
        fingerprint = benchmark_case_fingerprint(case)
        if fingerprint != reference.case_fingerprint:
            raise BenchmarkSuiteError(
                f"benchmark Case fingerprint mismatch for {reference.case_id}"
            )
        cases.append(case)
        fingerprints.append(fingerprint)
    canonical = json.dumps(
        manifest.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return LoadedBenchmarkSuite(
        manifest=manifest,
        cases=tuple(cases),
        case_fingerprints=tuple(fingerprints),
        suite_digest=sha256(canonical).hexdigest(),
    )


def run_local_benchmark(
    *,
    suite: LoadedBenchmarkSuite,
    output_root: Path,
    run_id: str,
) -> BenchmarkReport:
    """Execute every deterministic Case and leave governed cells as NOT_RUN."""

    if not _IDENTIFIER.fullmatch(run_id):
        raise ValueError("benchmark run ID is invalid")
    root = output_root.resolve()
    if root.exists() and any(root.iterdir()):
        raise BenchmarkSuiteError(f"benchmark output directory must be empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    local_cells: list[BenchmarkCell] = []
    for case, fingerprint in zip(
        suite.cases, suite.case_fingerprints, strict=True
    ):
        started_at = datetime.now(UTC)
        started = time.perf_counter_ns()
        result = MockRepairRunner(case.root).run(root / case.manifest.case_id)
        elapsed_ms = (time.perf_counter_ns() - started) // 1_000_000
        finished_at = datetime.now(UTC)
        bundle_path = result.artifacts_dir / "task-evidence-bundle.json"
        local_cells.append(
            BenchmarkCell(
                case_id=case.manifest.case_id,
                case_fingerprint=fingerprint,
                mode="LOCAL_DETERMINISTIC",
                status="PASSED",
                started_at=started_at,
                finished_at=finished_at,
                elapsed_ms=elapsed_ms,
                evidence=[
                    BenchmarkEvidence(
                        kind="LOCAL_TASK_EVIDENCE",
                        uri=(
                            f"artifact://{run_id}/{case.manifest.case_id}/"
                            "artifacts/task-evidence-bundle.json"
                        ),
                        sha256=sha256(bundle_path.read_bytes()).hexdigest(),
                    )
                ],
            )
        )
    governed_cells = [
        BenchmarkCell(
            case_id=case.manifest.case_id,
            case_fingerprint=fingerprint,
            mode="AGENTTEAMS_GOVERNED",
            status="NOT_RUN",
            reason="No governed AgentTeams result was supplied for this local run.",
        )
        for case, fingerprint in zip(
            suite.cases, suite.case_fingerprints, strict=True
        )
    ]
    report = BenchmarkReport(
        suite_id=suite.manifest.suite_id,
        suite_version=suite.manifest.version,
        suite_digest=suite.suite_digest,
        run_id=run_id,
        created_at=datetime.now(UTC),
        complete=False,
        cells=[*local_cells, *governed_cells],
    )
    report_path = root / "benchmark-report.json"
    report_path.write_text(
        json.dumps(
            report.model_dump(mode="json", by_alias=True),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report

