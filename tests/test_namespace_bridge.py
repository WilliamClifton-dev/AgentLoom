from __future__ import annotations

import json
import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

from agentloom.namespace_bridge import (
    ALLOWED_RESULT_FILES,
    DockerMcStorage,
    NamespaceBridge,
    NamespaceBridgeError,
    NamespaceLayout,
    discover_storage_prefix,
    write_evidence,
)


class MemoryStorage:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = dict(objects)

    def exists(self, path: str) -> bool:
        return path in self.objects

    def read(self, path: str) -> bytes:
        try:
            return self.objects[path]
        except KeyError as exc:
            raise NamespaceBridgeError(f"missing object: {path}") from exc

    def copy(self, source: str, target: str) -> None:
        self.objects[target] = self.read(source)

    def mirror(self, source_prefix: str, target_prefix: str) -> None:
        for path, content in list(self.objects.items()):
            if path.startswith(source_prefix):
                relative = path.removeprefix(source_prefix)
                self.objects[f"{target_prefix}{relative}"] = content


def make_layout() -> NamespaceLayout:
    return NamespaceLayout.build(
        storage_prefix="hiclaw/hiclaw-storage",
        team_name="agentloom-repair",
        task_id="AL-MOCK-001",
    )


def test_layout_maps_manager_parent_task_to_team_private_namespace() -> None:
    layout = make_layout()

    assert layout.global_task_prefix == (
        "hiclaw/hiclaw-storage/shared/tasks/AL-MOCK-001/"
    )
    assert layout.team_task_prefix == (
        "hiclaw/hiclaw-storage/teams/agentloom-repair/"
        "shared/tasks/AL-MOCK-001/"
    )


@pytest.mark.parametrize(
    ("team_name", "task_id"),
    [
        ("../other-team", "AL-MOCK-001"),
        ("agentloom-repair", "../escape"),
        ("agentloom/rewrite", "AL-MOCK-001"),
        ("agentloom-repair", ""),
    ],
)
def test_layout_rejects_namespace_traversal(team_name: str, task_id: str) -> None:
    with pytest.raises(ValueError, match="safe identifier"):
        NamespaceLayout.build(
            storage_prefix="hiclaw/hiclaw-storage",
            team_name=team_name,
            task_id=task_id,
        )


def test_stage_copies_parent_task_and_records_verified_spec_hash() -> None:
    layout = make_layout()
    spec = b"# Repair fixture\n"
    storage = MemoryStorage(
        {
            f"{layout.global_task_prefix}spec.md": spec,
            f"{layout.global_task_prefix}base/input.txt": b"fixture\n",
        }
    )

    evidence = NamespaceBridge(storage).stage(layout)

    assert storage.read(f"{layout.team_task_prefix}spec.md") == spec
    assert storage.read(f"{layout.team_task_prefix}base/input.txt") == b"fixture\n"
    assert evidence.action == "STAGE"
    assert evidence.spec_sha256 == sha256(spec).hexdigest()
    assert evidence.copied_files == ()


def test_stage_refuses_to_overwrite_a_different_team_parent_task() -> None:
    layout = make_layout()
    storage = MemoryStorage(
        {
            f"{layout.global_task_prefix}spec.md": b"expected",
            f"{layout.team_task_prefix}spec.md": b"different",
        }
    )

    with pytest.raises(NamespaceBridgeError, match="spec hash mismatch"):
        NamespaceBridge(storage).stage(layout)

    assert storage.read(f"{layout.team_task_prefix}spec.md") == b"different"


def test_collect_copies_only_allowlisted_outputs_after_spec_verification() -> None:
    layout = make_layout()
    spec = b"immutable spec"
    result_files = {
        name: f"content for {name}".encode() for name in ALLOWED_RESULT_FILES
    }
    storage = MemoryStorage(
        {
            f"{layout.global_task_prefix}spec.md": spec,
            f"{layout.team_task_prefix}spec.md": spec,
            **{
                f"{layout.team_task_prefix}{name}": content
                for name, content in result_files.items()
            },
            f"{layout.team_task_prefix}workspace/private.txt": b"do not collect",
            f"{layout.team_task_prefix}meta.json": b"team-owned metadata",
        }
    )

    evidence = NamespaceBridge(storage).collect(layout)

    assert evidence.action == "COLLECT"
    assert set(evidence.copied_files) == set(ALLOWED_RESULT_FILES)
    for name, content in result_files.items():
        assert storage.read(f"{layout.global_task_prefix}{name}") == content
    assert not storage.exists(f"{layout.global_task_prefix}workspace/private.txt")
    assert not storage.exists(f"{layout.global_task_prefix}meta.json")


