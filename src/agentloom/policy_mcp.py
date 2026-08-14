"""MCP transport for the fail-closed AgentLoom Policy Broker."""

import os
import re
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from datetime import UTC, datetime
from hmac import compare_digest
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from agentloom.capabilities import ToolProvider
from agentloom.contracts import (
    AgentIdentity,
    GrantIssuanceRequest,
    GrantVerificationRequest,
    SignedSkillExecutionGrant,
    SkillExecutionGrant,
    ToolCallEventRecord,
    ToolExecutionEnvelope,
    ToolExecutionResult,
)
from agentloom.docker_sandbox import DockerSandboxProvider
from agentloom.local_tools import LocalTestRunnerProvider
from agentloom.policy import (
    InMemoryNonceStore,
    NonceStore,
    PolicyDenied,
    SkillGrantAuthorizer,
    TrustedGrantIssuer,
)
from agentloom.sandbox_tools import SandboxedTestRunnerProvider
from agentloom.skill_catalog import load_skill_provider
from agentloom.storage import Database, DatabaseNonceStore

POLICY_VERIFY_TOOL = "verify_skill_execution_grant"
GRANT_ISSUE_TOOL = "issue_skill_execution_grant"
TOOL_EXECUTE_TOOL = "execute_governed_tool"
POLICY_SIGNING_KEY_ENV = "AGENTLOOM_POLICY_SIGNING_KEY"
POLICY_TOOL_WORKSPACE_ENV = "AGENTLOOM_TOOL_WORKSPACE"
POLICY_EVIDENCE_ROOT_ENV = "AGENTLOOM_TOOL_EVIDENCE_ROOT"
POLICY_DATABASE_URL_ENV = "AGENTLOOM_DATABASE_URL"
POLICY_SKILL_CATALOG_ENV = "AGENTLOOM_SKILL_CATALOG"
POLICY_MCP_TRANSPORT_ENV = "AGENTLOOM_MCP_TRANSPORT"
POLICY_HTTP_HOST_ENV = "AGENTLOOM_MCP_HOST"
POLICY_HTTP_PORT_ENV = "AGENTLOOM_MCP_PORT"
POLICY_HTTP_PUBLIC_HOST_ENV = "AGENTLOOM_MCP_PUBLIC_HOST"
POLICY_GATEWAY_ASSERTION_ENV = "AGENTLOOM_GATEWAY_ASSERTION"
POLICY_SANDBOX_BACKEND_ENV = "AGENTLOOM_SANDBOX_BACKEND"
POLICY_SANDBOX_IMAGE_ENV = "AGENTLOOM_SANDBOX_IMAGE"
POLICY_ALLOW_HOST_TEST_EXECUTION_ENV = "AGENTLOOM_ALLOW_HOST_TEST_EXECUTION"

MCPTransport = Literal["stdio", "sse", "streamable-http"]
_TRUSTED_GATEWAY_CONSUMER: ContextVar[str | None] = ContextVar(
    "agentloom_trusted_gateway_consumer",
    default=None,
)


def trusted_gateway_consumer() -> str | None:
    """Return the gateway-authenticated consumer for the active HTTP request."""

    return _TRUSTED_GATEWAY_CONSUMER.get()


