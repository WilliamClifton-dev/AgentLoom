import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from agentloom.contracts import (
    AgentIdentity,
    GrantIssuanceRequest,
    SkillCatalog,
    SkillEvaluation,
    SkillExecutionGrant,
    SkillManifest,
    SkillSource,
    TaskCreate,
    TaskTransition,
    tool_parameter_digest,
)
from agentloom.policy import InMemoryNonceStore, SkillGrantAuthorizer
from agentloom.policy_mcp import (
    GRANT_ISSUE_TOOL,
    POLICY_ALLOW_HOST_TEST_EXECUTION_ENV,
    POLICY_DATABASE_URL_ENV,
    POLICY_EVIDENCE_ROOT_ENV,
    POLICY_GATEWAY_ASSERTION_ENV,
    POLICY_HTTP_HOST_ENV,
    POLICY_HTTP_PORT_ENV,
    POLICY_HTTP_PUBLIC_HOST_ENV,
    POLICY_MCP_TRANSPORT_ENV,
    POLICY_SANDBOX_BACKEND_ENV,
    POLICY_SANDBOX_IMAGE_ENV,
    POLICY_SIGNING_KEY_ENV,
    POLICY_SKILL_CATALOG_ENV,
    POLICY_TOOL_WORKSPACE_ENV,
    TOOL_EXECUTE_TOOL,
    GatewayIdentityMiddleware,
    _transport_from_env,
    create_policy_broker_mcp_from_env,
    trusted_gateway_consumer,
)
from agentloom.storage import Database

