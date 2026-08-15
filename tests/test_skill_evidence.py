import asyncio
import hashlib
import json
from pathlib import Path
from typing import cast

import pytest

from agentloom.contracts import SkillInvocationEvidenceRecord, ToolCallEventRecord
from agentloom.skill_evidence import (
    SkillEvidenceError,
    generate_patch_scope_evidence,
    verify_patch_scope_evidence_bundle,
)


def test_generate_patch_scope_evidence_produces_three_complete_closures(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[1]
    output_root = tmp_path / "skill-evidence"

    summary = asyncio.run(
        generate_patch_scope_evidence(
            output_root,
            repository_root / "skills" / "catalog.json",
        )
    )

    assert summary["schemaVersion"] == "agentloom.skill-invocation-bundle/v1alpha1"
    assert summary["status"] == "PASSED"
    invocations = cast(list[dict[str, str]], summary["invocations"])
    assert len(invocations) == 3
    assert len({item["taskId"] for item in invocations}) == 3
    assert len({item["invocationId"] for item in invocations}) == 3

    for item in invocations:
        tool_path = output_root / item["toolCallPath"]
        invocation_path = output_root / item["invocationPath"]
        provider_path = output_root / item["providerEvidencePath"]
        assert hashlib.sha256(tool_path.read_bytes()).hexdigest() == item["toolCallSha256"]
        assert (
            hashlib.sha256(invocation_path.read_bytes()).hexdigest()
            == item["invocationSha256"]
        )
        tool_call = ToolCallEventRecord.model_validate_json(
            tool_path.read_text(encoding="utf-8")
        )
        invocation = SkillInvocationEvidenceRecord.model_validate_json(
            invocation_path.read_text(encoding="utf-8")
        )
        assert tool_call.has_valid_payload_digest()
        assert invocation.has_valid_payload_digest()
        assert invocation.tool_call_event_id == tool_call.event_id
        assert invocation.tool_call_payload_digest == tool_call.payload_digest
        assert invocation.evidence_ref == provider_path.stem
        assert invocation.evidence_sha256 == hashlib.sha256(
            provider_path.read_bytes()
        ).hexdigest()
        provider_evidence = json.loads(provider_path.read_text(encoding="utf-8"))
        assert provider_evidence["verdict"] == "PASSED"


def test_generate_patch_scope_evidence_refuses_existing_root(tmp_path: Path) -> None:
    repository_root = Path(__file__).parents[1]
    output_root = tmp_path / "skill-evidence"
    output_root.mkdir()

    with pytest.raises(FileExistsError):
        asyncio.run(
            generate_patch_scope_evidence(
                output_root,
                repository_root / "skills" / "catalog.json",
            )
        )


def test_verify_patch_scope_evidence_bundle_reopens_all_execution_closures(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[1]
    output_root = tmp_path / "skill-evidence"
    asyncio.run(
        generate_patch_scope_evidence(
            output_root,
            repository_root / "skills" / "catalog.json",
        )
    )

    verified = verify_patch_scope_evidence_bundle(
        output_root / "skill-invocation-bundle.json",
        repository_root / "skills" / "catalog.json",
    )

    assert verified["status"] == "PASSED"
    assert verified["invocationCount"] == 3
    assert verified["skillName"] == "patch-scope-validator"
    assert len(cast(list[dict[str, str]], verified["invocations"])) == 3


def test_verify_patch_scope_evidence_bundle_rejects_tampered_provider_evidence(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[1]
    output_root = tmp_path / "skill-evidence"
    summary = asyncio.run(
        generate_patch_scope_evidence(
            output_root,
            repository_root / "skills" / "catalog.json",
        )
    )
    item = cast(list[dict[str, str]], summary["invocations"])[0]
    provider_path = output_root / item["providerEvidencePath"]
    provider_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(SkillEvidenceError, match="digest"):
        verify_patch_scope_evidence_bundle(
            output_root / "skill-invocation-bundle.json",
            repository_root / "skills" / "catalog.json",
        )


def test_verify_patch_scope_evidence_bundle_rejects_member_path_escape(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[1]
    output_root = tmp_path / "skill-evidence"
    asyncio.run(
        generate_patch_scope_evidence(
            output_root,
            repository_root / "skills" / "catalog.json",
        )
    )
    bundle_path = output_root / "skill-invocation-bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["invocations"][0]["toolCallPath"] = "../outside.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    with pytest.raises(SkillEvidenceError, match="member path"):
        verify_patch_scope_evidence_bundle(
            bundle_path,
            repository_root / "skills" / "catalog.json",
        )
