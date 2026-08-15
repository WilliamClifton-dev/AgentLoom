"""Generate three model-free governed patch-scope Skill invocation closures."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

from pydantic import Field, ValidationError

from agentloom.contracts import (
    AgentIdentity,
    ContractModel,
    SkillExecutionGrant,
    SkillInvocationEvidenceRecord,
    ToolCallEventRecord,
    ToolExecutionRequest,
    tool_parameter_digest,
)
from agentloom.policy import InMemoryNonceStore, SkillGrantAuthorizer
from agentloom.policy_mcp import TOOL_EXECUTE_TOOL, create_policy_broker_mcp
from agentloom.skill_catalog import load_skill_catalog
from agentloom.skill_invocations import ImmutableSkillInvocationWriter
from agentloom.skills.patch_scope_validator import PatchScopeValidatorProvider

_CASES = (
    ("severity-normalization", "src/severity.py"),
    ("pagination-boundary", "lib/pagination.py"),
    ("retry-delay-cap", "src/retry_policy.py"),
)
_MAX_EVIDENCE_BYTES = 1_048_576


class SkillEvidenceError(RuntimeError):
    """Raised when persisted Skill invocation evidence is not self-consistent."""


class SkillInvocationBundleItem(ContractModel):
    task_id: str = Field(alias="taskId", min_length=1)
    invocation_id: str = Field(alias="invocationId", min_length=1)
    tool_call_path: str = Field(
        alias="toolCallPath",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}\.json$",
    )
    tool_call_sha256: str = Field(
        alias="toolCallSha256",
        pattern=r"^[a-f0-9]{64}$",
    )
    invocation_path: str = Field(
        alias="invocationPath",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}\.json$",
    )
    invocation_sha256: str = Field(
        alias="invocationSha256",
        pattern=r"^[a-f0-9]{64}$",
    )
    provider_evidence_path: str = Field(
        alias="providerEvidencePath",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}\.json$",
    )
    provider_evidence_sha256: str = Field(
        alias="providerEvidenceSha256",
        pattern=r"^[a-f0-9]{64}$",
    )


class SkillInvocationBundle(ContractModel):
    schema_version: Literal["agentloom.skill-invocation-bundle/v1alpha1"] = Field(
        alias="schemaVersion"
    )
    status: Literal["PASSED"]
    skill_name: Literal["patch-scope-validator"] = Field(alias="skillName")
    skill_version: str = Field(alias="skillVersion", min_length=1)
    skill_content_hash: str = Field(
        alias="skillContentHash",
        pattern=r"^sha256:[a-f0-9]{64}$",
    )
    invocations: list[SkillInvocationBundleItem] = Field(
        min_length=3,
        max_length=32,
    )


class PatchScopeViolationEvidence(ContractModel):
    file_path: str = Field(min_length=1)
    violation_type: Literal["modified"]
    reason: str = Field(min_length=1)


class PatchScopeProviderEvidence(ContractModel):
    schema_version: Literal["agentloom.patch-scope-result/v1alpha1"] = Field(
        alias="schemaVersion"
    )
    task_id: str = Field(alias="taskId", min_length=1)
    step_id: str = Field(alias="stepId", min_length=1)
    verdict: Literal["PASSED", "FAILED", "DENIED"]
    patch_sha256: str | None = Field(
        alias="patchSha256",
        pattern=r"^[a-f0-9]{64}$",
    )
    allowed_paths: list[str] = Field(alias="allowedPaths")
    actual_modified_paths: list[str] = Field(alias="actualModifiedPaths")
    violations: list[PatchScopeViolationEvidence]
    error_code: str | None = Field(default=None, alias="errorCode")


def _canonical_patch(path: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new"
    )


def _write_record(path: Path, record: ToolCallEventRecord) -> ToolCallEventRecord:
    encoded = (record.model_dump_json(by_alias=True, indent=2) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(encoded)
    return record


async def generate_patch_scope_evidence(
    output_root: Path,
    catalog_path: Path,
) -> dict[str, object]:
    """Execute and persist exactly three governed patch-scope invocations."""

    output_root.mkdir(parents=True, exist_ok=False)
    catalog = load_skill_catalog(catalog_path)
    manifest = next(
        skill for skill in catalog.skills if skill.name == "patch-scope-validator"
    )
    if manifest.lifecycle_state != "PUBLISHED" or manifest.source is None:
        raise ValueError("patch-scope-validator must be a sourced PUBLISHED Skill")

    agent = AgentIdentity(
        name="agentloom-verifier",
        role="independent patch scope verification",
        capabilities=["patch.read"],
        inputs=["PatchArtifact", "allowed paths"],
        outputs=["PatchScopeValidationResult"],
        dependencies=["patch-scope-validator"],
        decision_boundary=["cannot modify the patch"],
        trace=["Skill invocation closure"],
    )
    authorizer = SkillGrantAuthorizer(secrets.token_bytes(32), InMemoryNonceStore())
    provider = PatchScopeValidatorProvider(output_root)
    invocation_writer = ImmutableSkillInvocationWriter(output_root)
    tool_calls: list[ToolCallEventRecord] = []

    def record_tool_call(event: ToolCallEventRecord) -> ToolCallEventRecord:
        if not event.has_valid_payload_digest():
            raise ValueError("ToolCall payload digest is invalid")
        tool_calls.append(event)
        return _write_record(output_root / f"{event.event_id}.json", event)

    server = create_policy_broker_mcp(
        authorizer,
        tool_provider=provider,
        tool_call_recorder=record_tool_call,
        skill_invocation_recorder=invocation_writer,
    )

    for index, (case_id, changed_path) in enumerate(_CASES, start=1):
        patch = _canonical_patch(changed_path)
        parameters: dict[str, object] = {
            "patch": patch,
            "patchSha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
            "allowedPaths": [changed_path],
        }
        request = ToolExecutionRequest(
            task_id=f"task-skill-{case_id}",
            step_id=f"scope-{index:02d}",
            agent_name=agent.name,
            skill_name=manifest.name,
            skill_version=manifest.version,
            tool_name="patch-scope-validator",
            action="patch.validate:scope",
            parameter_digest=tool_parameter_digest(parameters),
            parameters=parameters,
        )
        now = datetime.now(UTC)
        grant = SkillExecutionGrant(
            grant_id=f"grant-scope-{uuid4().hex}",
            task_id=request.task_id,
            step_id=request.step_id,
            agent_name=request.agent_name,
            skill_name=request.skill_name,
            skill_version=request.skill_version,
            skill_content_hash=manifest.source.content_hash,
            tool_name=request.tool_name,
            action=request.action,
            parameter_digest=request.parameter_digest,
            authorized_paths=[changed_path],
            risk_level="L0",
            nonce=secrets.token_hex(16),
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        signed = authorizer.issue(
            grant,
            manifest=manifest,
            agent=agent,
            requested_paths=[changed_path],
            task_allowed_paths=[changed_path],
        )
        raw_result = await server.call_tool(
            TOOL_EXECUTE_TOOL,
            {
                "request": {
                    "signedGrant": signed.model_dump(mode="json", by_alias=True),
                    "toolRequest": request.model_dump(mode="json", by_alias=True),
                }
            },
        )
        _, result = cast(tuple[object, dict[str, object]], raw_result)
        if result.get("status") != "SUCCEEDED":
            raise RuntimeError(f"patch-scope invocation failed for {case_id}")

    if len(tool_calls) != len(_CASES):
        raise RuntimeError("Policy Broker did not record exactly three ToolCalls")

    invocations: list[dict[str, str]] = []
    invocation_paths = sorted(output_root.glob("skill-invocation-*.json"))
    if len(invocation_paths) != len(_CASES):
        raise RuntimeError("Policy Broker did not record exactly three Skill invocations")
    invocation_by_event: dict[str, tuple[Path, SkillInvocationEvidenceRecord]] = {}
    for path in invocation_paths:
        record = SkillInvocationEvidenceRecord.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if not record.has_valid_payload_digest():
            raise RuntimeError("Skill invocation payload digest is invalid")
        invocation_by_event[record.tool_call_event_id] = (path, record)

    for tool_call in tool_calls:
        tool_path = output_root / f"{tool_call.event_id}.json"
        invocation_path, invocation = invocation_by_event[tool_call.event_id]
        provider_path = output_root / f"{invocation.evidence_ref}.json"
        provider_digest = hashlib.sha256(provider_path.read_bytes()).hexdigest()
        if provider_digest != invocation.evidence_sha256:
            raise RuntimeError("Provider Evidence digest does not match invocation")
        invocations.append(
            {
                "taskId": invocation.task_id,
                "invocationId": invocation.invocation_id,
                "toolCallPath": tool_path.name,
                "toolCallSha256": hashlib.sha256(tool_path.read_bytes()).hexdigest(),
                "invocationPath": invocation_path.name,
                "invocationSha256": hashlib.sha256(
                    invocation_path.read_bytes()
                ).hexdigest(),
                "providerEvidencePath": provider_path.name,
                "providerEvidenceSha256": provider_digest,
            }
        )

    summary: dict[str, object] = {
        "schemaVersion": "agentloom.skill-invocation-bundle/v1alpha1",
        "status": "PASSED",
        "skillName": manifest.name,
        "skillVersion": manifest.version,
        "skillContentHash": manifest.source.content_hash,
        "invocations": invocations,
    }
    bundle_path = output_root / "skill-invocation-bundle.json"
    encoded = (json.dumps(summary, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    with bundle_path.open("xb") as stream:
        stream.write(encoded)
    return summary


def _read_evidence_bytes(path: Path, artifact_name: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise SkillEvidenceError(f"{artifact_name} must be a regular file")
    try:
        size = path.stat().st_size
        if size < 1 or size > _MAX_EVIDENCE_BYTES:
            raise SkillEvidenceError(f"{artifact_name} exceeds its size boundary")
        encoded = path.read_bytes()
    except OSError as exc:
        raise SkillEvidenceError(f"{artifact_name} could not be read") from exc
    if len(encoded) != size:
        raise SkillEvidenceError(f"{artifact_name} changed while being read")
    return encoded


def _bundle_member(root: Path, name: str) -> Path:
    candidate = root / name
    if candidate.parent != root or candidate.is_symlink():
        raise SkillEvidenceError("Skill evidence member path is unsafe")
    return candidate


def _sha256_bytes(encoded: bytes) -> str:
    return hashlib.sha256(encoded).hexdigest()


def _verify_workspace_skill_source(catalog_path: Path, source_path: str) -> str:
    catalog_root = catalog_path.resolve().parent.parent
    unresolved = catalog_root / source_path
    if unresolved.is_symlink():
        raise SkillEvidenceError("Skill source snapshot must not be a symlink")
    resolved = unresolved.resolve()
    try:
        resolved.relative_to(catalog_root)
    except ValueError as exc:
        raise SkillEvidenceError("Skill source snapshot escapes the repository") from exc
    encoded = _read_evidence_bytes(resolved, "Skill source snapshot")
    return f"sha256:{_sha256_bytes(encoded)}"


def verify_patch_scope_evidence_bundle(
    bundle_path: Path,
    catalog_path: Path,
) -> dict[str, object]:
    """Strictly reopen and cross-bind one persisted patch-scope evidence bundle."""

    resolved_bundle = bundle_path.absolute()
    encoded_bundle = _read_evidence_bytes(resolved_bundle, "Skill evidence bundle")
    try:
        bundle = SkillInvocationBundle.model_validate_json(encoded_bundle)
    except (ValidationError, ValueError) as exc:
        raise SkillEvidenceError(
            "Skill evidence bundle has an invalid schema or member path"
        ) from exc

    try:
        catalog = load_skill_catalog(catalog_path)
        manifest = next(
            skill for skill in catalog.skills if skill.name == bundle.skill_name
        )
    except (OSError, ValidationError, StopIteration, ValueError) as exc:
        raise SkillEvidenceError("Published Skill manifest could not be loaded") from exc
    if manifest.lifecycle_state != "PUBLISHED" or manifest.source is None:
        raise SkillEvidenceError("Skill evidence requires a sourced PUBLISHED Skill")
    if (
        manifest.version != bundle.skill_version
        or manifest.source.content_hash != bundle.skill_content_hash
    ):
        raise SkillEvidenceError("Skill evidence does not match the published version")
    if manifest.source.workspace_snapshot is None or manifest.source.commit is not None:
        raise SkillEvidenceError("Team-original Skill requires a workspace snapshot")
    actual_source_hash = _verify_workspace_skill_source(
        catalog_path,
        manifest.source.path,
    )
    if (
        actual_source_hash != manifest.source.workspace_snapshot
        or actual_source_hash != manifest.source.content_hash
    ):
        raise SkillEvidenceError("Skill source snapshot digest does not match the catalog")

    task_ids = [item.task_id for item in bundle.invocations]
    invocation_ids = [item.invocation_id for item in bundle.invocations]
    member_names = [
        name
        for item in bundle.invocations
        for name in (
            item.tool_call_path,
            item.invocation_path,
            item.provider_evidence_path,
        )
    ]
    if len(set(task_ids)) != len(task_ids):
        raise SkillEvidenceError("Skill evidence task IDs must be distinct")
    if len(set(invocation_ids)) != len(invocation_ids):
        raise SkillEvidenceError("Skill invocation IDs must be distinct")
    if len(set(member_names)) != len(member_names):
        raise SkillEvidenceError("Skill evidence member paths must be distinct")

    root = resolved_bundle.parent
    verified_items: list[dict[str, str]] = []
    for item in bundle.invocations:
        tool_path = _bundle_member(root, item.tool_call_path)
        invocation_path = _bundle_member(root, item.invocation_path)
        provider_path = _bundle_member(root, item.provider_evidence_path)
        tool_bytes = _read_evidence_bytes(tool_path, "ToolCall evidence")
        invocation_bytes = _read_evidence_bytes(
            invocation_path,
            "Skill invocation evidence",
        )
        provider_bytes = _read_evidence_bytes(provider_path, "Provider evidence")
        if _sha256_bytes(tool_bytes) != item.tool_call_sha256:
            raise SkillEvidenceError("ToolCall evidence digest does not match")
        if _sha256_bytes(invocation_bytes) != item.invocation_sha256:
            raise SkillEvidenceError("Skill invocation evidence digest does not match")
        if _sha256_bytes(provider_bytes) != item.provider_evidence_sha256:
            raise SkillEvidenceError("Provider evidence digest does not match")
        try:
            tool_call = ToolCallEventRecord.model_validate_json(tool_bytes)
            invocation = SkillInvocationEvidenceRecord.model_validate_json(
                invocation_bytes
            )
            provider = PatchScopeProviderEvidence.model_validate_json(provider_bytes)
        except (ValidationError, ValueError) as exc:
            raise SkillEvidenceError("Skill execution closure has invalid evidence") from exc
        if not tool_call.has_valid_payload_digest():
            raise SkillEvidenceError("ToolCall payload digest is invalid")
        if not invocation.has_valid_payload_digest():
            raise SkillEvidenceError("Skill invocation payload digest is invalid")
        closure_matches = (
            item.task_id == invocation.task_id == tool_call.task_id == provider.task_id
            and item.invocation_id == invocation.invocation_id
            and invocation.step_id == tool_call.step_id == provider.step_id
            and invocation.agent_name == tool_call.actor == "agentloom-verifier"
            and invocation.skill_name == bundle.skill_name
            and invocation.skill_version == bundle.skill_version
            and invocation.skill_content_hash == bundle.skill_content_hash
            and invocation.grant_id == tool_call.grant_id
            and invocation.tool_call_event_id == tool_call.event_id
            and invocation.tool_call_payload_digest == tool_call.payload_digest
            and invocation.input_digest == tool_call.parameter_digest
            and invocation.output_digest == tool_call.output_digest
            and invocation.evidence_ref == provider_path.stem
            and invocation.evidence_ref in tool_call.evidence_refs
            and invocation.evidence_sha256 == item.provider_evidence_sha256
            and tool_call.output_digest == item.provider_evidence_sha256
            and invocation.status == tool_call.status == "SUCCEEDED"
            and tool_call.provider_id == "patch-scope-validator/v1.0.1"
            and tool_call.tool_name == "patch-scope-validator"
            and tool_call.action == "patch.validate:scope"
            and provider.verdict == "PASSED"
            and provider.patch_sha256 is not None
            and not provider.violations
            and provider.error_code is None
        )
        if not closure_matches:
            raise SkillEvidenceError("Skill execution closure does not match")
        verified_items.append(item.model_dump(mode="json", by_alias=True))

    return {
        "schemaVersion": bundle.schema_version,
        "status": bundle.status,
        "skillName": bundle.skill_name,
        "skillVersion": bundle.skill_version,
        "skillContentHash": bundle.skill_content_hash,
        "invocationCount": len(bundle.invocations),
        "invocations": verified_items,
        "bundleSha256": _sha256_bytes(encoded_bundle),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--output-root", type=Path)
    operation.add_argument("--verify-bundle", type=Path)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("skills/catalog.json"),
    )
    arguments = parser.parse_args()
    if arguments.verify_bundle is not None:
        output = verify_patch_scope_evidence_bundle(
            arguments.verify_bundle,
            arguments.catalog,
        )
    else:
        assert arguments.output_root is not None
        summary = asyncio.run(
            generate_patch_scope_evidence(arguments.output_root, arguments.catalog)
        )
        bundle_path = arguments.output_root / "skill-invocation-bundle.json"
        output = {
            **summary,
            "bundleSha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
        }
    print(json.dumps(output, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
