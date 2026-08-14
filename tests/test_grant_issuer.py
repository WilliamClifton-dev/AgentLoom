import asyncio
from datetime import UTC, datetime
from typing import cast

import pytest

from agentloom.capabilities import CatalogSkillProvider
from agentloom.contracts import (
    AgentIdentity,
    GrantIssuanceRequest,
    SkillCatalog,
    SkillEvaluation,
    SkillManifest,
    SkillSource,
    TaskRecord,
)
from agentloom.policy import (
    InMemoryNonceStore,
    PolicyDenied,
    SkillGrantAuthorizer,
    TrustedGrantIssuer,
)
from agentloom.policy_mcp import GRANT_ISSUE_TOOL, create_policy_broker_mcp

SIGNING_KEY = b"test-signing-key-with-32-bytes!!"
NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def _manifest(**overrides: object) -> SkillManifest:
    values: dict[str, object] = {
        "name": "code-review-and-quality",
        "version": "1.0.0",
        "skill_type": "governed-external-skill",
        "scenarios": ["independent-verification"],
        "input_schema": "schemas/skills/review-input.schema.json",
        "output_schema": "schemas/skills/review-findings.schema.json",
        "invocation_conditions": ["patch-frozen"],
        "dependencies": ["test-runner"],
        "failure_modes": ["TEST_FAILED"],
        "permissions": ["tests.execute"],
        "security_boundary": "L1 isolated verifier workspace",
        "reuse_value": "Reusable independent verification",
        "source": SkillSource(
            repository="https://github.com/addyosmani/agent-skills",
            path="skills/code-review-and-quality",
            commit="a" * 40,
            license="MIT",
            content_hash=f"sha256:{'b' * 64}",
        ),
        "compatible_agents": ["agentloom-verifier"],
        "allowed_tools": ["test-runner:process.exec:test"],
        "allowed_paths": ["tests/**"],
        "risk_level": "L1",
        "evaluation": SkillEvaluation(
            upstream_evidence_refs=["ev-upstream-review"],
            agentloom_bench_evidence_refs=["ev-agentloom-review"],
        ),
        "lifecycle_state": "PUBLISHED",
    }
    values.update(overrides)
    return SkillManifest.model_validate(values)


def _verifier() -> AgentIdentity:
    return AgentIdentity(
        name="agentloom-verifier",
        role="independent verification",
        capabilities=["repo.read", "tests.execute"],
        inputs=["PatchArtifact"],
        outputs=["VerificationResult"],
        dependencies=["test-runner"],
        decision_boundary=["cannot modify the patch"],
        trace=["governed tool calls"],
    )


def _task(status: str = "VERIFYING") -> TaskRecord:
    return TaskRecord(
        task_id="task-01",
        title="Verify a frozen patch",
        repository_uri="fixture://grant-issuer",
        issue="Run the bounded verifier tests.",
        acceptance_criteria=["The governed pytest command passes."],
        allowed_paths=["tests/test_parser.py"],
        status=status,
        plan_version=4,
        created_at=NOW,
    )


def _request(**overrides: object) -> GrantIssuanceRequest:
    values: dict[str, object] = {
        "task_id": "task-01",
        "step_id": "verify-01",
        "skill_name": "code-review-and-quality",
        "skill_version": "1.0.0",
        "tool_name": "test-runner",
        "action": "process.exec:test",
        "parameter_digest": "c" * 64,
        "requested_paths": ["tests/test_parser.py"],
    }
    values.update(overrides)
    return GrantIssuanceRequest.model_validate(values)


def _issuer(task: TaskRecord, manifest: SkillManifest | None = None) -> TrustedGrantIssuer:
    token_values = iter(("grant-token", "nonce-token"))
    provider = CatalogSkillProvider(SkillCatalog(skills=[manifest or _manifest()]))
    return TrustedGrantIssuer(
        SkillGrantAuthorizer(SIGNING_KEY, InMemoryNonceStore(), clock=lambda: NOW),
        skill_provider=provider,
        task_lookup=lambda task_id: task if task_id == task.task_id else None,
        consumer_agents={"worker-agentloom-verifier": _verifier()},
        clock=lambda: NOW,
        token_factory=lambda: next(token_values),
    )


