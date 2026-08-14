from __future__ import annotations

import hashlib
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentloom.contracts import ToolCallEventRecord, ToolExecutionResult
from agentloom.docker_sandbox import workspace_tree_digest
from agentloom.sandbox_e2e import (
    SandboxE2EContext,
    SandboxE2EVerificationError,
    prepare_sandbox_e2e,
    verify_sandbox_e2e,
)
from agentloom.storage import Database

IMAGE_REF = "sha256:" + "e" * 64
ROOT = Path(__file__).resolve().parents[1]
CASE_ROOT = ROOT / "demo" / "cases" / "pagination-boundary"


def create_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    shutil.copytree(CASE_ROOT / "before", workspace)
    return workspace


def prepare(tmp_path: Path) -> tuple[Database, Path, SandboxE2EContext]:
    workspace = create_workspace(tmp_path)
    database_url = f"sqlite:///{tmp_path / 'broker.db'}"
    context = prepare_sandbox_e2e(
        database_url=database_url,
        workspace=workspace,
        skill_catalog=Path(__file__).resolve().parents[1] / "skills" / "catalog.json",
        case_root=CASE_ROOT,
    )
    return Database(database_url), workspace, context


def test_prepare_sandbox_e2e_binds_two_verifier_tasks_to_one_snapshot(
    tmp_path: Path,
) -> None:
    database, workspace, context = prepare(tmp_path)

    assert context.schema_version == "agentloom.sandbox-e2e-context/v1alpha1"
    assert context.case_id == "pagination-boundary"
    assert len(context.case_fingerprint) == 64
    assert context.workspace_digest == workspace_tree_digest(workspace)
    assert set(context.tasks) == {"direct", "model"}
    assert context.tasks["direct"].task_id != context.tasks["model"].task_id
    for task in context.tasks.values():
        stored = database.get_task(task.task_id)
        assert stored is not None
        assert stored.status == "VERIFYING"
        assert stored.allowed_paths == ["tests/test_pagination.py"]
        assert task.issuance_request.parameter_digest == task.tool_request.parameter_digest
        assert task.tool_request.parameters["workspaceDigest"] == context.workspace_digest
        assert task.tool_request.parameters["command"] == [
            "pytest",
            "-q",
            "tests/test_pagination.py::test_page_count_exact_multiple",
        ]
        assert task.tool_request.parameters["workingDirectory"] == "."


@pytest.mark.parametrize(
    "case_id",
    ["severity-normalization", "pagination-boundary", "retry-delay-cap"],
)
def test_prepare_sandbox_e2e_derives_governed_request_from_case(
    tmp_path: Path,
    case_id: str,
) -> None:
    case_root = ROOT / "demo" / "cases" / case_id
    workspace = tmp_path / case_id
    shutil.copytree(case_root / "before", workspace)

    context = prepare_sandbox_e2e(
        database_url=f"sqlite:///{tmp_path / f'{case_id}.db'}",
        workspace=workspace,
        skill_catalog=ROOT / "skills" / "catalog.json",
        case_root=case_root,
    )

    assert context.case_id == case_id
    assert context.tasks["direct"].tool_request.parameters["command"][-1].startswith(
        "tests/test_"
    )
    assert context.tasks["direct"].issuance_request.requested_paths == [
        context.tasks["direct"].tool_request.parameters["command"][-1].split("::")[0]
    ]


def test_verify_sandbox_e2e_requires_matching_toolcall_and_docker_evidence(
    tmp_path: Path,
) -> None:
    database, _, context = prepare(tmp_path)
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    direct = context.tasks["direct"]
    evidence_content = (
        "STATUS: SUCCEEDED\n"
        "SANDBOX_PROVIDER: docker-sandbox\n"
        f"IMAGE_REF: {IMAGE_REF}\n"
        f"SNAPSHOT_DIGEST: {context.workspace_digest}\n"
        "EXIT_CODE: 0\n"
        "STDOUT:\n1 passed\n"
        "STDERR:\n\n"
    )
    output_digest = hashlib.sha256(evidence_content.encode()).hexdigest()
    result = ToolExecutionResult(
        status="SUCCEEDED",
        evidence_refs=["ev-tool-direct"],
        output_digest=output_digest,
    )
    event = ToolCallEventRecord.from_execution(
        event_id="tool-event-direct",
        request=direct.tool_request,
        result=result,
        provider_id="sandboxed-test-runner/docker-sandbox",
        grant_id="grant-direct",
        actor="agentloom-verifier",
        created_at=datetime.now(UTC),
    )
    database.record_tool_call(event)
    (evidence_root / "ev-tool-direct.txt").write_bytes(evidence_content.encode())

    verified = verify_sandbox_e2e(
        database_url=str(database.engine.url),
        evidence_root=evidence_root,
        context=context,
        expected_image=IMAGE_REF,
        task_names=["direct"],
    )

    assert verified["direct"].provider_id == "sandboxed-test-runner/docker-sandbox"
    assert verified["direct"].evidence_ref == "ev-tool-direct"


def test_verify_sandbox_e2e_rejects_missing_or_host_provider_evidence(
    tmp_path: Path,
) -> None:
    database, _, context = prepare(tmp_path)
    direct = context.tasks["direct"]
    result = ToolExecutionResult(
        status="SUCCEEDED",
        evidence_refs=["ev-tool-host"],
        output_digest="b" * 64,
    )
    database.record_tool_call(
        ToolCallEventRecord.from_execution(
            event_id="tool-event-host",
            request=direct.tool_request,
            result=result,
            provider_id="local-test-runner",
            grant_id="grant-host",
            actor="agentloom-verifier",
            created_at=datetime.now(UTC),
        )
    )

    with pytest.raises(SandboxE2EVerificationError, match="Docker provider"):
        verify_sandbox_e2e(
            database_url=str(database.engine.url),
            evidence_root=tmp_path / "evidence",
            context=context,
            expected_image=IMAGE_REF,
            task_names=["direct"],
        )
