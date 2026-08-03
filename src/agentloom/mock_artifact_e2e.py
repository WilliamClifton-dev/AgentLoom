"""Offline repair artifact E2E across AgentTeams storage namespaces."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from agentloom.contracts import (
    PatchArtifact,
    RepairArtifactBundle,
    RiskReport,
    RootCauseReport,
    TaskRecord,
    VerificationResult,
)
from agentloom.demo_case import load_demo_case
from agentloom.mock_repair import MockRepairRunner
from agentloom.namespace_bridge import (
    ALLOWED_RESULT_FILES,
    DockerMcStorage,
    NamespaceBridge,
    NamespaceBridgeEvidence,
    NamespaceLayout,
    NamespaceStorage,
    discover_storage_prefix,
)


class WritableNamespaceStorage(NamespaceStorage, Protocol):
    def write(self, path: str, content: bytes) -> None: ...


@dataclass(frozen=True)
class MockArtifactE2EResult:
    output_root: Path
    task: TaskRecord
    bundle: RepairArtifactBundle
    layout: NamespaceLayout
    stage_evidence: NamespaceBridgeEvidence
    collect_evidence: NamespaceBridgeEvidence


class MockArtifactE2E:
    """Publish, bridge, collect, and revalidate one deterministic repair run."""

    def __init__(
        self,
        *,
        storage: WritableNamespaceStorage,
        storage_prefix: str,
        team_name: str,
        fixture_root: Path,
    ) -> None:
        self._storage = storage
        self._storage_prefix = storage_prefix
        self._team_name = team_name
        self._fixture_root = fixture_root.resolve()
        self._case = load_demo_case(self._fixture_root)

    def run(self, output_root: Path) -> MockArtifactE2EResult:
        root = output_root.resolve()
        if root.exists() and any(root.iterdir()):
            raise ValueError(f"output directory must be empty: {root}")

        local_result = MockRepairRunner(self._fixture_root).run(root / "local")
        layout = NamespaceLayout.build(
            storage_prefix=self._storage_prefix,
            team_name=self._team_name,
            task_id=local_result.task.task_id,
        )
        self._publish_parent(layout, local_result.task)
        bridge = NamespaceBridge(self._storage)
        stage_evidence = bridge.stage(layout)

        for name in ALLOWED_RESULT_FILES:
            artifact = local_result.artifacts_dir / name
            if artifact.is_file():
                self._storage.write(
                    f"{layout.team_task_prefix}{name}",
                    artifact.read_bytes(),
                )

        collect_evidence = bridge.collect(layout)
        bundle = self._load_collected_bundle(layout)
        patch_content = self._storage.read(f"{layout.global_task_prefix}repair.patch")
        if sha256(patch_content).hexdigest() != bundle.patch.sha256:
            raise ValueError("collected repair.patch does not match PatchArtifact")

        evidence_path = root / "mock-artifact-e2e.json"
        evidence_path.write_text(
            json.dumps(
                {
                    "schemaVersion": "agentloom.mock-artifact-e2e/v1alpha1",
                    "taskId": local_result.task.task_id,
                    "taskStatus": local_result.task.status,
                    "verificationVerdict": bundle.verification.verdict,
                    "riskVerdict": bundle.risk.verdict,
                    "patchSha256": bundle.patch.sha256,
                    "stage": stage_evidence.to_dict(),
                    "collect": collect_evidence.to_dict(),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return MockArtifactE2EResult(
            output_root=root,
            task=local_result.task,
            bundle=bundle,
            layout=layout,
            stage_evidence=stage_evidence,
            collect_evidence=collect_evidence,
        )

    def _publish_parent(self, layout: NamespaceLayout, task: TaskRecord) -> None:
        spec = _task_spec(task).encode("utf-8")
        self._storage.write(f"{layout.global_task_prefix}spec.md", spec)
        before_root = self._case.source_root
        for path in sorted(before_root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                relative = path.relative_to(before_root).as_posix()
                self._storage.write(
                    f"{layout.global_task_prefix}base/{relative}",
                    path.read_bytes(),
                )

    def _load_collected_bundle(self, layout: NamespaceLayout) -> RepairArtifactBundle:
        root_cause = RootCauseReport.model_validate_json(
            self._storage.read(
                f"{layout.global_task_prefix}root-cause-report.json"
            )
        )
        patch = PatchArtifact.model_validate_json(
            self._storage.read(f"{layout.global_task_prefix}patch-artifact.json")
        )
        verification = VerificationResult.model_validate_json(
            self._storage.read(
                f"{layout.global_task_prefix}verification-result.json"
            )
        )
        risk = RiskReport.model_validate_json(
            self._storage.read(f"{layout.global_task_prefix}risk-report.json")
        )
        return RepairArtifactBundle(
            root_cause=root_cause,
            patch=patch,
            verification=verification,
            risk=risk,
        )


def _task_spec(task: TaskRecord) -> str:
    acceptance = "\n".join(f"- {item}" for item in task.acceptance_criteria)
    allowed_paths = "\n".join(f"- {item}" for item in task.allowed_paths)
    return (
        f"# Parent repair task: {task.task_id}\n\n"
        f"## Issue\n{task.issue}\n\n"
        f"## Acceptance criteria\n{acceptance}\n\n"
        f"## Allowed paths\n{allowed_paths}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the offline repair artifact E2E against AgentTeams MinIO."
    )
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "demo"
        / "cases"
        / "severity-normalization",
    )
    parser.add_argument("--team-name", default="agentloom-repair")
    parser.add_argument("--controller", default="hiclaw-controller")
    parser.add_argument("--storage-prefix")
    arguments = parser.parse_args()

    try:
        storage_prefix = arguments.storage_prefix or discover_storage_prefix(
            arguments.controller
        )
        result = MockArtifactE2E(
            storage=DockerMcStorage(arguments.controller),
            storage_prefix=storage_prefix,
            team_name=arguments.team_name,
            fixture_root=arguments.fixture_root,
        ).run(arguments.output_root)
        print(
            json.dumps(
                {
                    "taskId": result.task.task_id,
                    "status": result.task.status,
                    "verificationVerdict": result.bundle.verification.verdict,
                    "riskVerdict": result.bundle.risk.verdict,
                    "patchSha256": result.bundle.patch.sha256,
                    "evidencePath": str(
                        result.output_root / "mock-artifact-e2e.json"
                    ),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (OSError, RuntimeError, ValueError, UnicodeError) as exc:
        print(f"mock artifact E2E failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