class GatewayIdentityMiddleware:
    """Reject direct or ambiguous requests before they enter an MCP session."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        assertion_secret: str,
        allowed_consumers: set[str],
    ) -> None:
        if len(assertion_secret) < 32:
            raise ValueError("gateway assertion must contain at least 32 characters")
        self._app = app
        self._assertion_secret = assertion_secret
        self._allowed_consumers = frozenset(allowed_consumers)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        consumer_values = self._header_values(scope, b"x-mse-consumer")
        assertion_values = self._header_values(
            scope,
            b"x-agentloom-gateway-assertion",
        )
        if len(consumer_values) != 1 or len(assertion_values) != 1:
            await PlainTextResponse("authentication required", status_code=401)(
                scope,
                receive,
                send,
            )
            return
        assertion = assertion_values[0]
        if not compare_digest(assertion, self._assertion_secret):
            await PlainTextResponse("authentication required", status_code=401)(
                scope,
                receive,
                send,
            )
            return
        consumer = consumer_values[0]
        if consumer not in self._allowed_consumers:
            await PlainTextResponse("forbidden", status_code=403)(scope, receive, send)
            return
        token = _TRUSTED_GATEWAY_CONSUMER.set(consumer)
        try:
            await self._app(scope, receive, send)
        finally:
            _TRUSTED_GATEWAY_CONSUMER.reset(token)

    @staticmethod
    def _header_values(scope: Scope, name: bytes) -> list[str]:
        values: list[str] = []
        for raw_name, raw_value in scope.get("headers", []):
            if raw_name.lower() == name:
                try:
                    values.append(raw_value.decode("ascii"))
                except UnicodeDecodeError:
                    return []
        return values


def create_policy_broker_mcp(
    authorizer: SkillGrantAuthorizer,
    *,
    tool_provider: ToolProvider | None = None,
    tool_call_recorder: Callable[[ToolCallEventRecord], object] | None = None,
    grant_issuer: TrustedGrantIssuer | None = None,
    consumer_agents: Mapping[str, AgentIdentity] | None = None,
    trusted_consumer_getter: Callable[[], str | None] = trusted_gateway_consumer,
    host: str = "127.0.0.1",
    port: int = 8000,
    public_host: str = "localhost",
) -> FastMCP:
    """Create the single-tool MCP boundary around a trusted grant authorizer."""
    server = FastMCP(
        "agentloom-policy-broker",
        instructions=(
            "Verify a signed, parameter-bound SkillExecutionGrant immediately before "
            "one governed tool call. Grants are short-lived and cannot be replayed."
        ),
        host=host,
        port=port,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[
                public_host,
                f"{public_host}:*",
                "127.0.0.1:*",
                "localhost:*",
                "[::1]:*",
            ],
            allowed_origins=[
                f"http://{public_host}:*",
                "http://127.0.0.1:*",
                "http://localhost:*",
                "http://[::1]:*",
            ],
        ),
    )

    def require_grant_consumer(signed_grant: SignedSkillExecutionGrant) -> None:
        if consumer_agents is None:
            return
        consumer = trusted_consumer_getter()
        agent = consumer_agents.get(consumer) if consumer is not None else None
        if agent is None or agent.name != signed_grant.grant.agent_name:
            raise PolicyDenied("consumer is not authorized to execute Grant")

    @server.tool(
        name=POLICY_VERIFY_TOOL,
        description=(
            "Verify and consume one signed SkillExecutionGrant. Returns POLICY_DENIED "
            "for invalid, expired, mismatched, or replayed grants."
        ),
    )
    def verify_skill_execution_grant(
        request: GrantVerificationRequest,
    ) -> SkillExecutionGrant:
        try:
            require_grant_consumer(request.signed_grant)
            return authorizer.verify(
                request.signed_grant,
                parameter_digest=request.parameter_digest,
            )
        except PolicyDenied as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    if grant_issuer is not None:

        @server.tool(
            name=GRANT_ISSUE_TOOL,
            description=(
                "Issue one short-lived SkillExecutionGrant from authoritative task, "
                "Skill, and gateway-authenticated Agent identity."
            ),
        )
        async def issue_skill_execution_grant(
            request: GrantIssuanceRequest,
        ) -> SignedSkillExecutionGrant:
            try:
                return await grant_issuer.issue(
                    request,
                    trusted_consumer=trusted_consumer_getter(),
                )
            except PolicyDenied as exc:
                raise ToolError(f"{exc.code}: {exc}") from exc

    if tool_provider is not None:

        @server.tool(
            name=TOOL_EXECUTE_TOOL,
            description=(
                "Verify one signed SkillExecutionGrant and execute its bound tool "
                "through the configured ToolProvider."
            ),
        )
        async def execute_governed_tool(
            request: ToolExecutionEnvelope,
        ) -> ToolExecutionResult:
            try:
                require_grant_consumer(request.signed_grant)
            except PolicyDenied as exc:
                raise ToolError(f"{exc.code}: {exc}") from exc
            try:
                requested_paths = tool_provider.requested_paths(request.tool_request)
            except ValueError as exc:
                raise ToolError(
                    "POLICY_DENIED: tool parameters are not authorized"
                ) from exc
            try:
                authorizer.verify(
                    request.signed_grant,
                    parameter_digest=request.tool_request.parameter_digest,
                    requested_paths=requested_paths,
                )
            except PolicyDenied as exc:
                raise ToolError(f"{exc.code}: {exc}") from exc
            result = await tool_provider.execute(request.tool_request)
            if tool_call_recorder is not None:
                event = ToolCallEventRecord.from_execution(
                    event_id=f"tool-event-{uuid4().hex}",
                    request=request.tool_request,
                    result=result,
                    provider_id=tool_provider.provider_id,
                    grant_id=request.signed_grant.grant.grant_id,
                    actor=request.tool_request.agent_name,
                    created_at=datetime.now(UTC),
                )
                try:
                    tool_call_recorder(event)
                except Exception as exc:
                    raise ToolError(
                        "TOOL_EVENT_RECORDING_FAILED: tool result was not committed"
                    ) from exc
            return result

    return server


def create_policy_broker_mcp_from_env(
    *,
    trusted_consumer_getter: Callable[[], str | None] = trusted_gateway_consumer,
) -> FastMCP:
    """Create a transport-neutral server from validated process configuration."""
    signing_key = os.environ.get(POLICY_SIGNING_KEY_ENV)
    if signing_key is None:
        raise RuntimeError(f"{POLICY_SIGNING_KEY_ENV} is required")
    transport = _transport_from_env()
    if transport == "streamable-http":
        _gateway_assertion_from_env()
    host, port, public_host = _http_settings_from_env()
    workspace = os.environ.get(POLICY_TOOL_WORKSPACE_ENV)
    evidence_root = os.environ.get(POLICY_EVIDENCE_ROOT_ENV)
    database_url = os.environ.get(POLICY_DATABASE_URL_ENV)
    skill_catalog = os.environ.get(POLICY_SKILL_CATALOG_ENV)
    tool_configuration = (workspace, evidence_root, database_url)
    database: Database | None = None
    provider: ToolProvider | None = None
    trusted_consumer_agents = {
        "worker-agentloom-verifier": _verifier_identity(),
    }
    consumer_agents = (
        trusted_consumer_agents if transport == "streamable-http" else None
    )
    if any(value is not None for value in tool_configuration):
        if not all(value is not None for value in tool_configuration):
            raise RuntimeError(
                f"{POLICY_TOOL_WORKSPACE_ENV}, {POLICY_EVIDENCE_ROOT_ENV}, and "
                f"{POLICY_DATABASE_URL_ENV} must be configured together"
            )
        assert workspace is not None
        assert evidence_root is not None
        assert database_url is not None
        provider = tool_provider_from_env(Path(workspace), Path(evidence_root))
        database = Database(database_url)
        database.create_schema()
    nonce_store: NonceStore = (
        DatabaseNonceStore(database) if database is not None else InMemoryNonceStore()
    )
    authorizer = SkillGrantAuthorizer(signing_key.encode("utf-8"), nonce_store)
    grant_issuer: TrustedGrantIssuer | None = None
    if skill_catalog is not None:
        if database is None:
            raise RuntimeError(
                f"{POLICY_SKILL_CATALOG_ENV} requires {POLICY_DATABASE_URL_ENV}"
            )
        grant_issuer = TrustedGrantIssuer(
            authorizer,
            skill_provider=load_skill_provider(Path(skill_catalog)),
            task_lookup=database.get_task,
            consumer_agents=trusted_consumer_agents,
        )
    return create_policy_broker_mcp(
        authorizer,
        tool_provider=provider,
        tool_call_recorder=database.record_tool_call if database is not None else None,
        grant_issuer=grant_issuer,
        consumer_agents=consumer_agents,
        trusted_consumer_getter=trusted_consumer_getter,
        host=host,
        port=port,
        public_host=public_host,
    )


def tool_provider_from_env(
    workspace: Path,
    evidence_root: Path,
) -> ToolProvider:
    """Construct the configured Tool Provider without executing a tool call."""
    backend = os.environ.get(POLICY_SANDBOX_BACKEND_ENV)
    if backend is None:
        raise RuntimeError(f"{POLICY_SANDBOX_BACKEND_ENV} is required")
    if backend == "docker":
        image_ref = os.environ.get(POLICY_SANDBOX_IMAGE_ENV)
        if image_ref is None:
            raise RuntimeError(f"{POLICY_SANDBOX_IMAGE_ENV} is required for docker")
        try:
            sandbox = DockerSandboxProvider(workspace, image_ref)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        return SandboxedTestRunnerProvider(workspace, evidence_root, sandbox)
    if backend == "local-development":
        acknowledgement = os.environ.get(POLICY_ALLOW_HOST_TEST_EXECUTION_ENV)
        if acknowledgement != "true":
            raise RuntimeError(
                f"{POLICY_ALLOW_HOST_TEST_EXECUTION_ENV}=true is required for "
                "local-development"
            )
        return LocalTestRunnerProvider(workspace, evidence_root)
    raise RuntimeError(f"{POLICY_SANDBOX_BACKEND_ENV} is invalid")


def _verifier_identity() -> AgentIdentity:
    return AgentIdentity(
        name="agentloom-verifier",
        role="independent verification",
        capabilities=["repo.read", "tests.read", "tests.execute", "tools.audit"],
        inputs=["PatchArtifact", "acceptance criteria", "Evidence"],
        outputs=["VerificationResult", "RiskReport", "Badcase"],
        dependencies=["test-runner", "static-check-adapter"],
        decision_boundary=[
            "cannot modify the patch",
            "cannot lower acceptance criteria",
        ],
        trace=["governed tool calls", "test evidence", "verdict"],
    )


def _http_settings_from_env() -> tuple[str, int, str]:
    host = os.environ.get(POLICY_HTTP_HOST_ENV, "127.0.0.1")
    raw_port = os.environ.get(POLICY_HTTP_PORT_ENV, "8000")
    public_host = os.environ.get(POLICY_HTTP_PUBLIC_HOST_ENV, "localhost")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise RuntimeError(f"{POLICY_HTTP_PORT_ENV} must be an integer") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError(f"{POLICY_HTTP_PORT_ENV} must be between 1 and 65535")
    if not re.fullmatch(r"(?:[A-Za-z0-9.-]+|\[[A-Fa-f0-9:]+\])", public_host):
        raise RuntimeError(f"{POLICY_HTTP_PUBLIC_HOST_ENV} is invalid")
    return host, port, public_host


def _transport_from_env() -> MCPTransport:
    value = os.environ.get(POLICY_MCP_TRANSPORT_ENV, "stdio")
    if value not in {"stdio", "sse", "streamable-http"}:
        raise RuntimeError(f"{POLICY_MCP_TRANSPORT_ENV} is invalid")
    return cast(MCPTransport, value)


def _gateway_assertion_from_env() -> str:
    assertion = os.environ.get(POLICY_GATEWAY_ASSERTION_ENV)
    if assertion is None or len(assertion) < 32:
        raise RuntimeError(
            f"{POLICY_GATEWAY_ASSERTION_ENV} must contain at least 32 characters"
        )
    return assertion


def main() -> None:
    """Run the Policy Broker using the configured MCP transport."""
    server = create_policy_broker_mcp_from_env()
    transport = _transport_from_env()
    if transport != "streamable-http":
        server.run(transport=transport)
        return

    import uvicorn

    app = GatewayIdentityMiddleware(
        server.streamable_http_app(),
        assertion_secret=_gateway_assertion_from_env(),
        allowed_consumers={
            "worker-agentloom-investigator",
            "worker-agentloom-implementer",
            "worker-agentloom-verifier",
        },
    )
    uvicorn.run(
        app,
        host=server.settings.host,
        port=server.settings.port,
        log_level=server.settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
