"""Provider-neutral capability contracts and local reference providers."""

from collections.abc import Awaitable, Callable
from typing import Protocol

from agentloom.contracts import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SkillCatalog,
    SkillManifest,
    SkillResolutionRequest,
    ToolExecutionRequest,
    ToolExecutionResult,
    VerificationRequest,
    VerificationResult,
)


class SkillNotFound(LookupError):
    """Raised when a provider cannot resolve the requested Skill version."""


class SkillProvider(Protocol):
    """Definition for a provider that resolves governed Skill manifests."""

    provider_id: str

    async def resolve(self, request: SkillResolutionRequest) -> SkillManifest:
        """Resolve one immutable manifest or raise ``SkillNotFound``."""


class ToolProvider(Protocol):
    """Definition for one authorized, provider-neutral tool execution."""

    provider_id: str

    def requested_paths(self, request: ToolExecutionRequest) -> list[str]:
        """Return workspace-root-relative paths selected by the request."""

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        """Execute one request and return its canonical result."""


class SandboxProvider(Protocol):
    """Definition for an isolated, snapshot-bound execution backend."""

    provider_id: str

    async def execute(
        self,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult:
        """Execute one request without exposing the host process boundary."""


class VerifierProvider(Protocol):
    """Definition for an independent verifier that cannot mutate the workspace."""

    provider_id: str

    async def verify(self, request: VerificationRequest) -> VerificationResult:
        """Verify one frozen patch and return a structured verdict."""


class CatalogSkillProvider:
    """Resolve Skills from one validated local catalog."""

    provider_id = "local-catalog"

    def __init__(self, catalog: SkillCatalog) -> None:
        self._catalog = catalog

    async def resolve(self, request: SkillResolutionRequest) -> SkillManifest:
        for skill in self._catalog.skills:
            if skill.name == request.name and (
                request.version is None or skill.version == request.version
            ):
                return skill
        raise SkillNotFound(
            f"Skill {request.name!r}"
            + (f"@{request.version}" if request.version else "")
            + " is unavailable"
        )


class CallableToolProvider:
    """Adapt a local async function to the shared ToolProvider contract."""

    def __init__(
        self,
        provider_id: str,
        handler: Callable[[ToolExecutionRequest], Awaitable[ToolExecutionResult]],
    ) -> None:
        if not provider_id:
            raise ValueError("tool provider id cannot be empty")
        self.provider_id = provider_id
        self._handler = handler

    def requested_paths(self, request: ToolExecutionRequest) -> list[str]:
        return []

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        return await self._handler(request)


class CallableVerifierProvider:
    """Adapt a local async function to the shared VerifierProvider contract."""

    def __init__(
        self,
        provider_id: str,
        handler: Callable[[VerificationRequest], Awaitable[VerificationResult]],
    ) -> None:
        if not provider_id:
            raise ValueError("verifier provider id cannot be empty")
        self.provider_id = provider_id
        self._handler = handler

    async def verify(self, request: VerificationRequest) -> VerificationResult:
        return await self._handler(request)
