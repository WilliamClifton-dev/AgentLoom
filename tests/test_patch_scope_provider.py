import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from agentloom.capabilities import ToolProvider
from agentloom.contracts import ToolExecutionRequest, tool_parameter_digest
from agentloom.skills.patch_scope_validator import PatchScopeValidatorProvider


def _patch(old_path: str = "src/severity.py", new_path: str | None = None) -> str:
    destination = new_path or old_path
    return (
        f"diff --git a/{old_path} b/{destination}\n"
        f"--- a/{old_path}\n"
        f"+++ b/{destination}\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new"
    )


def _request(patch: str, allowed_paths: list[str]) -> ToolExecutionRequest:
    parameters: dict[str, object] = {
        "patch": patch,
        "patchSha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
        "allowedPaths": allowed_paths,
    }
    return ToolExecutionRequest(
        task_id="task-scope-01",
        step_id="scope-01",
        agent_name="agentloom-verifier",
        skill_name="patch-scope-validator",
        skill_version="1.0.1",
        tool_name="patch-scope-validator",
        action="patch.validate:scope",
        parameter_digest=tool_parameter_digest(parameters),
        parameters=parameters,
    )


def test_patch_scope_provider_satisfies_tool_contract_and_writes_evidence(
    tmp_path: Path,
) -> None:
    provider: ToolProvider = PatchScopeValidatorProvider(tmp_path)
    request = _request(_patch(), ["src/severity.py"])

    assert provider.provider_id == "patch-scope-validator/v1.0.1"
    assert provider.requested_paths(request) == ["src/severity.py"]

    result = asyncio.run(provider.execute(request))

    assert result.status == "SUCCEEDED"
    assert result.error_code is None
    assert len(result.evidence_refs) == 1
    evidence_path = tmp_path / f"{result.evidence_refs[0]}.json"
    assert result.output_digest == hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["schemaVersion"] == "agentloom.patch-scope-result/v1alpha1"
    assert evidence["verdict"] == "PASSED"
    assert evidence["actualModifiedPaths"] == ["src/severity.py"]


def test_patch_scope_provider_reports_rename_source_and_destination(
    tmp_path: Path,
) -> None:
    provider = PatchScopeValidatorProvider(tmp_path)
    request = _request(_patch("src/old.py", "src/new.py"), ["src/new.py"])

    assert provider.requested_paths(request) == ["src/new.py", "src/old.py"]
    result = asyncio.run(provider.execute(request))

    assert result.status == "FAILED"
    assert result.error_code == "PATCH_SCOPE_VIOLATION"


@pytest.mark.parametrize(
    "patch",
    [
        "",
        _patch("../outside.py"),
        _patch("/absolute.py"),
    ],
)
def test_patch_scope_provider_rejects_empty_or_unsafe_diff(
    tmp_path: Path,
    patch: str,
) -> None:
    provider = PatchScopeValidatorProvider(tmp_path)
    request = _request(patch, ["src/**"])

    with pytest.raises(ValueError, match="patch"):
        provider.requested_paths(request)


def test_patch_scope_provider_denies_hash_mismatch(tmp_path: Path) -> None:
    provider = PatchScopeValidatorProvider(tmp_path)
    request = _request(_patch(), ["src/severity.py"])
    parameters = {**request.parameters, "patchSha256": "0" * 64}
    mismatched = request.model_copy(
        update={
            "parameters": parameters,
            "parameter_digest": tool_parameter_digest(parameters),
        }
    )

    result = asyncio.run(provider.execute(mismatched))

    assert result.status == "DENIED"
    assert result.error_code == "PATCH_HASH_MISMATCH"


def test_patch_scope_provider_denies_patch_over_128_kib(tmp_path: Path) -> None:
    provider = PatchScopeValidatorProvider(tmp_path)
    oversized = _patch() + ("\n context" * 20_000)
    request = _request(oversized, ["src/severity.py"])

    result = asyncio.run(provider.execute(request))

    assert result.status == "DENIED"
    assert result.error_code == "PATCH_TOO_LARGE"
