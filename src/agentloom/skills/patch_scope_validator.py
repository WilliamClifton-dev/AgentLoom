"""Team-original patch scope validation and its governed ToolProvider."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from fnmatch import fnmatch
from hmac import compare_digest
from pathlib import Path, PurePosixPath
from uuid import uuid4

from pydantic import Field, ValidationError, field_validator

from agentloom.contracts import ContractModel, ToolExecutionRequest, ToolExecutionResult

MAX_PATCH_BYTES = 131_072
MAX_PATH_LENGTH = 1_024
MAX_PATH_PARTS = 128
_HUNK_HEADER = re.compile(
    r"^@@ -(?:\d+)(?:,(\d+))? \+(?:\d+)(?:,(\d+))? @@(?: .*)?$"
)
_UNSUPPORTED_PATCH_PREFIXES = (
    "rename from ",
    "rename to ",
    "copy from ",
    "copy to ",
    "GIT binary patch",
    "Binary files ",
)


@dataclass(frozen=True)
class PatchScopeViolation:
    """One path that is outside the authorized patch scope."""

    file_path: str
    violation_type: str
    reason: str


@dataclass(frozen=True)
class PatchScopeValidationResult:
    """Deterministic result of validating one unified diff."""

    verdict: str
    allowed_paths: list[str]
    actual_modified_paths: list[str]
    violations: list[PatchScopeViolation]
    patch_hash: str


class PatchScopeValidatorParameters(ContractModel):
    """Strict external parameters for the patch scope ToolProvider."""

    patch: str = Field(min_length=1)
    patch_sha256: str = Field(alias="patchSha256", pattern=r"^[a-f0-9]{64}$")
    allowed_paths: list[str] = Field(alias="allowedPaths", min_length=1, max_length=256)

    @field_validator("allowed_paths")
    @classmethod
    def allowed_paths_are_safe(cls, value: list[str]) -> list[str]:
        normalized = [_validate_pattern(pattern) for pattern in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("allowedPaths cannot contain duplicates")
        return normalized


def _validate_pattern(pattern: str) -> str:
    if "\\" in pattern or "\x00" in pattern:
        raise ValueError("allowed patch patterns must use safe POSIX syntax")
    parsed = PurePosixPath(pattern)
    if (
        not pattern
        or len(pattern) > MAX_PATH_LENGTH
        or len(parsed.parts) > MAX_PATH_PARTS
        or parsed.is_absolute()
        or ".." in parsed.parts
        or parsed.as_posix() != pattern
    ):
        raise ValueError(
            "allowed patch patterns must satisfy the length boundary and use "
            "normalized relative paths"
        )
    return pattern


def _normalize_diff_path(raw: str) -> str | None:
    path = raw.split("\t", maxsplit=1)[0]
    if path == "/dev/null":
        return None
    if path.startswith(("a/", "b/")):
        path = path[2:]
    if not path or "\\" in path or "\x00" in path or path.startswith('"'):
        raise ValueError("patch contains an unsupported path")
    parsed = PurePosixPath(path)
    if (
        len(path) > MAX_PATH_LENGTH
        or len(parsed.parts) > MAX_PATH_PARTS
        or parsed.is_absolute()
        or ".." in parsed.parts
        or parsed.as_posix() != path
    ):
        raise ValueError("patch path exceeds the length boundary or is unsafe")
    return path


def parse_unified_diff_paths(patch_content: str) -> set[str]:
    """Extract every old and new path from a bounded unified diff."""

    if not patch_content:
        return set()
    lines = patch_content.splitlines()
    paths: set[str] = set()
    file_count = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith(_UNSUPPORTED_PATCH_PREFIXES):
            raise ValueError("patch contains an unsupported file operation")
        if not line.startswith("--- "):
            if line.startswith("+++ ") or line.startswith((" ", "+", "-", "\\")):
                raise ValueError("patch contains an unpaired file header or hunk line")
            index += 1
            continue

        if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
            raise ValueError("patch file header is not a complete ---/+++ pair")
        old_path = _normalize_diff_path(line[4:])
        new_path = _normalize_diff_path(lines[index + 1][4:])
        if old_path is None and new_path is None:
            raise ValueError("patch file header cannot contain two null paths")
        paths.update(path for path in (old_path, new_path) if path is not None)
        index += 2

        hunk_count = 0
        while index < len(lines) and lines[index].startswith("@@ "):
            match = _HUNK_HEADER.fullmatch(lines[index])
            if match is None:
                raise ValueError("patch contains an invalid hunk header")
            old_remaining = int(match.group(1) or "1")
            new_remaining = int(match.group(2) or "1")
            index += 1
            previous_was_data = False
            while old_remaining or new_remaining:
                if index >= len(lines):
                    raise ValueError("patch hunk is truncated")
                hunk_line = lines[index]
                if hunk_line == "\\ No newline at end of file":
                    if not previous_was_data:
                        raise ValueError("patch contains a misplaced newline marker")
                    previous_was_data = False
                    index += 1
                    continue
                if not hunk_line:
                    raise ValueError("patch contains an invalid empty hunk line")
                prefix = hunk_line[0]
                if prefix == " ":
                    old_remaining -= 1
                    new_remaining -= 1
                elif prefix == "-":
                    old_remaining -= 1
                elif prefix == "+":
                    new_remaining -= 1
                else:
                    raise ValueError("patch contains an invalid hunk line")
                if old_remaining < 0 or new_remaining < 0:
                    raise ValueError("patch hunk exceeds its declared line counts")
                previous_was_data = True
                index += 1
            if (
                index < len(lines)
                and lines[index] == "\\ No newline at end of file"
            ):
                index += 1
            hunk_count += 1
        if hunk_count == 0:
            raise ValueError("patch file header is not followed by a hunk")
        file_count += 1

    if file_count == 0 or not paths:
        raise ValueError("patch does not contain a complete unified diff")
    return paths


def matches_allowed_pattern(file_path: str, allowed_patterns: list[str]) -> bool:
    """Return whether a normalized path matches one authorized pattern."""

    normalized_path = _normalize_diff_path(file_path)
    if normalized_path is None:
        return False
    return any(
        _matches_recursive_pattern(
            normalized_path.split("/"),
            _validate_pattern(pattern).split("/"),
        )
        for pattern in allowed_patterns
    )


def _matches_recursive_pattern(path_parts: list[str], pattern_parts: list[str]) -> bool:
    def expand_double_star(states: set[int]) -> set[int]:
        expanded = set(states)
        pending = list(states)
        while pending:
            index = pending.pop()
            if (
                index < len(pattern_parts)
                and pattern_parts[index] == "**"
                and index + 1 not in expanded
            ):
                expanded.add(index + 1)
                pending.append(index + 1)
        return expanded

    states = expand_double_star({0})
    for path_part in path_parts:
        next_states: set[int] = set()
        for index in states:
            if index >= len(pattern_parts):
                continue
            pattern = pattern_parts[index]
            if pattern == "**":
                next_states.add(index)
            elif fnmatch(path_part, pattern):
                next_states.add(index + 1)
        states = expand_double_star(next_states)
        if not states:
            return False
    return len(pattern_parts) in expand_double_star(states)


def validate_patch_scope(
    patch_content: str,
    allowed_paths: list[str],
    patch_hash: str,
) -> PatchScopeValidationResult:
    """Validate that every old and new diff path is authorized."""

    modified_paths = parse_unified_diff_paths(patch_content)
    violations = [
        PatchScopeViolation(
            file_path=path,
            violation_type="modified",
            reason=f"Path '{path}' does not match any allowed pattern",
        )
        for path in sorted(modified_paths)
        if not matches_allowed_pattern(path, allowed_paths)
    ]
    return PatchScopeValidationResult(
        verdict="PASSED" if not violations else "FAILED",
        allowed_paths=list(allowed_paths),
        actual_modified_paths=sorted(modified_paths),
        violations=violations,
        patch_hash=patch_hash,
    )


def validate_patch_scope_from_file(
    patch_file_path: str,
    allowed_paths: list[str],
) -> PatchScopeValidationResult:
    patch_content = Path(patch_file_path).read_text(encoding="utf-8")
    patch_hash = hashlib.sha256(patch_content.encode("utf-8")).hexdigest()
    return validate_patch_scope(patch_content, allowed_paths, patch_hash)


class PatchScopeValidatorProvider:
    """Validate an inline diff without filesystem or process access."""

    provider_id = "patch-scope-validator/v1.0.1"

    def __init__(self, evidence_root: Path) -> None:
        self._evidence_root = evidence_root.resolve()

    def requested_paths(self, request: ToolExecutionRequest) -> list[str]:
        parameters = PatchScopeValidatorParameters.model_validate(request.parameters)
        self._assert_patch_size(parameters.patch)
        self._assert_patch_hash(parameters)
        return sorted(parse_unified_diff_paths(parameters.patch))

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        return await asyncio.to_thread(self._execute, request)

    def _execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        if (
            request.skill_name != "patch-scope-validator"
            or request.skill_version != "1.0.1"
            or request.tool_name != "patch-scope-validator"
            or request.action != "patch.validate:scope"
        ):
            return self._write_denial(request, "TOOL_ACTION_NOT_SUPPORTED")
        try:
            parameters = PatchScopeValidatorParameters.model_validate(request.parameters)
        except ValidationError:
            return self._write_denial(request, "INVALID_TOOL_PARAMETERS")
        try:
            self._assert_patch_size(parameters.patch)
        except ValueError:
            return self._write_denial(request, "PATCH_TOO_LARGE")
        try:
            self._assert_patch_hash(parameters)
        except ValueError:
            return self._write_denial(request, "PATCH_HASH_MISMATCH")
        try:
            validation = validate_patch_scope(
                parameters.patch,
                parameters.allowed_paths,
                parameters.patch_sha256,
            )
        except ValueError:
            return self._write_denial(request, "INVALID_UNIFIED_DIFF")
        status = "SUCCEEDED" if validation.verdict == "PASSED" else "FAILED"
        error_code = None if status == "SUCCEEDED" else "PATCH_SCOPE_VIOLATION"
        return self._write_result(request, validation, status, error_code)

    @staticmethod
    def _assert_patch_size(patch: str) -> None:
        if len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
            raise ValueError("patch exceeds 128 KiB")

    @staticmethod
    def _assert_patch_hash(parameters: PatchScopeValidatorParameters) -> None:
        actual = hashlib.sha256(parameters.patch.encode("utf-8")).hexdigest()
        if not compare_digest(actual, parameters.patch_sha256):
            raise ValueError("patchSha256 does not match patch")

    def _write_denial(
        self,
        request: ToolExecutionRequest,
        error_code: str,
    ) -> ToolExecutionResult:
        return self._write_result(request, None, "DENIED", error_code)

    def _write_result(
        self,
        request: ToolExecutionRequest,
        validation: PatchScopeValidationResult | None,
        status: str,
        error_code: str | None,
    ) -> ToolExecutionResult:
        evidence_id = f"ev-skill-{uuid4().hex}"
        evidence = {
            "schemaVersion": "agentloom.patch-scope-result/v1alpha1",
            "taskId": request.task_id,
            "stepId": request.step_id,
            "verdict": validation.verdict if validation is not None else "DENIED",
            "patchSha256": validation.patch_hash if validation is not None else None,
            "allowedPaths": validation.allowed_paths if validation is not None else [],
            "actualModifiedPaths": (
                validation.actual_modified_paths if validation is not None else []
            ),
            "violations": (
                [asdict(violation) for violation in validation.violations]
                if validation is not None
                else []
            ),
            "errorCode": error_code,
        }
        encoded = (json.dumps(evidence, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
        self._evidence_root.mkdir(parents=True, exist_ok=True)
        output_path = self._evidence_root / f"{evidence_id}.json"
        with output_path.open("xb") as stream:
            stream.write(encoded)
        return ToolExecutionResult(
            status=status,
            evidence_refs=[evidence_id],
            output_digest=hashlib.sha256(encoded).hexdigest(),
            error_code=error_code,
        )
