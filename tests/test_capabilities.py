import pytest

from agentloom.capabilities import (
    CallableToolProvider,
    CallableVerifierProvider,
    CatalogSkillProvider,
    SkillNotFound,
)
from agentloom.contracts import (
    PatchArtifact,
    SkillCatalog,
    SkillManifest,
    SkillResolutionRequest,
    ToolExecutionRequest,
    ToolExecutionResult,
    VerificationChecks,
    VerificationRequest,
    VerificationResult,
    tool_parameter_digest,
)


def published_skill() -> SkillManifest:
    return SkillManifest(
        name="debugging-and-error-recovery",
        version="1.0.0",
        skill_type="external-skill",
        scenarios=["bug-triage"],
        input_schema="schemas/debugging-input.json",
        output_schema="schemas/root-cause-report.json",
        invocation_conditions=["issue-and-repository-present"],
        dependencies=["repository-search"],
        failure_modes=["INSUFFICIENT_EVIDENCE"],
        permissions=["repo.read"],
        security_boundary="L0 read-only",
        reuse_value="Reusable for defect investigation",
        lifecycle_state="DISCOVERED",
    )


def tool_request() -> ToolExecutionRequest:
    return ToolExecutionRequest(
        task_id="task-01",
        step_id="step-01",
        agent_name="agentloom-investigator",
        skill_name="debugging-and-error-recovery",
        skill_version="1.0.0",
        tool_name="repository-search",
        action="repo.read",
        parameter_digest=tool_parameter_digest({}),
    )


def verification_request() -> VerificationRequest:
    patch = PatchArtifact(
        task_id="task-01",
        patch_uri="artifact://task-01/repair.patch",
        sha256="b" * 64,
        changed_paths=["src/example.py"],
        evidence_refs=["ev-patch"],
    )
    return VerificationRequest(
        task_id="task-01",
        patch=patch,
        evidence_refs=["ev-patch"],
        allowed_paths=["src/**"],
    )


@pytest.mark.asyncio
async def test_catalog_skill_provider_resolves_pinned_version() -> None:
    skill = published_skill()
    provider = CatalogSkillProvider(SkillCatalog(skills=[skill]))

    resolved = await provider.resolve(
        SkillResolutionRequest(name=skill.name, version=skill.version)
    )

    assert provider.provider_id == "local-catalog"
    assert resolved == skill


@pytest.mark.asyncio
async def test_catalog_skill_provider_fails_closed_for_unknown_version() -> None:
    provider = CatalogSkillProvider(SkillCatalog(skills=[published_skill()]))

    with pytest.raises(SkillNotFound):
        await provider.resolve(
            SkillResolutionRequest(
                name="debugging-and-error-recovery",
                version="9.9.9",
            )
        )


@pytest.mark.asyncio
async def test_tool_provider_contract_returns_canonical_result() -> None:
    request = tool_request()
    provider = CallableToolProvider(
        "local-tool",
        lambda received: _tool_result(received),
    )

    result = await provider.execute(request)

    assert provider.provider_id == "local-tool"
    assert result.status == "SUCCEEDED"
    assert result.evidence_refs == ["ev-tool"]


async def _tool_result(request: ToolExecutionRequest) -> ToolExecutionResult:
    assert request.task_id == "task-01"
    return ToolExecutionResult(status="SUCCEEDED", evidence_refs=["ev-tool"])


@pytest.mark.asyncio
async def test_verifier_provider_contract_preserves_patch_binding() -> None:
    request = verification_request()

    async def verify(received: VerificationRequest) -> VerificationResult:
        return VerificationResult(
            task_id=received.task_id,
            patch_hash=received.patch.sha256,
            verdict="PASSED",
            checks=VerificationChecks(
                original_failure_reproduced=True,
                target_tests_passed=True,
                regression_tests_passed=True,
                static_checks_passed=True,
                unauthorized_changes=False,
            ),
            evidence_refs=received.evidence_refs,
            reason="independent checks passed",
            verifier_agent="agentloom-verifier",
        )

    provider = CallableVerifierProvider("local-verifier", verify)
    result = await provider.verify(request)

    assert provider.provider_id == "local-verifier"
    assert result.patch_hash == request.patch.sha256