def test_trusted_issuer_derives_verifier_and_server_owned_grant_fields() -> None:
    signed = asyncio.run(
        _issuer(_task()).issue(
            _request(),
            trusted_consumer="worker-agentloom-verifier",
        )
    )

    grant = signed.grant
    assert grant.agent_name == "agentloom-verifier"
    assert grant.grant_id == "grant-grant-token"
    assert grant.nonce == "nonce-token"
    assert grant.issued_at == NOW
    assert (grant.expires_at - grant.issued_at).total_seconds() == 300
    assert grant.skill_content_hash == f"sha256:{'b' * 64}"
    assert grant.risk_level == "L1"
    assert grant.authorized_paths == ["tests/test_parser.py"]


@pytest.mark.parametrize(
    ("trusted_consumer", "task", "manifest", "message"),
    [
        (None, _task(), _manifest(), "trusted gateway consumer is required"),
        ("worker-agentloom-implementer", _task(), _manifest(), "consumer is not authorized"),
        (
            "worker-agentloom-verifier",
            _task("IMPLEMENTING"),
            _manifest(),
            "task is not in VERIFYING",
        ),
        (
            "worker-agentloom-verifier",
            _task(),
            _manifest(lifecycle_state="QUARANTINED", evaluation=None),
            "Skill is not published",
        ),
    ],
)
def test_trusted_issuer_fails_closed(
    trusted_consumer: str | None,
    task: TaskRecord,
    manifest: SkillManifest,
    message: str,
) -> None:
    with pytest.raises(PolicyDenied, match=message):
        asyncio.run(
            _issuer(task, manifest).issue(
                _request(),
                trusted_consumer=trusted_consumer,
            )
        )


def test_trusted_issuer_rejects_unknown_task_and_path_escalation() -> None:
    issuer = _issuer(_task())

    with pytest.raises(PolicyDenied, match="task is unavailable"):
        asyncio.run(
            issuer.issue(
                _request(task_id="task-missing"),
                trusted_consumer="worker-agentloom-verifier",
            )
        )
    with pytest.raises(PolicyDenied, match="not allowed by the task"):
        asyncio.run(
            issuer.issue(
                _request(requested_paths=["tests/test_other.py"]),
                trusted_consumer="worker-agentloom-verifier",
            )
        )


def test_policy_broker_issues_grant_for_trusted_request_context_only() -> None:
    from mcp.server.fastmcp.exceptions import ToolError

    request = _request()
    issuer = _issuer(_task())
    server = create_policy_broker_mcp(
        SkillGrantAuthorizer(SIGNING_KEY, InMemoryNonceStore(), clock=lambda: NOW),
        grant_issuer=issuer,
        trusted_consumer_getter=lambda: "worker-agentloom-verifier",
    )

    async def issue() -> None:
        raw_result = await server.call_tool(
            GRANT_ISSUE_TOOL,
            {"request": request.model_dump(mode="json", by_alias=True)},
        )
        _, structured = cast(tuple[object, dict[str, object]], raw_result)
        assert structured is not None
        grant = cast(dict[str, object], structured["grant"])
        assert grant["agentName"] == "agentloom-verifier"

        forged = request.model_dump(mode="json", by_alias=True)
        forged["agentName"] = "agentloom-implementer"
        with pytest.raises(ToolError, match="extra_forbidden"):
            await server.call_tool(GRANT_ISSUE_TOOL, {"request": forged})

    asyncio.run(issue())


def test_policy_broker_issuance_fails_without_trusted_request_context() -> None:
    from mcp.server.fastmcp.exceptions import ToolError

    server = create_policy_broker_mcp(
        SkillGrantAuthorizer(SIGNING_KEY, InMemoryNonceStore(), clock=lambda: NOW),
        grant_issuer=_issuer(_task()),
    )

    async def reject() -> None:
        with pytest.raises(ToolError, match="trusted gateway consumer is required"):
            await server.call_tool(
                GRANT_ISSUE_TOOL,
                {"request": _request().model_dump(mode="json", by_alias=True)},
            )

    asyncio.run(reject())
