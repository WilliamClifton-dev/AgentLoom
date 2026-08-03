"""Fail-closed handoff between AgentTeams global and team task namespaces."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal, Protocol

BridgeAction = Literal["STAGE", "COLLECT"]

ALLOWED_RESULT_FILES = (
    "result.md",
    "root-cause-report.json",
    "patch-artifact.json",
    "verification-result.json",
    "risk-report.json",
    "test-results.txt",
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
