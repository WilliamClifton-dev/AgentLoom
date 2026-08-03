from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from agentloom.mock_artifact_e2e import MockArtifactE2E
from agentloom.namespace_bridge import NamespaceBridgeError

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "demo" / "cases"


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def exists(self, path: str) -> bool:
        return path in self.objects

    def read(self, path: str) -> bytes:
        try:
            return self.objects[path]
        except KeyError as exc:
            raise NamespaceBridgeError(f"missing object: {path}") from exc

    def write(self, path: str, content: bytes) -> None:
        self.objects[path] = content

    def copy(self, source: str, target: str) -> None:
        self.write(target, self.read(source))

    def mirror(self, source_prefix: str, target_prefix: str) -> None:
        for path, content in list(self.objects.items()):
            if path.startswith(source_prefix):
                self.write(
                    f"{target_prefix}{path.removeprefix(source_prefix)}",
                    content,
                )


@pytest.mark.parametrize(
    "case_id", ["severity-normalization", "pagination-boundary"]
)
def test_mock_artifact_e2e_round_trips_verified_outputs_across_namespaces(
    tmp_path: Path,
    case_id: str,
) -> None:
    storage = MemoryStorage()

    result = MockArtifactE2E(
        storage=storage,
        storage_prefix="hiclaw/hiclaw-storage",
        team_name="agentloom-repair",
        fixture_root=CASES / case_id,
    ).run(tmp_path / "run")

    layout = result.layout
    assert result.task.status == "COMPLETED"
    assert result.stage_evidence.action == "STAGE"
    assert result.collect_evidence.action == "COLLECT"
    assert result.bundle.verification.verdict == "PASSED"
    assert result.bundle.risk.verdict == "PASSED"
    assert storage.read(f"{layout.global_task_prefix}spec.md") == storage.read(
        f"{layout.team_task_prefix}spec.md"
    )
    assert storage.read(f"{layout.global_task_prefix}result.md").startswith(
        b"# Repair result"
    )
    repair_patch = storage.read(f"{layout.global_task_prefix}repair.patch")
    assert sha256(repair_patch).hexdigest() == result.bundle.patch.sha256
    assert set(result.collect_evidence.copied_files) == {
        "result.md",
        "root-cause-report.json",
        "repair.patch",
        "patch-artifact.json",
        "verification-result.json",
        "risk-report.json",
        "test-results.txt",
        "evidence.json",
    }

    evidence_path = result.output_root / "mock-artifact-e2e.json"
    assert evidence_path.is_file()
    evidence_text = evidence_path.read_text(encoding="utf-8")
    assert result.task.task_id in evidence_text
    assert "apiKey" not in evidence_text
    assert "password" not in evidence_text.lower()
