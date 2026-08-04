"""Fail-closed handoff between AgentTeams global and team task namespaces."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal, Protocol

BridgeAction = Literal["STAGE", "COLLECT"]

ALLOWED_RESULT_FILES = (
    "result.md",
    "root-cause-report.json",
    "repair.patch",
    "patch-artifact.json",
    "verification-result.json",
    "risk-report.json",
    "test-results.txt",
    "evidence.json",
)

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class NamespaceBridgeError(RuntimeError):
    """Raised when a namespace handoff cannot be verified safely."""


class NamespaceStorage(Protocol):
    """Minimal object-storage operations required by the bridge."""

    def exists(self, path: str) -> bool: ...

    def read(self, path: str) -> bytes: ...

    def copy(self, source: str, target: str) -> None: ...

    def mirror(self, source_prefix: str, target_prefix: str) -> None: ...


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[bytes]]
PipeCommandRunner = Callable[[list[str], bytes], subprocess.CompletedProcess[bytes]]


class DockerMcStorage:
    """MinIO adapter that executes only fixed `mc` commands in the controller."""

    def __init__(
        self,
        controller_container: str,
        *,
        runner: CommandRunner | None = None,
        pipe_runner: PipeCommandRunner | None = None,
    ) -> None:
        self._controller_container = _validated_identifier(
            controller_container,
            "controller_container",
        )
        self._runner = runner or _run_command
        self._pipe_runner = pipe_runner or _run_pipe_command

    def exists(self, path: str) -> bool:
        result = self._invoke("stat", path)
        return result.returncode == 0

    def read(self, path: str) -> bytes:
        return self._checked("cat", path).stdout

    def copy(self, source: str, target: str) -> None:
        self._checked("cp", source, target)

    def write(self, path: str, content: bytes) -> None:
        command = [
            "docker",
            "exec",
            "-i",
            self._controller_container,
            "mc",
            "pipe",
            path,
        ]
        result = self._pipe_runner(command, content)
        if result.returncode != 0:
            raise NamespaceBridgeError(
                f"mc pipe failed in {self._controller_container}"
            )

    def mirror(self, source_prefix: str, target_prefix: str) -> None:
        self._checked("mirror", source_prefix, target_prefix, "--overwrite")

    def _invoke(self, *arguments: str) -> subprocess.CompletedProcess[bytes]:
        return self._runner(
            [
                "docker",
                "exec",
                self._controller_container,
                "mc",
                *arguments,
            ]
        )

    def _checked(
        self,
        operation: str,
        *arguments: str,
    ) -> subprocess.CompletedProcess[bytes]:
        result = self._invoke(operation, *arguments)
        if result.returncode != 0:
            raise NamespaceBridgeError(
                f"mc {operation} failed in {self._controller_container}"
            )
        return result


@dataclass(frozen=True)
class NamespaceLayout:
    """Validated storage locations for one delegated parent task."""

    storage_prefix: str
    team_name: str
    task_id: str
    global_task_prefix: str
    team_task_prefix: str

    @classmethod
    def build(
        cls,
        *,
        storage_prefix: str,
        team_name: str,
        task_id: str,
    ) -> NamespaceLayout:
        safe_team = _validated_identifier(team_name, "team_name")
        safe_task = _validated_identifier(task_id, "task_id")
        safe_prefix = _validated_storage_prefix(storage_prefix)
        return cls(
            storage_prefix=safe_prefix,
            team_name=safe_team,
            task_id=safe_task,
            global_task_prefix=f"{safe_prefix}/shared/tasks/{safe_task}/",
            team_task_prefix=(
                f"{safe_prefix}/teams/{safe_team}/shared/tasks/{safe_task}/"
            ),
        )


@dataclass(frozen=True)
class NamespaceBridgeEvidence:
    """Secret-free evidence emitted after a verified handoff."""

    action: BridgeAction
    task_id: str
    team_name: str
    spec_sha256: str
    copied_files: tuple[str, ...]
    file_sha256: dict[str, str]
    verified_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "taskId": self.task_id,
            "teamName": self.team_name,
            "specSha256": self.spec_sha256,
            "copiedFiles": list(self.copied_files),
            "fileSha256": self.file_sha256,
            "verifiedAt": self.verified_at,
        }


class NamespaceBridge:
    """Copy parent tasks across AgentTeams namespaces without widening access."""

    def __init__(self, storage: NamespaceStorage) -> None:
        self._storage = storage

    def stage(self, layout: NamespaceLayout) -> NamespaceBridgeEvidence:
        """Copy a Manager-owned parent task into the Team namespace."""
        global_spec = f"{layout.global_task_prefix}spec.md"
        team_spec = f"{layout.team_task_prefix}spec.md"
        spec_content = self._read_required(global_spec)
        expected_hash = _digest(spec_content)

        if self._storage.exists(team_spec):
            self._require_matching_hash(team_spec, expected_hash, "spec")

        self._storage.mirror(layout.global_task_prefix, layout.team_task_prefix)
        self._require_matching_hash(team_spec, expected_hash, "spec")
        return self._evidence(
            action="STAGE",
            layout=layout,
            spec_sha256=expected_hash,
            copied_files=(),
            file_sha256={},
        )

    def collect(self, layout: NamespaceLayout) -> NamespaceBridgeEvidence:
        """Copy only approved result artifacts back into the global namespace."""
        global_spec = f"{layout.global_task_prefix}spec.md"
        team_spec = f"{layout.team_task_prefix}spec.md"
        expected_hash = _digest(self._read_required(global_spec))
        self._require_matching_hash(team_spec, expected_hash, "spec")

        team_result = f"{layout.team_task_prefix}result.md"
        if not self._storage.exists(team_result):
            raise NamespaceBridgeError(f"missing required result.md: {team_result}")

        copied_files: list[str] = []
        file_sha256: dict[str, str] = {}
        for name in ALLOWED_RESULT_FILES:
            source = f"{layout.team_task_prefix}{name}"
            if not self._storage.exists(source):
                continue
            target = f"{layout.global_task_prefix}{name}"
            content_hash = _digest(self._storage.read(source))
            self._storage.copy(source, target)
            self._require_matching_hash(target, content_hash, name)
            copied_files.append(name)
            file_sha256[name] = content_hash

        return self._evidence(
            action="COLLECT",
            layout=layout,
            spec_sha256=expected_hash,
            copied_files=tuple(copied_files),
            file_sha256=file_sha256,
        )

    def _read_required(self, path: str) -> bytes:
        if not self._storage.exists(path):
            raise NamespaceBridgeError(f"missing required object: {path}")
        return self._storage.read(path)

    def _require_matching_hash(
        self,
        path: str,
        expected_hash: str,
        label: str,
    ) -> None:
        if not self._storage.exists(path):
            raise NamespaceBridgeError(f"missing copied {label}: {path}")
        actual_hash = _digest(self._storage.read(path))
        if actual_hash != expected_hash:
            raise NamespaceBridgeError(
                f"{label} hash mismatch at {path}: "
                f"expected {expected_hash}, got {actual_hash}"
            )

    @staticmethod
    def _evidence(
        *,
        action: BridgeAction,
        layout: NamespaceLayout,
        spec_sha256: str,
        copied_files: tuple[str, ...],
        file_sha256: dict[str, str],
    ) -> NamespaceBridgeEvidence:
        return NamespaceBridgeEvidence(
            action=action,
            task_id=layout.task_id,
            team_name=layout.team_name,
            spec_sha256=spec_sha256,
            copied_files=copied_files,
            file_sha256=file_sha256,
            verified_at=datetime.now(UTC).isoformat(),
        )


def _validated_identifier(value: str, field: str) -> str:
    normalized = value.strip()
    if not _SAFE_IDENTIFIER.fullmatch(normalized):
        raise ValueError(f"{field} must be a safe identifier")
    return normalized


def _validated_storage_prefix(value: str) -> str:
    normalized = value.strip().strip("/")
    parts = normalized.split("/")
    if len(parts) < 2 or any(not _SAFE_IDENTIFIER.fullmatch(part) for part in parts):
        raise ValueError("storage_prefix must contain safe identifier segments")
    return normalized


def _digest(content: bytes) -> str:
    return sha256(content).hexdigest()


def discover_storage_prefix(
    controller_container: str,
    *,
    runner: CommandRunner | None = None,
) -> str:
    """Read only the non-secret storage prefix from the controller."""
    safe_container = _validated_identifier(
        controller_container,
        "controller_container",
    )
    execute = runner or _run_command
    result = execute(
        [
            "docker",
            "exec",
            safe_container,
            "printenv",
            "HICLAW_STORAGE_PREFIX",
        ]
    )
    if result.returncode != 0:
        raise NamespaceBridgeError(
            f"cannot discover storage prefix from {safe_container}"
        )
    prefix = result.stdout.decode("utf-8", errors="strict").strip()
    return _validated_storage_prefix(prefix)


def write_evidence(evidence: NamespaceBridgeEvidence, path: Path) -> None:
    """Atomically write secret-free bridge evidence."""
    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(evidence.to_dict(), indent=2, sort_keys=True) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary_path = Path(temporary.name)
        temporary_path.replace(destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bridge one AgentTeams parent task across storage namespaces."
    )
    parser.add_argument("action", choices=("stage", "collect"))
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--team-name", default="agentloom-repair")
    parser.add_argument("--controller", default="hiclaw-controller")
    parser.add_argument("--storage-prefix")
    parser.add_argument("--evidence-path", type=Path)
    arguments = parser.parse_args(argv)

    try:
        storage_prefix = arguments.storage_prefix or discover_storage_prefix(
            arguments.controller
        )
        layout = NamespaceLayout.build(
            storage_prefix=storage_prefix,
            team_name=arguments.team_name,
            task_id=arguments.task_id,
        )
        bridge = NamespaceBridge(DockerMcStorage(arguments.controller))
        evidence = (
            bridge.stage(layout)
            if arguments.action == "stage"
            else bridge.collect(layout)
        )
        if arguments.evidence_path is not None:
            write_evidence(evidence, arguments.evidence_path)
        print(json.dumps(evidence.to_dict(), indent=2, sort_keys=True))
        return 0
    except (NamespaceBridgeError, ValueError, UnicodeError) as exc:
        print(f"namespace bridge failed: {exc}", file=sys.stderr)
        return 1


def _run_command(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, check=False, capture_output=True)


def _run_pipe_command(
    command: list[str],
    content: bytes,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        input=content,
        check=False,
        capture_output=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
