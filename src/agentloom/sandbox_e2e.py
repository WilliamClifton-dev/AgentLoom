"""Prepare and verify redacted AgentTeams-to-Docker E2E fixtures."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path
from typing import Literal, cast

from pydantic import Field

from agentloom.contracts import (
    ContractModel,
    GrantIssuanceRequest,
    TaskCreate,
    TaskTransition,
    ToolExecutionRequest,
    tool_parameter_digest,
)
from agentloom.docker_sandbox import workspace_tree_digest
from agentloom.skill_catalog import load_skill_catalog
from agentloom.storage import Database

_SKILL_NAME = "code-review-and-quality"
_TARGET_PATH = "tests/test_pagination.py"
_DOCKER_PROVIDER_ID = "sandboxed-test-runner/docker-sandbox"
_IMAGE_REF = re.compile(
    r"^(?:sha256:[a-f0-9]{64}|[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64})$"
)
_EVIDENCE_REF = re.compile(r"^ev-tool-[A-Za-z0-9._-]+$")
_MAX_EVIDENCE_BYTES = 2 * 1024 * 1024


class SandboxE2ETask(ContractModel):
    task_id: str = Field(alias="taskId", min_length=1)
    issuance_request: GrantIssuanceRequest = Field(alias="issuanceRequest")
    tool_request: ToolExecutionRequest = Field(alias="toolRequest")
    success_marker: str = Field(alias="successMarker", min_length=1)


class SandboxE2EContext(ContractModel):
    schema_version: Literal["agentloom.sandbox-e2e-context/v1alpha1"] = Field(
        default="agentloom.sandbox-e2e-context/v1alpha1",
        alias="schemaVersion",
    )
    workspace_digest: str = Field(
        alias="workspaceDigest",
        pattern=r"^[a-f0-9]{64}$",
    )
    tasks: dict[Literal["direct", "model"], SandboxE2ETask]


class SandboxE2EVerifiedTask(ContractModel):
    task_id: str = Field(alias="taskId", min_length=1)
    provider_id: Literal["sandboxed-test-runner/docker-sandbox"] = Field(
        alias="providerId"
    )
    evidence_ref: str = Field(alias="evidenceRef", pattern=r"^ev-tool-[A-Za-z0-9._-]+$")
    output_digest: str = Field(alias="outputDigest", pattern=r"^[a-f0-9]{64}$")


class SandboxE2EVerificationError(RuntimeError):
    """Raised when runtime records do not prove the production sandbox path."""


def prepare_sandbox_e2e(
    *,
    database_url: str,
    workspace: Path,
    skill_catalog: Path,
) -> SandboxE2EContext:
    resolved_workspace = workspace.resolve()
    digest = workspace_tree_digest(resolved_workspace)
    catalog = load_skill_catalog(skill_catalog.resolve())
    matching = [
        skill
        for skill in catalog.skills
        if skill.name == _SKILL_NAME and skill.lifecycle_state == "PUBLISHED"
    ]
    if len(matching) != 1:
        raise ValueError("sandbox E2E requires one published review Skill")
    skill = matching[0]
    if (
        "agentloom-verifier" not in (skill.compatible_agents or [])
        or "test-runner:process.exec:test" not in (skill.allowed_tools or [])
    ):
        raise ValueError("published review Skill does not authorize the Verifier runner")

    parameters: dict[str, object] = {
        "command": ["pytest", "-q", _TARGET_PATH],
        "workingDirectory": ".",
        "workspaceDigest": digest,
        "timeoutSeconds": 30,
        "outputLimitBytes": 65536,
    }
    parameter_digest = tool_parameter_digest(parameters)
    database = Database(database_url)
    database.create_schema()
    tasks: dict[Literal["direct", "model"], SandboxE2ETask] = {}
    for task_name in ("direct", "model"):
        task = database.create_task(
            TaskCreate(
                title=f"Task 16 {task_name} sandbox verification",
                repository_uri=resolved_workspace.as_uri(),
                issue="Run one governed pytest through the production Docker sandbox.",
                acceptance_criteria=[
                    "The Verifier ToolCall succeeds only through docker-sandbox."
                ],
                allowed_paths=[_TARGET_PATH],
            )
        )
        for status in ("PLANNED", "INVESTIGATING", "IMPLEMENTING", "VERIFYING"):
            updated = database.transition_task(
                task.task_id,
                TaskTransition(
                    expected_plan_version=task.plan_version,
                    status=status,
                    reason=f"Advance Task 16 fixture to {status}.",
                ),
            )
            if updated is None:
                raise RuntimeError("sandbox E2E task disappeared during preparation")
            task = updated
        step_id = f"verify-sandbox-{task_name}"
        issuance = GrantIssuanceRequest(
            task_id=task.task_id,
            step_id=step_id,
            skill_name=skill.name,
            skill_version=skill.version,
            tool_name="test-runner",
            action="process.exec:test",
            parameter_digest=parameter_digest,
            requested_paths=[_TARGET_PATH],
        )
        tool_request = ToolExecutionRequest(
            task_id=task.task_id,
            step_id=step_id,
            agent_name="agentloom-verifier",
            skill_name=skill.name,
            skill_version=skill.version,
            tool_name="test-runner",
            action="process.exec:test",
            parameter_digest=parameter_digest,
            parameters=parameters,
        )
        tasks[task_name] = SandboxE2ETask(
            task_id=task.task_id,
            issuance_request=issuance,
            tool_request=tool_request,
            success_marker=f"[{task.task_id}] SANDBOX_TOOL_PASS",
        )
    return SandboxE2EContext(workspace_digest=digest, tasks=tasks)


def verify_sandbox_e2e(
    *,
    database_url: str,
    evidence_root: Path,
    context: SandboxE2EContext,
    expected_image: str,
    task_names: list[str],
) -> dict[str, SandboxE2EVerifiedTask]:
    if not _IMAGE_REF.fullmatch(expected_image):
        raise ValueError("expected image must be immutable")
    if not task_names:
        raise ValueError("at least one sandbox E2E task must be verified")
    database = Database(database_url)
    verified: dict[str, SandboxE2EVerifiedTask] = {}
    for task_name in task_names:
        if task_name not in {"direct", "model"}:
            raise ValueError(f"unknown sandbox E2E task: {task_name}")
        typed_name = cast(Literal["direct", "model"], task_name)
        task = context.tasks[typed_name]
        events = database.list_tool_calls(task.task_id)
        if len(events) != 1:
            raise SandboxE2EVerificationError(
                f"{task_name} must have exactly one ToolCall"
            )
        event = events[0]
        if event.provider_id != _DOCKER_PROVIDER_ID:
            raise SandboxE2EVerificationError(
                f"{task_name} ToolCall did not use the Docker provider"
            )
        if (
            event.actor != "agentloom-verifier"
            or event.status != "SUCCEEDED"
            or event.error_code is not None
            or event.parameter_digest != task.tool_request.parameter_digest
        ):
            raise SandboxE2EVerificationError(
                f"{task_name} ToolCall identity or result is invalid"
            )
        if len(event.evidence_refs) != 1:
            raise SandboxE2EVerificationError(
                f"{task_name} ToolCall must have one Evidence reference"
            )
        evidence_ref = event.evidence_refs[0]
        if not _EVIDENCE_REF.fullmatch(evidence_ref):
            raise SandboxE2EVerificationError("ToolCall Evidence reference is invalid")
        evidence_path = evidence_root.resolve() / f"{evidence_ref}.txt"
        try:
            if evidence_path.stat().st_size > _MAX_EVIDENCE_BYTES:
                raise SandboxE2EVerificationError("sandbox Evidence exceeds size limit")
            evidence_bytes = evidence_path.read_bytes()
        except OSError as exc:
            raise SandboxE2EVerificationError("sandbox Evidence is unavailable") from exc
        if hashlib.sha256(evidence_bytes).hexdigest() != event.output_digest:
            raise SandboxE2EVerificationError("sandbox Evidence digest does not match ToolCall")
        evidence = evidence_bytes.decode("utf-8")
        required_lines = (
            "STATUS: SUCCEEDED\n",
            "SANDBOX_PROVIDER: docker-sandbox\n",
            f"IMAGE_REF: {expected_image}\n",
            f"SNAPSHOT_DIGEST: {context.workspace_digest}\n",
            "EXIT_CODE: 0\n",
            "1 passed",
        )
        if any(line not in evidence for line in required_lines):
            raise SandboxE2EVerificationError(
                f"{task_name} Evidence does not prove the expected sandbox result"
            )
        verified[task_name] = SandboxE2EVerifiedTask(
            task_id=task.task_id,
            provider_id=_DOCKER_PROVIDER_ID,
            evidence_ref=evidence_ref,
            output_digest=event.output_digest,
        )
    return verified


def _write_json(path: Path, model: ContractModel) -> None:
    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(model.model_dump_json(by_alias=True, indent=2))
        stream.write("\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare or verify Task 16 fixtures")
    subcommands = parser.add_subparsers(dest="command", required=True)
    prepare = subcommands.add_parser("prepare")
    prepare.add_argument("--database-url", required=True)
    prepare.add_argument("--workspace", type=Path, required=True)
    prepare.add_argument("--skill-catalog", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    verify = subcommands.add_parser("verify")
    verify.add_argument("--database-url", required=True)
    verify.add_argument("--evidence-root", type=Path, required=True)
    verify.add_argument("--context", type=Path, required=True)
    verify.add_argument("--expected-image", required=True)
    verify.add_argument("--task", action="append", required=True)
    verify.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    if arguments.command == "prepare":
        context = prepare_sandbox_e2e(
            database_url=arguments.database_url,
            workspace=arguments.workspace,
            skill_catalog=arguments.skill_catalog,
        )
        _write_json(arguments.output, context)
        return
    context = SandboxE2EContext.model_validate_json(arguments.context.read_text("utf-8"))
    verified = verify_sandbox_e2e(
        database_url=arguments.database_url,
        evidence_root=arguments.evidence_root,
        context=context,
        expected_image=arguments.expected_image,
        task_names=arguments.task,
    )
    result = SandboxE2EVerificationResult(tasks=verified)
    _write_json(arguments.output, result)


class SandboxE2EVerificationResult(ContractModel):
    schema_version: Literal["agentloom.sandbox-e2e-verification/v1alpha1"] = Field(
        default="agentloom.sandbox-e2e-verification/v1alpha1",
        alias="schemaVersion",
    )
    tasks: dict[str, SandboxE2EVerifiedTask]


if __name__ == "__main__":
    main()
