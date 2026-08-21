"""Fail-closed verification for model-generated AgentTeams repair submissions."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import ValidationError

from agentloom.contracts import (
    VerificationResult,
)
from agentloom.demo_case import DemoCase, demo_case_fingerprint, load_demo_case
from agentloom.docker_sandbox import workspace_tree_digest
from agentloom.mock_repair import (
    _file_hash,
)

AgentName = Literal[
    "agentloom-investigator",
    "agentloom-implementer",
    "agentloom-verifier",
]
ProviderName = Literal["dashscope", "deepseek", "stepfun", "minimax-cn"]
ModelName = Literal[
    "qwen3.7-plus",
    "deepseek-v4-pro",
    "step-3.7-flash",
    "MiniMax-M2.5",
]

_EXPECTED_AGENTS: tuple[AgentName, ...] = (
    "agentloom-investigator",
    "agentloom-implementer",
    "agentloom-verifier",
)
_PROVIDER_MODELS: dict[ProviderName, ModelName] = {
    "dashscope": "qwen3.7-plus",
    "deepseek": "deepseek-v4-pro",
    "stepfun": "step-3.7-flash",
    "minimax-cn": "MiniMax-M2.5",
}
_HIDDEN_WORKSPACE = ".agentloom-hidden-tests"
_MAX_PATCH_BYTES = 131_072
_MAX_SOURCE_FILES = 64
_MAX_SOURCE_BYTES = 1_048_576




from agentloom.live_repair.models import (  # noqa: E402,F401
    LiveRepairCaseContext,
    LiveRepairError,
    LiveRepairSourceFile,
    LiveRepairSubmission,
)


def prepare_live_repair_case_context(case_root: Path) -> LiveRepairCaseContext:
    """Expose only validated, model-visible inputs for a live repair Case."""

    case = load_demo_case(case_root)
    files = sorted(path for path in case.source_root.rglob("*") if path.is_file())
    if len(files) > _MAX_SOURCE_FILES:
        raise LiveRepairError("live repair Case contains too many source files")
    source_files: list[LiveRepairSourceFile] = []
    total_bytes = 0
    for path in files:
        relative = path.relative_to(case.source_root).as_posix()
        size = path.stat().st_size
        total_bytes += size
        if total_bytes > _MAX_SOURCE_BYTES:
            raise LiveRepairError("live repair Case source exceeds the size limit")
        source_files.append(
            LiveRepairSourceFile(
                source_path=relative,
                object_name=f"base/{relative}",
                sha256=sha256(path.read_bytes()).hexdigest(),
                size_bytes=size,
            )
        )
    test_command = list(case.test_command)
    static_command = list(case.static_check_command)
    static_shell = (
        shlex.join(["python", "-m", *static_command])
        if static_command[0] == "compileall"
        else shlex.join(static_command)
    )
    acceptance = "\n".join(
        f"- {criterion}" for criterion in case.manifest.acceptance_criteria
    )
    allowed_paths = "\n".join(
        f"- {path}" for path in case.manifest.allowed_changed_paths
    )
    targets = "\n".join(
        f"- {target}" for target in case.manifest.target_failing_tests
    )
    spec = (
        f"# AgentLoom live repair Case: {case.manifest.case_id}\n\n"
        f"{case.issue}\n\n"
        f"Acceptance criteria:\n{acceptance}\n\n"
        f"Allowed changed paths:\n{allowed_paths}\n\n"
        f"Target failing tests:\n{targets}\n\n"
        f"Working directory: {case.manifest.working_directory}\n"
        f"Visible command: {shlex.join(test_command)}\n"
        f"Static command: {static_shell}\n"
    )
    return LiveRepairCaseContext(
        case_id=case.manifest.case_id,
        case_fingerprint=demo_case_fingerprint(case),
        title=case.manifest.title,
        issue=case.issue,
        acceptance_criteria=case.manifest.acceptance_criteria,
        source_files=source_files,
        working_directory=case.manifest.working_directory,
        test_command=test_command,
        test_shell_command=shlex.join(test_command),
        static_check_command=static_command,
        static_check_shell_command=static_shell,
        target_failing_tests=case.manifest.target_failing_tests,
        allowed_changed_paths=case.manifest.allowed_changed_paths,
        timeout_seconds=case.manifest.timeout_seconds,
        output_limit_bytes=case.manifest.output_limit_bytes,
        spec=spec,
    )

def _load_submission(path: Path) -> LiveRepairSubmission:
    try:
        return LiveRepairSubmission.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise LiveRepairError(f"invalid live repair submission: {exc}") from exc

def _patch_paths(patch: str) -> list[str]:
    forbidden_markers = (
        "GIT binary patch",
        "Binary files ",
        "rename from ",
        "rename to ",
        "copy from ",
        "copy to ",
    )
    if any(marker in patch for marker in forbidden_markers):
        raise LiveRepairError("binary, rename, and copy patches are not allowed")

    lines = patch.splitlines()
    paths: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("--- "):
            index += 1
            continue
        if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
            raise LiveRepairError("repair.patch contains an incomplete file header")
        before = line[4:]
        after = lines[index + 1][4:]
        if not before.startswith("a/") or not after.startswith("b/"):
            raise LiveRepairError("repair.patch must modify existing a/ and b/ paths")
        before_path = before[2:]
        after_path = after[2:]
        if before_path != after_path:
            raise LiveRepairError("repair.patch must not rename files")
        paths.append(_safe_patch_path(before_path))
        index += 2
    if not paths:
        raise LiveRepairError("repair.patch does not contain a unified diff")
    if len(paths) != len(set(paths)):
        raise LiveRepairError("repair.patch contains duplicate file sections")
    return sorted(paths)

def _safe_patch_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or value.startswith(("/", "\\")):
        raise LiveRepairError("repair.patch contains an absolute path")
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise LiveRepairError("repair.patch contains an unsafe path")
    if "\\" in value or "\x00" in value:
        raise LiveRepairError("repair.patch contains an unsafe path")
    return path.as_posix()

def _apply_patch(workspace: Path, patch_path: Path, case: DemoCase) -> None:
    git_metadata = workspace / ".git"
    if git_metadata.exists() or git_metadata.is_symlink():
        raise LiveRepairError("live repair workspace contains Git metadata")
    try:
        try:
            initialized = subprocess.run(
                ("git", "init", "--quiet"),
                cwd=workspace,
                capture_output=True,
                timeout=case.manifest.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LiveRepairError("git could not isolate the repair workspace") from exc
        output_size = len(initialized.stdout) + len(initialized.stderr)
        if output_size > case.manifest.output_limit_bytes:
            raise LiveRepairError("git init output exceeded the case limit")
        if initialized.returncode != 0:
            raise LiveRepairError("git could not isolate the repair workspace")

        for arguments in (
            ("git", "apply", "--check", "--whitespace=error-all", str(patch_path)),
            ("git", "apply", "--whitespace=error-all", str(patch_path)),
        ):
            try:
                result = subprocess.run(
                    arguments,
                    cwd=workspace,
                    capture_output=True,
                    timeout=case.manifest.timeout_seconds,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise LiveRepairError(
                    "git apply could not verify the submitted patch"
                ) from exc
            output_size = len(result.stdout) + len(result.stderr)
            if output_size > case.manifest.output_limit_bytes:
                raise LiveRepairError("git apply output exceeded the case limit")
            if result.returncode != 0:
                raise LiveRepairError("git apply rejected the submitted patch")
    finally:
        if git_metadata.exists() or git_metadata.is_symlink():
            try:
                shutil.rmtree(git_metadata)
            except OSError as exc:
                raise LiveRepairError(
                    "temporary Git metadata could not be removed"
                ) from exc

def _write_evidence(
    *,
    path: Path,
    submission: LiveRepairSubmission,
    case: DemoCase,
    submission_path: Path,
    test_results_path: Path,
    verified_workspace: Path,
    host_verification: VerificationResult,
) -> None:
    evidence = {
        "schemaVersion": "agentloom.live-repair-evidence/v1alpha1",
        "status": "PASS",
        "taskId": submission.task_id,
        "caseId": case.manifest.case_id,
        "caseFingerprint": demo_case_fingerprint(case),
        "caseSnapshotSha256": case.provenance.snapshot_sha256,
        "provider": submission.provider,
        "model": submission.model,
        "submissionSha256": _file_hash(submission_path),
        "patchSha256": submission.bundle.patch.sha256,
        "testResultsSha256": _file_hash(test_results_path),
        "verifiedWorkspaceDigest": workspace_tree_digest(verified_workspace),
        "agentVerificationVerdict": submission.bundle.verification.verdict,
        "hostVerificationVerdict": host_verification.verdict,
        "roleEvents": [
            event.model_dump(mode="json", by_alias=True)
            for event in submission.role_events
        ],
        "coordinationTrace": submission.coordination_trace.model_dump(
            mode="json", by_alias=True
        ),
        "independentVerification": {
            "originalFailureReproduced": True,
            "targetTestsPassed": True,
            "regressionTestsPassed": True,
            "hiddenTestsPassed": True,
            "staticChecksPassed": True,
            "unauthorizedChanges": False,
        },
    }
    path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

def _write_case_context(path: Path, context: LiveRepairCaseContext) -> None:
    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(context.model_dump_json(by_alias=True, indent=2))
        stream.write("\n")
