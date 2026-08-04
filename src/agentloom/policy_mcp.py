"""MCP transport for the fail-closed AgentLoom Policy Broker."""

import os

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from agentloom.contracts import GrantVerificationRequest, SkillExecutionGrant
from agentloom.policy import InMemoryNonceStore, PolicyDenied, SkillGrantAuthorizer

POLICY_VERIFY_TOOL = "verify_skill_execution_grant"
POLICY_SIGNING_KEY_ENV = "AGENTLOOM_POLICY_SIGNING_KEY"


def create_policy_broker_mcp(authorizer: SkillGrantAuthorizer) -> FastMCP:
    """Create the single-tool MCP boundary around a trusted grant authorizer."""
    server = FastMCP(
        "agentloom-policy-broker",
        instructions=(
            "Verify a signed, parameter-bound SkillExecutionGrant immediately before "
            "one governed tool call. Grants are short-lived and cannot be replayed."
        ),
    )

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
            return authorizer.verify(
                request.signed_grant,
                parameter_digest=request.parameter_digest,
            )
        except PolicyDenied as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    return server


def create_policy_broker_mcp_from_env() -> FastMCP:
    """Create the stdio server using the process-local signing key."""
    signing_key = os.environ.get(POLICY_SIGNING_KEY_ENV)
    if signing_key is None:
        raise RuntimeError(f"{POLICY_SIGNING_KEY_ENV} is required")
    authorizer = SkillGrantAuthorizer(
        signing_key.encode("utf-8"),
        InMemoryNonceStore(),
    )
    return create_policy_broker_mcp(authorizer)


def main() -> None:
    """Run the Policy Broker MCP server over stdio."""
    create_policy_broker_mcp_from_env().run(transport="stdio")


if __name__ == "__main__":
    main()