SIGNING_KEY = "test-signing-key-with-32-bytes!!"
GATEWAY_ASSERTION = "a" * 64


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_tcp_listener(port: int, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            _, stderr = process.communicate()
            raise AssertionError(f"Policy Broker exited before startup: {stderr}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("Policy Broker did not open its HTTP listener")


def test_environment_composition_executes_and_replays_local_tool_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp.server.fastmcp.exceptions import ToolError

    workspace = tmp_path / "workspace"
    evidence = tmp_path / "evidence"
    database_url = f"sqlite:///{tmp_path / 'broker.db'}"
    (workspace / "tests").mkdir(parents=True)
    (workspace / "tests" / "test_ok.py").write_text(
        "import os\n\n"
        "def test_ok() -> None:\n"
        "    assert 'AGENTLOOM_POLICY_SIGNING_KEY' not in os.environ\n",
        encoding="utf-8",
    )
    database = Database(database_url)
    database.create_schema()
    task = database.create_task(
        TaskCreate(
            title="Run the governed local test provider",
            repository_uri="fixture://policy-tool-e2e",
            issue="The policy broker must execute and record one bounded test.",
            acceptance_criteria=["The test passes and the ToolCall can be replayed."],
            allowed_paths=["tests/test_ok.py"],
        )
    )
    parameters: dict[str, object] = {
        "command": ["pytest", "-q", "tests/test_ok.py"],
        "workingDirectory": ".",
        "timeoutSeconds": 30,
        "outputLimitBytes": 65536,
    }
    digest = tool_parameter_digest(parameters)
    issued_at = datetime.now(UTC)
    grant = SkillExecutionGrant(
        grant_id="grant-tool-e2e",
        task_id=task.task_id,
        step_id="verify-01",
        agent_name="agentloom-verifier",
        skill_name="code-review-and-quality",
        skill_version="1.0.0",
        skill_content_hash=f"sha256:{'b' * 64}",
        tool_name="test-runner",
        action="process.exec:test",
        parameter_digest=digest,
        authorized_paths=["tests/test_ok.py"],
        risk_level="L1",
        nonce="nonce-tool-e2e",
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=5),
    )
    manifest = SkillManifest(
        name="code-review-and-quality",
        version="1.0.0",
        skill_type="external-skill",
        scenarios=["verification"],
        input_schema="schemas/review-input.json",
        output_schema="schemas/review-output.json",
        invocation_conditions=["patch-frozen"],
        dependencies=["test-runner"],
        failure_modes=["TEST_FAILED"],
        permissions=["tests.execute"],
        security_boundary="L1 isolated workspace",
        reuse_value="Reusable independent verification",
        source=SkillSource(
            repository="https://github.com/example/skills",
            path="skills/code-review-and-quality",
            commit="a" * 40,
            license="MIT",
            content_hash=f"sha256:{'b' * 64}",
        ),
        compatible_agents=["agentloom-verifier"],
        allowed_tools=["test-runner:process.exec:test"],
        allowed_paths=["tests/test_ok.py"],
        risk_level="L1",
        evaluation=SkillEvaluation(
            upstream_evidence_refs=["ev-upstream-review"],
            agentloom_bench_evidence_refs=["ev-agentloom-review"],
        ),
        lifecycle_state="PUBLISHED",
    )
    agent = AgentIdentity(
        name="agentloom-verifier",
        role="independent verification",
        capabilities=["tests.execute"],
        inputs=["PatchArtifact"],
        outputs=["VerificationResult"],
        dependencies=["code-review-and-quality"],
        decision_boundary=["cannot modify workspace"],
        trace=["tool calls"],
    )
    signed = SkillGrantAuthorizer(
        SIGNING_KEY.encode(), InMemoryNonceStore()
    ).issue(
        grant,
        manifest=manifest,
        agent=agent,
        requested_paths=["tests/test_ok.py"],
        task_allowed_paths=["tests/test_ok.py"],
    )
    monkeypatch.setenv(POLICY_SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv(POLICY_TOOL_WORKSPACE_ENV, str(workspace))
    monkeypatch.setenv(POLICY_EVIDENCE_ROOT_ENV, str(evidence))
    monkeypatch.setenv(POLICY_DATABASE_URL_ENV, database_url)
    monkeypatch.setenv(POLICY_SANDBOX_BACKEND_ENV, "local-development")
    monkeypatch.setenv(POLICY_ALLOW_HOST_TEST_EXECUTION_ENV, "true")
    monkeypatch.setenv(POLICY_MCP_TRANSPORT_ENV, "streamable-http")
    monkeypatch.setenv(POLICY_GATEWAY_ASSERTION_ENV, GATEWAY_ASSERTION)
    wrong_server = create_policy_broker_mcp_from_env(
        trusted_consumer_getter=lambda: "worker-agentloom-implementer"
    )
    server = create_policy_broker_mcp_from_env(
        trusted_consumer_getter=lambda: "worker-agentloom-verifier"
    )

    async def execute() -> None:
        envelope = {
            "request": {
                "signedGrant": signed.model_dump(mode="json", by_alias=True),
                "toolRequest": {
                    "taskId": grant.task_id,
                    "stepId": grant.step_id,
                    "agentName": grant.agent_name,
                    "skillName": grant.skill_name,
                    "skillVersion": grant.skill_version,
                    "toolName": grant.tool_name,
                    "action": grant.action,
                    "parameterDigest": digest,
                    "parameters": parameters,
                },
            }
        }
        with pytest.raises(ToolError, match="consumer is not authorized to execute"):
            await wrong_server.call_tool(TOOL_EXECUTE_TOOL, envelope)

        raw_result = await server.call_tool(TOOL_EXECUTE_TOOL, envelope)
        # MCP's runtime returns this tuple for tools with an output schema, but
        # its public annotation omits the structured-output tuple variant.
        _, structured = cast(tuple[object, dict[str, object]], raw_result)
        assert structured["status"] == "SUCCEEDED"

    asyncio.run(execute())

    events = database.list_tool_calls(task.task_id)
    assert len(events) == 1
    assert events[0].provider_id == "local-test-runner"
    assert events[0].grant_id == "grant-tool-e2e"
    assert events[0].has_valid_payload_digest()
    assert len(list(evidence.glob("*.txt"))) == 1
    invocation_paths = list(evidence.glob("skill-invocation-*.json"))
    assert len(invocation_paths) == 1
    invocation = json.loads(invocation_paths[0].read_text(encoding="utf-8"))
    assert invocation["skillName"] == "code-review-and-quality"
    assert invocation["toolCallEventId"] == events[0].event_id
    assert invocation["toolCallPayloadDigest"] == events[0].payload_digest


def test_environment_composition_issues_executes_and_rejects_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp.server.fastmcp.exceptions import ToolError

    workspace = tmp_path / "workspace"
    evidence = tmp_path / "evidence"
    database_url = f"sqlite:///{tmp_path / 'broker.db'}"
    catalog_path = tmp_path / "catalog.json"
    (workspace / "tests").mkdir(parents=True)
    (workspace / "tests" / "test_ok.py").write_text(
        "def test_ok() -> None:\n"
        "    assert True\n",
        encoding="utf-8",
    )
    database = Database(database_url)
    database.create_schema()
    task = database.create_task(
        TaskCreate(
            title="Issue and execute one governed verifier Grant",
            repository_uri="fixture://trusted-grant-e2e",
            issue="The Broker must derive identity and reject Grant replay.",
            acceptance_criteria=["One governed pytest call is persisted."],
            allowed_paths=["tests/test_ok.py"],
        )
    )
    for status in ("PLANNED", "INVESTIGATING", "IMPLEMENTING", "VERIFYING"):
        updated = database.transition_task(
            task.task_id,
            TaskTransition(
                expected_plan_version=task.plan_version,
                status=status,
                reason=f"Advance fixture to {status}.",
            ),
        )
        assert updated is not None
        task = updated

    manifest = SkillManifest(
        name="code-review-and-quality",
        version="1.0.0",
        skill_type="governed-external-skill",
        scenarios=["verification"],
        input_schema="schemas/skills/review-input.schema.json",
        output_schema="schemas/skills/review-findings.schema.json",
        invocation_conditions=["patch-frozen"],
        dependencies=["test-runner"],
        failure_modes=["TEST_FAILED"],
        permissions=["tests.execute"],
        security_boundary="L1 isolated verifier workspace",
        reuse_value="Reusable independent verification",
        source=SkillSource(
            repository="https://github.com/addyosmani/agent-skills",
            path="skills/code-review-and-quality",
            commit="a" * 40,
            license="MIT",
            content_hash=f"sha256:{'b' * 64}",
        ),
        compatible_agents=["agentloom-verifier"],
        allowed_tools=["test-runner:process.exec:test"],
        allowed_paths=["tests/**"],
        risk_level="L1",
        evaluation=SkillEvaluation(
            upstream_evidence_refs=["ev-upstream-review"],
            agentloom_bench_evidence_refs=["ev-agentloom-governed-pytest"],
        ),
        lifecycle_state="PUBLISHED",
    )
    catalog_path.write_text(
        SkillCatalog(skills=[manifest]).model_dump_json(by_alias=True),
        encoding="utf-8",
    )
    parameters: dict[str, object] = {
        "command": ["pytest", "-q", "tests/test_ok.py"],
        "workingDirectory": ".",
        "timeoutSeconds": 30,
        "outputLimitBytes": 65536,
    }
    issuance = GrantIssuanceRequest(
        task_id=task.task_id,
        step_id="verify-01",
        skill_name=manifest.name,
        skill_version=manifest.version,
        tool_name="test-runner",
        action="process.exec:test",
        parameter_digest=tool_parameter_digest(parameters),
        requested_paths=["tests/test_ok.py"],
    )

    monkeypatch.setenv(POLICY_SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv(POLICY_TOOL_WORKSPACE_ENV, str(workspace))
    monkeypatch.setenv(POLICY_EVIDENCE_ROOT_ENV, str(evidence))
    monkeypatch.setenv(POLICY_DATABASE_URL_ENV, database_url)
    monkeypatch.setenv(POLICY_SANDBOX_BACKEND_ENV, "local-development")
    monkeypatch.setenv(POLICY_ALLOW_HOST_TEST_EXECUTION_ENV, "true")
    monkeypatch.setenv(POLICY_SKILL_CATALOG_ENV, str(catalog_path))
    server = create_policy_broker_mcp_from_env(
        trusted_consumer_getter=lambda: "worker-agentloom-verifier"
    )

    async def execute() -> None:
        issue_raw = await server.call_tool(
            GRANT_ISSUE_TOOL,
            {"request": issuance.model_dump(mode="json", by_alias=True)},
        )
        _, signed = cast(tuple[object, dict[str, object]], issue_raw)
        envelope = {
            "request": {
                "signedGrant": signed,
                "toolRequest": {
                    "taskId": task.task_id,
                    "stepId": issuance.step_id,
                    "agentName": "agentloom-verifier",
                    "skillName": manifest.name,
                    "skillVersion": manifest.version,
                    "toolName": issuance.tool_name,
                    "action": issuance.action,
                    "parameterDigest": issuance.parameter_digest,
                    "parameters": parameters,
                },
            }
        }
        result_raw = await server.call_tool(TOOL_EXECUTE_TOOL, envelope)
        _, result = cast(tuple[object, dict[str, object]], result_raw)
        assert result["status"] == "SUCCEEDED"
        restarted_server = create_policy_broker_mcp_from_env(
            trusted_consumer_getter=lambda: "worker-agentloom-verifier"
        )
        with pytest.raises(ToolError, match="nonce has already been used"):
            await restarted_server.call_tool(TOOL_EXECUTE_TOOL, envelope)

    asyncio.run(execute())
    events = database.list_tool_calls(task.task_id)
    assert len(events) == 1
    assert events[0].actor == "agentloom-verifier"
    assert len(list(evidence.glob("*.txt"))) == 1


def test_environment_composition_rejects_partial_tool_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(POLICY_SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv(POLICY_TOOL_WORKSPACE_ENV, str(tmp_path))
    monkeypatch.delenv(POLICY_EVIDENCE_ROOT_ENV, raising=False)
    monkeypatch.delenv(POLICY_DATABASE_URL_ENV, raising=False)

    with pytest.raises(RuntimeError, match="must be configured together"):
        create_policy_broker_mcp_from_env()


def test_environment_composition_requires_explicit_sandbox_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(POLICY_SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv(POLICY_TOOL_WORKSPACE_ENV, str(tmp_path))
    monkeypatch.setenv(POLICY_EVIDENCE_ROOT_ENV, str(tmp_path / "evidence"))
    monkeypatch.setenv(POLICY_DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'broker.db'}")
    monkeypatch.delenv(POLICY_SANDBOX_BACKEND_ENV, raising=False)

    with pytest.raises(RuntimeError, match="AGENTLOOM_SANDBOX_BACKEND is required"):
        create_policy_broker_mcp_from_env()


def test_environment_composition_requires_immutable_docker_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(POLICY_SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv(POLICY_TOOL_WORKSPACE_ENV, str(tmp_path))
    monkeypatch.setenv(POLICY_EVIDENCE_ROOT_ENV, str(tmp_path / "evidence"))
    monkeypatch.setenv(POLICY_DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'broker.db'}")
    monkeypatch.setenv(POLICY_SANDBOX_BACKEND_ENV, "docker")
    monkeypatch.setenv(POLICY_SANDBOX_IMAGE_ENV, "python:3.12")

    with pytest.raises(RuntimeError, match="immutable image ID or digest"):
        create_policy_broker_mcp_from_env()


def test_environment_composition_requires_host_execution_acknowledgement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(POLICY_SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv(POLICY_TOOL_WORKSPACE_ENV, str(tmp_path))
    monkeypatch.setenv(POLICY_EVIDENCE_ROOT_ENV, str(tmp_path / "evidence"))
    monkeypatch.setenv(POLICY_DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'broker.db'}")
    monkeypatch.setenv(POLICY_SANDBOX_BACKEND_ENV, "local-development")
    monkeypatch.delenv(POLICY_ALLOW_HOST_TEST_EXECUTION_ENV, raising=False)

    with pytest.raises(RuntimeError, match="AGENTLOOM_ALLOW_HOST_TEST_EXECUTION=true"):
        create_policy_broker_mcp_from_env()


def test_environment_composition_accepts_pinned_docker_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(POLICY_SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv(POLICY_TOOL_WORKSPACE_ENV, str(tmp_path))
    monkeypatch.setenv(POLICY_EVIDENCE_ROOT_ENV, str(tmp_path / "evidence"))
    monkeypatch.setenv(POLICY_DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'broker.db'}")
    monkeypatch.setenv(POLICY_SANDBOX_BACKEND_ENV, "docker")
    monkeypatch.setenv(POLICY_SANDBOX_IMAGE_ENV, "sha256:" + "d" * 64)

    server = create_policy_broker_mcp_from_env()

    assert TOOL_EXECUTE_TOOL in {tool.name for tool in server._tool_manager.list_tools()}


def test_environment_composition_configures_streamable_http_security(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(POLICY_SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv(POLICY_MCP_TRANSPORT_ENV, "streamable-http")
    monkeypatch.setenv(POLICY_GATEWAY_ASSERTION_ENV, GATEWAY_ASSERTION)
    monkeypatch.setenv(POLICY_HTTP_HOST_ENV, "0.0.0.0")
    monkeypatch.setenv(POLICY_HTTP_PORT_ENV, "8765")
    monkeypatch.setenv(POLICY_HTTP_PUBLIC_HOST_ENV, "host.docker.internal")

    server = create_policy_broker_mcp_from_env()

    assert server.settings.host == "0.0.0.0"
    assert server.settings.port == 8765
    transport_security = server.settings.transport_security
    assert transport_security is not None
    assert "host.docker.internal" in transport_security.allowed_hosts
    assert "host.docker.internal:*" in transport_security.allowed_hosts


def test_gateway_identity_middleware_rejects_bypass_and_duplicate_headers() -> None:
    async def endpoint(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse({"consumer": trusted_gateway_consumer()})
        await response(scope, receive, send)

    app = GatewayIdentityMiddleware(
        endpoint,
        assertion_secret=GATEWAY_ASSERTION,
        allowed_consumers={"worker-agentloom-verifier"},
    )

    async def probe() -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            missing = await client.post("/mcp")
            assert missing.status_code == 401

            direct = await client.post(
                "/mcp",
                headers={"X-Mse-Consumer": "worker-agentloom-verifier"},
            )
            assert direct.status_code == 401

            unrelated = await client.post(
                "/mcp",
                headers={
                    "X-Mse-Consumer": "worker-alert-intake",
                    "X-AgentLoom-Gateway-Assertion": GATEWAY_ASSERTION,
                },
            )
            assert unrelated.status_code == 403

            duplicate = await client.post(
                "/mcp",
                headers=[
                    ("X-Mse-Consumer", "worker-agentloom-verifier"),
                    ("X-Mse-Consumer", "worker-agentloom-verifier"),
                    ("X-AgentLoom-Gateway-Assertion", GATEWAY_ASSERTION),
                ],
            )
            assert duplicate.status_code == 401

            accepted = await client.post(
                "/mcp",
                headers={
                    "X-Mse-Consumer": "worker-agentloom-verifier",
                    "X-AgentLoom-Gateway-Assertion": GATEWAY_ASSERTION,
                },
            )
            assert accepted.status_code == 200
            assert accepted.json() == {"consumer": "worker-agentloom-verifier"}

    asyncio.run(probe())


def test_environment_composition_requires_gateway_assertion_for_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(POLICY_SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv(POLICY_MCP_TRANSPORT_ENV, "streamable-http")
    monkeypatch.delenv(POLICY_GATEWAY_ASSERTION_ENV, raising=False)

    with pytest.raises(RuntimeError, match=POLICY_GATEWAY_ASSERTION_ENV):
        create_policy_broker_mcp_from_env()


def test_environment_composition_rejects_invalid_http_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(POLICY_SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv(POLICY_HTTP_PORT_ENV, "70000")

    with pytest.raises(RuntimeError, match="must be between 1 and 65535"):
        create_policy_broker_mcp_from_env()


def test_environment_composition_rejects_unknown_mcp_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(POLICY_MCP_TRANSPORT_ENV, "websocket")

    with pytest.raises(RuntimeError, match="AGENTLOOM_MCP_TRANSPORT is invalid"):
        _transport_from_env()


def test_streamable_http_process_initializes_and_lists_policy_tools() -> None:
    port = _unused_local_port()
    environment = os.environ.copy()
    for optional_setting in (
        POLICY_TOOL_WORKSPACE_ENV,
        POLICY_EVIDENCE_ROOT_ENV,
        POLICY_DATABASE_URL_ENV,
        POLICY_SANDBOX_BACKEND_ENV,
        POLICY_SANDBOX_IMAGE_ENV,
        POLICY_ALLOW_HOST_TEST_EXECUTION_ENV,
    ):
        environment.pop(optional_setting, None)
    environment.update(
        {
            POLICY_SIGNING_KEY_ENV: SIGNING_KEY,
            POLICY_MCP_TRANSPORT_ENV: "streamable-http",
            POLICY_GATEWAY_ASSERTION_ENV: GATEWAY_ASSERTION,
            POLICY_HTTP_HOST_ENV: "127.0.0.1",
            POLICY_HTTP_PORT_ENV: str(port),
            POLICY_HTTP_PUBLIC_HOST_ENV: "127.0.0.1",
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "agentloom.policy_mcp"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_tcp_listener(port, process)

        async def probe() -> set[str]:
            async with AsyncClient(
                headers={
                    "X-Mse-Consumer": "worker-agentloom-verifier",
                    "X-AgentLoom-Gateway-Assertion": GATEWAY_ASSERTION,
                }
            ) as http_client:
                async with streamable_http_client(
                    f"http://127.0.0.1:{port}/mcp",
                    http_client=http_client,
                ) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        result = await session.list_tools()
                        return {tool.name for tool in result.tools}

        assert asyncio.run(probe()) == {"verify_skill_execution_grant"}
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)


def test_streamable_http_process_issues_executes_and_fails_closed(
    tmp_path: Path,
) -> None:
    port = _unused_local_port()
    workspace = tmp_path / "workspace"
    evidence = tmp_path / "evidence"
    database_path = tmp_path / "broker.db"
    database_url = f"sqlite:///{database_path}"
    repository_root = Path(__file__).resolve().parents[1]
    (workspace / "tests").mkdir(parents=True)
    (workspace / "tests" / "test_ok.py").write_text(
        "def test_ok() -> None:\n"
        "    assert True\n",
        encoding="utf-8",
    )
    (workspace / "tests" / "test_other.py").write_text(
        "def test_other() -> None:\n"
        "    assert True\n",
        encoding="utf-8",
    )
    database = Database(database_url)
    database.create_schema()
    task = database.create_task(
        TaskCreate(
            title="Streamable HTTP trusted Grant flow",
            repository_uri="fixture://streamable-grant-e2e",
            issue="Verify trusted consumer propagation across the MCP session.",
            acceptance_criteria=["One bounded test call succeeds."],
            allowed_paths=["tests/test_ok.py"],
        )
    )
    for status in ("PLANNED", "INVESTIGATING", "IMPLEMENTING", "VERIFYING"):
        updated = database.transition_task(
            task.task_id,
            TaskTransition(
                expected_plan_version=task.plan_version,
                status=status,
                reason=f"Advance fixture to {status}.",
            ),
        )
        assert updated is not None
        task = updated

    parameters: dict[str, object] = {
        "command": ["pytest", "-q", "tests/test_ok.py"],
        "workingDirectory": ".",
        "timeoutSeconds": 30,
        "outputLimitBytes": 65536,
    }
    digest = tool_parameter_digest(parameters)
    issue_request = {
        "taskId": task.task_id,
        "stepId": "verify-http-01",
        "skillName": "code-review-and-quality",
        "skillVersion": "0.0.0+upstream.7829ffd",
        "toolName": "test-runner",
        "action": "process.exec:test",
        "parameterDigest": digest,
        "requestedPaths": ["tests/test_ok.py"],
    }
    environment = os.environ.copy()
    environment.update(
        {
            POLICY_SIGNING_KEY_ENV: SIGNING_KEY,
            POLICY_GATEWAY_ASSERTION_ENV: GATEWAY_ASSERTION,
            POLICY_TOOL_WORKSPACE_ENV: str(workspace),
            POLICY_EVIDENCE_ROOT_ENV: str(evidence),
            POLICY_DATABASE_URL_ENV: database_url,
            POLICY_SANDBOX_BACKEND_ENV: "local-development",
            POLICY_ALLOW_HOST_TEST_EXECUTION_ENV: "true",
            POLICY_SKILL_CATALOG_ENV: str(repository_root / "skills" / "catalog.json"),
            POLICY_MCP_TRANSPORT_ENV: "streamable-http",
            POLICY_HTTP_HOST_ENV: "127.0.0.1",
            POLICY_HTTP_PORT_ENV: str(port),
            POLICY_HTTP_PUBLIC_HOST_ENV: "127.0.0.1",
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "agentloom.policy_mcp"],
        cwd=repository_root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_tcp_listener(port, process)
        url = f"http://127.0.0.1:{port}/mcp"

        async def probe() -> None:
            async with AsyncClient(base_url=f"http://127.0.0.1:{port}") as direct:
                assert (await direct.post("/mcp")).status_code == 401
                duplicate = await direct.post(
                    "/mcp",
                    headers=[
                        ("X-Mse-Consumer", "worker-agentloom-verifier"),
                        ("X-Mse-Consumer", "worker-agentloom-verifier"),
                        ("X-AgentLoom-Gateway-Assertion", GATEWAY_ASSERTION),
                    ],
                )
                assert duplicate.status_code == 401

            async with AsyncClient(
                headers={
                    "X-Mse-Consumer": "worker-agentloom-implementer",
                    "X-AgentLoom-Gateway-Assertion": GATEWAY_ASSERTION,
                }
            ) as wrong_client:
                async with streamable_http_client(
                    url,
                    http_client=wrong_client,
                ) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        denied = await session.call_tool(
                            GRANT_ISSUE_TOOL,
                            {"request": issue_request},
                        )
                        assert denied.isError is True
                        assert "consumer is not authorized" in str(denied.content)

            async with AsyncClient(
                headers={
                    "X-Mse-Consumer": "worker-agentloom-verifier",
                    "X-AgentLoom-Gateway-Assertion": GATEWAY_ASSERTION,
                }
            ) as verifier_client:
                async with streamable_http_client(
                    url,
                    http_client=verifier_client,
                ) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        issued = await session.call_tool(
                            GRANT_ISSUE_TOOL,
                            {"request": issue_request},
                        )
                        assert issued.isError is False
                        assert issued.structuredContent is not None
                        signed = issued.structuredContent
                        assert signed["grant"]["agentName"] == "agentloom-verifier"
                        envelope = {
                            "request": {
                                "signedGrant": signed,
                                "toolRequest": {
                                    "taskId": task.task_id,
                                    "stepId": "verify-http-01",
                                    "agentName": "agentloom-verifier",
                                    "skillName": "code-review-and-quality",
                                    "skillVersion": "0.0.0+upstream.7829ffd",
                                    "toolName": "test-runner",
                                    "action": "process.exec:test",
                                    "parameterDigest": digest,
                                    "parameters": parameters,
                                },
                            }
                        }
                        async with AsyncClient(
                            headers={
                                "X-Mse-Consumer": "worker-agentloom-implementer",
                                "X-AgentLoom-Gateway-Assertion": GATEWAY_ASSERTION,
                            }
                        ) as implementer_client:
                            async with streamable_http_client(
                                url,
                                http_client=implementer_client,
                            ) as implementer_streams:
                                async with ClientSession(
                                    implementer_streams[0], implementer_streams[1]
                                ) as implementer_session:
                                    await implementer_session.initialize()
                                    wrong_agent = await implementer_session.call_tool(
                                        TOOL_EXECUTE_TOOL,
                                        envelope,
                                    )
                                    assert wrong_agent.isError is True
                                    assert "consumer is not authorized to execute" in str(
                                        wrong_agent.content
                                    )

                        other_parameters: dict[str, object] = {
                            **parameters,
                            "command": ["pytest", "-q", "tests/test_other.py"],
                        }
                        other_digest = tool_parameter_digest(other_parameters)
                        path_mismatch_request = {
                            **issue_request,
                            "stepId": "verify-http-path-mismatch",
                            "parameterDigest": other_digest,
                        }
                        path_issued = await session.call_tool(
                            GRANT_ISSUE_TOOL,
                            {"request": path_mismatch_request},
                        )
                        assert path_issued.isError is False
                        assert path_issued.structuredContent is not None
                        path_mismatch = await session.call_tool(
                            TOOL_EXECUTE_TOOL,
                            {
                                "request": {
                                    "signedGrant": path_issued.structuredContent,
                                    "toolRequest": {
                                        **envelope["request"]["toolRequest"],
                                        "stepId": "verify-http-path-mismatch",
                                        "parameterDigest": other_digest,
                                        "parameters": other_parameters,
                                    },
                                }
                            },
                        )
                        assert path_mismatch.isError is True
                        assert "path is not authorized by grant" in str(
                            path_mismatch.content
                        )

                        tampered = {
                            "request": {
                                **envelope["request"],
                                "toolRequest": {
                                    **envelope["request"]["toolRequest"],
                                    "parameters": {
                                        **parameters,
                                        "timeoutSeconds": 31,
                                    },
                                },
                            }
                        }
                        rejected = await session.call_tool(TOOL_EXECUTE_TOOL, tampered)
                        assert rejected.isError is True
                        assert "parameters do not match parameterDigest" in str(
                            rejected.content
                        )

                        executed = await session.call_tool(TOOL_EXECUTE_TOOL, envelope)
                        assert executed.isError is False
                        assert executed.structuredContent is not None
                        assert executed.structuredContent["status"] == "SUCCEEDED"

                        replayed = await session.call_tool(TOOL_EXECUTE_TOOL, envelope)
                        assert replayed.isError is True
                        assert "nonce has already been used" in str(replayed.content)

        asyncio.run(probe())
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)

    events = database.list_tool_calls(task.task_id)
    assert len(events) == 1
    assert events[0].actor == "agentloom-verifier"
    assert len(list(evidence.glob("*.txt"))) == 1
