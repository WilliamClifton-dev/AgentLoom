"""Strict, local-only contract for reproducible repair demo cases."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, field_validator

from agentloom.contracts import ContractModel

_SHELL_META = re.compile(r"[;&|><`$()\r\n]")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[/\\]")
_SHA256_PREFIX = "sha256:"
_KNOWN_LICENSES = {
    "AGPL-3.0-only",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "GPL-2.0-only",
    "GPL-3.0-only",
    "ISC",
    "LGPL-3.0-only",
    "MIT",
    "MPL-2.0",
    "Unlicense",
}


class DemoCaseError(RuntimeError):
    """Raised when a demo case cannot be trusted or loaded safely."""


class DemoRuntime(ContractModel):
    language: Literal["python"]
    version: Literal[">=3.12,<3.13"]


class DemoProvenance(ContractModel):
    schema_version: Literal["agentloom.demo-provenance/v1alpha1"] = Field(
        alias="schemaVersion"
    )
    repository_url: str = Field(
        alias="repositoryUrl",
        pattern=r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?$",
    )
    frozen_commit: str = Field(
        alias="frozenCommit", pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$"
    )
    issue_url: str = Field(
        alias="issueUrl", pattern=r"^https://github\.com/[^\s]+$"
    )
    license: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9.+-]*$")
    snapshot_sha256: str = Field(
        alias="snapshotSha256", pattern=r"^sha256:[a-f0-9]{64}$"
    )

    @field_validator("license")
    @classmethod
    def license_is_recognized(cls, value: str) -> str:
        if value not in _KNOWN_LICENSES:
            raise ValueError("license must be a recognized SPDX identifier")
        return value


SafePath = Annotated[str, Field(min_length=1, max_length=300)]


class DemoCaseManifest(ContractModel):
    schema_version: Literal["agentloom.demo-case/v1alpha1"] = Field(
        alias="schemaVersion"
    )
    case_id: str = Field(alias="caseId", pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    title: str = Field(min_length=1, max_length=200)
    issue_path: SafePath = Field(alias="issuePath")
    acceptance_criteria: list[str] = Field(
        alias="acceptanceCriteria", min_length=1
    )
    provenance_path: SafePath = Field(alias="provenancePath")
    source_root: SafePath = Field(alias="sourceRoot")
    expected_patch_root: SafePath = Field(alias="expectedPatchRoot")
    hidden_tests_path: SafePath = Field(alias="hiddenTestsPath")
    working_directory: SafePath = Field(alias="workingDirectory")
    test_command: list[str] = Field(alias="testCommand", min_length=1)
    static_check_command: list[str] = Field(
        alias="staticCheckCommand", min_length=1
    )
    target_failing_tests: list[str] = Field(
        alias="targetFailingTests", min_length=1
    )
    allowed_changed_paths: list[SafePath] = Field(
        alias="allowedChangedPaths", min_length=1
    )
    timeout_seconds: int = Field(alias="timeoutSeconds", ge=1, le=120)
    output_limit_bytes: int = Field(
        alias="outputLimitBytes", ge=1024, le=1_048_576
    )
    runtime: DemoRuntime
    expected_root_cause: str = Field(alias="expectedRootCause", min_length=1)

    @field_validator(
        "issue_path",
        "provenance_path",
        "source_root",
        "expected_patch_root",
        "hidden_tests_path",
    )
    @classmethod
    def paths_are_safe(cls, value: str) -> str:
        return _validate_relative_path(value)

    @field_validator("working_directory")
    @classmethod
    def working_directory_is_safe(cls, value: str) -> str:
        if value == ".":
            return value
        return _validate_relative_path(value)

    @field_validator("allowed_changed_paths")
    @classmethod
    def changed_paths_are_safe(cls, values: list[str]) -> list[str]:
        normalized = [_validate_relative_path(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("allowedChangedPaths contains duplicates")
        return normalized

    @field_validator("target_failing_tests")
    @classmethod
    def target_ids_are_safe(cls, values: list[str]) -> list[str]:
        for value in values:
            _validate_argument(value)
            if "::" not in value:
                raise ValueError("targetFailingTests entries must be pytest node IDs")
        return values

    @field_validator("test_command")
    @classmethod
    def test_command_is_safe(cls, value: list[str]) -> list[str]:
        return _validate_command(value, module="pytest")

    @field_validator("static_check_command")
    @classmethod
    def static_command_is_safe(cls, value: list[str]) -> list[str]:
        return _validate_command(value, module="compileall")


@dataclass(frozen=True)
class DemoCase:
    root: Path
    manifest: DemoCaseManifest
    provenance: DemoProvenance
    issue: str
    source_root: Path
    expected_patch_root: Path
    hidden_tests_root: Path
    working_directory: Path
    test_command: tuple[str, ...]
    static_check_command: tuple[str, ...]


def load_demo_case(case_root: Path) -> DemoCase:
    """Load a local case, validate every path, and verify its frozen snapshot."""
    root = case_root.resolve()
    manifest_path = root / "case.json"
    if not manifest_path.is_file():
        raise DemoCaseError(f"case manifest is missing: {manifest_path}")
    manifest = DemoCaseManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )

    source_root = _resolve_inside(root, manifest.source_root, kind="sourceRoot")
    expected_root = _resolve_inside(
        root, manifest.expected_patch_root, kind="expectedPatchRoot"
    )
    hidden_root = _resolve_inside(
        root, manifest.hidden_tests_path, kind="hiddenTestsPath"
    )
    for label, path in (
        ("sourceRoot", source_root),
        ("expectedPatchRoot", expected_root),
        ("hiddenTestsPath", hidden_root),
    ):
        if not path.is_dir():
            raise DemoCaseError(f"{label} is not a directory: {path}")
        _assert_no_symlinks(path)

    provenance_path = _resolve_inside(
        root, manifest.provenance_path, kind="provenancePath"
    )
    issue_path = _resolve_inside(root, manifest.issue_path, kind="issuePath")
    if not provenance_path.is_file():
        raise DemoCaseError(f"provenance file is missing: {provenance_path}")
    if not issue_path.is_file():
        raise DemoCaseError(f"issue file is missing: {issue_path}")
    provenance = DemoProvenance.model_validate_json(
        provenance_path.read_text(encoding="utf-8")
    )
    issue = issue_path.read_text(encoding="utf-8").strip()
    if not issue:
        raise DemoCaseError("issue file must not be empty")

    working_directory = _resolve_inside(
        source_root, manifest.working_directory, kind="workingDirectory"
    )
    if not working_directory.is_dir():
        raise DemoCaseError(
            f"workingDirectory is not a directory: {working_directory}"
        )

    hidden_relative = hidden_root.relative_to(root)
    if (source_root / hidden_relative).exists():
        raise DemoCaseError("hidden tests are exposed inside sourceRoot")

    actual_hash = snapshot_sha256(source_root)
    expected_hash = provenance.snapshot_sha256.removeprefix(_SHA256_PREFIX)
    if actual_hash != expected_hash:
        raise DemoCaseError(
            f"snapshot hash mismatch: expected {expected_hash}, got {actual_hash}"
        )

    return DemoCase(
        root=root,
        manifest=manifest,
        provenance=provenance,
        issue=issue,
        source_root=source_root,
        expected_patch_root=expected_root,
        hidden_tests_root=hidden_root,
        working_directory=working_directory,
        test_command=tuple(manifest.test_command),
        static_check_command=tuple(manifest.static_check_command),
    )


def snapshot_sha256(root: Path) -> str:
    """Hash stable POSIX paths and platform-independent file content."""
    if not root.is_dir():
        raise DemoCaseError(f"snapshot root is not a directory: {root}")
    digest = sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    for path in files:
        if path.is_symlink():
            raise DemoCaseError(f"snapshot contains a symbolic link: {path}")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = _canonical_snapshot_content(path.read_bytes())
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _canonical_snapshot_content(content: bytes) -> bytes:
    """Normalize Git-style text line endings while preserving binary bytes."""
    if b"\x00" in content:
        return content
    try:
        content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return content
    return content.replace(b"\r\n", b"\n")


def resolve_command(command: tuple[str, ...]) -> list[str]:
    """Map a validated logical command to the current Python interpreter."""
    if command[0] == "python":
        return [sys.executable, *command[1:]]
    return [sys.executable, "-m", *command]


def validate_pytest_command(command: list[str]) -> tuple[str, ...]:
    """Validate one pytest argument vector without accepting a shell command."""

    return tuple(_validate_command(command, module="pytest"))


def _validate_command(value: list[str], *, module: str) -> list[str]:
    if not value:
        raise ValueError("command must not be empty")
    for argument in value:
        _validate_argument(argument)
    if value[0] == module:
        arguments = value[1:]
    elif len(value) >= 3 and value[:3] == ["python", "-m", module]:
        arguments = value[3:]
    else:
        raise ValueError(f"command must invoke the allowed Python module: {module}")
    allowed_flags = (
        {"-q", "-s", "--disable-warnings"}
        if module == "pytest"
        else {"-q", "-f"}
    )
    for argument in arguments:
        if argument in allowed_flags:
            continue
        if module == "pytest" and re.fullmatch(r"--maxfail=[1-9][0-9]*", argument):
            continue
        if argument.startswith("-"):
            raise ValueError(f"unsupported {module} option: {argument}")
        _validate_relative_test_argument(argument, module=module)
    return value


def _validate_argument(value: str) -> None:
    if not value or "\x00" in value or _SHELL_META.search(value):
        raise ValueError("command contains an unsafe argument")
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or _WINDOWS_ABSOLUTE.match(value):
        raise ValueError("absolute command paths are forbidden")
    if ".." in PurePosixPath(normalized).parts:
        raise ValueError("command path traversal is forbidden")


def _validate_relative_test_argument(value: str, *, module: str) -> None:
    path_text = value.split("::", maxsplit=1)[0]
    if module == "pytest" and "::" not in value and not path_text.endswith(".py"):
        if "/" not in path_text and not path_text.startswith("."):
            raise ValueError("pytest targets must be relative test paths")
    _validate_relative_path(path_text)


def _validate_relative_path(value: str) -> str:
    if "\\" in value or "\x00" in value:
        raise ValueError("paths must use safe POSIX syntax")
    path = PurePosixPath(value)
    if path.is_absolute() or value in {"", "."} or ".." in path.parts:
        raise ValueError("path must be a normalized relative path")
    if path.as_posix() != value:
        raise ValueError("path must be normalized")
    return value


def _resolve_inside(root: Path, relative: str, *, kind: str) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise DemoCaseError(f"{kind} escapes the case boundary")
    return candidate


def _assert_no_symlinks(root: Path) -> None:
    for path in (root, *root.rglob("*")):
        if path.is_symlink():
            raise DemoCaseError(f"case contains a symbolic link: {path}")