def test_collect_fails_closed_when_leader_mutates_parent_spec() -> None:
    layout = make_layout()
    storage = MemoryStorage(
        {
            f"{layout.global_task_prefix}spec.md": b"manager spec",
            f"{layout.team_task_prefix}spec.md": b"mutated spec",
            f"{layout.team_task_prefix}result.md": b"STATUS: SUCCESS",
        }
    )

    with pytest.raises(NamespaceBridgeError, match="spec hash mismatch"):
        NamespaceBridge(storage).collect(layout)

    assert not storage.exists(f"{layout.global_task_prefix}result.md")


def test_collect_requires_a_team_owned_result() -> None:
    layout = make_layout()
    storage = MemoryStorage(
        {
            f"{layout.global_task_prefix}spec.md": b"same",
            f"{layout.team_task_prefix}spec.md": b"same",
        }
    )

    with pytest.raises(NamespaceBridgeError, match="result.md"):
        NamespaceBridge(storage).collect(layout)


class CommandRunner:
    def __init__(self, responses: list[subprocess.CompletedProcess[bytes]]) -> None:
        self.responses = list(responses)
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess[bytes]:
        self.commands.append(command)
        return self.responses.pop(0)


def completed(
    *, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_docker_storage_uses_argument_arrays_for_minio_operations() -> None:
    runner = CommandRunner(
        [
            completed(),
            completed(stdout=b"spec"),
            completed(),
            completed(),
        ]
    )
    storage = DockerMcStorage("hiclaw-controller", runner=runner)

    assert storage.exists("hiclaw/hiclaw-storage/shared/tasks/T/spec.md")
    assert storage.read("hiclaw/hiclaw-storage/shared/tasks/T/spec.md") == b"spec"
    storage.copy("source/result.md", "target/result.md")
    storage.mirror("source/", "target/")

    assert runner.commands == [
        [
            "docker",
            "exec",
            "hiclaw-controller",
            "mc",
            "stat",
            "hiclaw/hiclaw-storage/shared/tasks/T/spec.md",
        ],
        [
            "docker",
            "exec",
            "hiclaw-controller",
            "mc",
            "cat",
            "hiclaw/hiclaw-storage/shared/tasks/T/spec.md",
        ],
        [
            "docker",
            "exec",
            "hiclaw-controller",
            "mc",
            "cp",
            "source/result.md",
            "target/result.md",
        ],
        [
            "docker",
            "exec",
            "hiclaw-controller",
            "mc",
            "mirror",
            "source/",
            "target/",
            "--overwrite",
        ],
    ]


def test_docker_storage_redacts_command_output_on_failure() -> None:
    runner = CommandRunner(
        [completed(returncode=1, stderr=b"provider-secret-should-not-escape")]
    )
    storage = DockerMcStorage("hiclaw-controller", runner=runner)

    with pytest.raises(NamespaceBridgeError, match="mc cp failed") as error:
        storage.copy("source", "target")

    assert "provider-secret" not in str(error.value)


def test_storage_prefix_is_discovered_without_exposing_other_environment() -> None:
    runner = CommandRunner([completed(stdout=b"hiclaw/hiclaw-storage\n")])

    prefix = discover_storage_prefix("hiclaw-controller", runner=runner)

    assert prefix == "hiclaw/hiclaw-storage"
    assert runner.commands == [
        [
            "docker",
            "exec",
            "hiclaw-controller",
            "printenv",
            "HICLAW_STORAGE_PREFIX",
        ]
    ]


def test_evidence_writer_emits_camel_case_secret_free_json(tmp_path: Path) -> None:
    layout = make_layout()
    spec = b"spec"
    storage = MemoryStorage(
        {
            f"{layout.global_task_prefix}spec.md": spec,
            f"{layout.team_task_prefix}spec.md": spec,
            f"{layout.team_task_prefix}result.md": b"STATUS: SUCCESS",
        }
    )
    evidence = NamespaceBridge(storage).collect(layout)
    evidence_path = tmp_path / "bridge.json"

    write_evidence(evidence, evidence_path)

    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["action"] == "COLLECT"
    assert payload["taskId"] == "AL-MOCK-001"
    assert payload["teamName"] == "agentloom-repair"
    assert payload["specSha256"] == sha256(spec).hexdigest()
    assert payload["copiedFiles"] == ["result.md"]
    assert payload["fileSha256"]["result.md"]
    assert "password" not in evidence_path.read_text(encoding="utf-8").lower()
    assert "token" not in evidence_path.read_text(encoding="utf-8").lower()
