"""Skill-bound authorization for the Policy Broker."""

import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from threading import Lock
from typing import Protocol

from agentloom.capabilities import SkillNotFound, SkillProvider
from agentloom.contracts import (
    AgentIdentity,
    ApprovalRecord,
    GrantIssuanceRequest,
    SignedSkillExecutionGrant,
    SkillExecutionGrant,
    SkillManifest,
    SkillResolutionRequest,
    TaskRecord,
)


class PolicyDenied(Exception):
    """Raised when a tool call fails a Policy Broker check."""

    code = "POLICY_DENIED"


class NonceStore(Protocol):
    """Atomically consume one opaque Grant nonce."""

    def consume(self, nonce: str) -> bool:
        """Return false when the nonce was already consumed."""

        ...


class InMemoryNonceStore:
    """Atomic replay guard for the single-process initial deployment."""

    def __init__(self) -> None:
        self._consumed: set[str] = set()
        self._lock = Lock()

    def consume(self, nonce: str) -> bool:
        with self._lock:
            if nonce in self._consumed:
                return False
            self._consumed.add(nonce)
            return True


class TrustedGrantIssuer:
    """Derive short-lived Grants from authoritative task, Skill, and identity data."""

    def __init__(
        self,
        authorizer: "SkillGrantAuthorizer",
        *,
        skill_provider: SkillProvider,
        task_lookup: Callable[[str], TaskRecord | None],
        consumer_agents: Mapping[str, AgentIdentity],
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._authorizer = authorizer
        self._skill_provider = skill_provider
        self._task_lookup = task_lookup
        self._consumer_agents = dict(consumer_agents)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._token_factory = token_factory or (lambda: secrets.token_hex(16))

    async def issue(
        self,
        request: GrantIssuanceRequest,
        *,
        trusted_consumer: str | None,
    ) -> SignedSkillExecutionGrant:
        if trusted_consumer is None:
            raise PolicyDenied("trusted gateway consumer is required")
        agent = self._consumer_agents.get(trusted_consumer)
        if agent is None:
            raise PolicyDenied("consumer is not authorized to request Grants")
        task = self._task_lookup(request.task_id)
        if task is None:
            raise PolicyDenied("task is unavailable")
        if task.status != "VERIFYING":
            raise PolicyDenied("task is not in VERIFYING")

        resolution = SkillResolutionRequest(
            name=request.skill_name,
            version=request.skill_version,
        )
        try:
            manifest = await self._skill_provider.resolve(resolution)
        except SkillNotFound as error:
            raise PolicyDenied("Skill could not be resolved") from error
        if manifest.source is None or manifest.risk_level is None:
            raise PolicyDenied("Skill governance metadata is unavailable")

        issued_at = self._clock()
        grant_token = self._token_factory()
        nonce = self._token_factory()
        grant = SkillExecutionGrant(
            grant_id=f"grant-{grant_token}",
            task_id=request.task_id,
            step_id=request.step_id,
            agent_name=agent.name,
            skill_name=manifest.name,
            skill_version=manifest.version,
            skill_content_hash=manifest.source.content_hash,
            tool_name=request.tool_name,
            action=request.action,
            parameter_digest=request.parameter_digest,
            authorized_paths=request.requested_paths,
            risk_level=manifest.risk_level,
            nonce=nonce,
            issued_at=issued_at,
            expires_at=issued_at + timedelta(minutes=5),
        )
        return await self._authorizer.issue_from_provider(
            grant,
            provider=self._skill_provider,
            request=resolution,
            agent=agent,
            requested_paths=request.requested_paths,
            task_allowed_paths=task.allowed_paths,
        )


class SkillGrantAuthorizer:
    def __init__(
        self,
        signing_key: bytes,
        nonce_store: NonceStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if len(signing_key) < 32:
            raise ValueError("signing key must contain at least 32 bytes")
        self._signing_key = signing_key
        self._nonce_store = nonce_store
        self._clock = clock or (lambda: datetime.now(UTC))

    def _sign(self, grant: SkillExecutionGrant) -> SignedSkillExecutionGrant:
        return SignedSkillExecutionGrant(
            grant=grant,
            signature=self._signature(grant),
        )

    def issue(
        self,
        grant: SkillExecutionGrant,
        *,
        manifest: SkillManifest,
        agent: AgentIdentity,
        requested_paths: list[str],
        task_allowed_paths: list[str],
        approval: ApprovalRecord | None = None,
        valid_approval_refs: set[str] | None = None,
    ) -> SignedSkillExecutionGrant:
        """Authorize and sign a grant using a trusted Registry manifest."""
        if manifest.lifecycle_state != "PUBLISHED":
            raise PolicyDenied("Skill is not published")
        if manifest.source is None:
            raise PolicyDenied("Published Skill source is unavailable")
        if manifest.name != grant.skill_name or manifest.version != grant.skill_version:
            raise PolicyDenied("Grant does not match the published Skill version")
        if grant.skill_content_hash != manifest.source.content_hash:
            raise PolicyDenied("Grant does not match the published Skill content")
        if grant.authorized_paths != requested_paths:
            raise PolicyDenied("Grant paths do not match the authorized request")
        if agent.name != grant.agent_name or grant.agent_name not in (
            manifest.compatible_agents or []
        ):
            raise PolicyDenied("Agent is not compatible with the Skill")
        if not set(manifest.permissions).issubset(agent.capabilities):
            raise PolicyDenied("Agent capabilities do not satisfy Skill permissions")
        tool_action = f"{grant.tool_name}:{grant.action}"
        if tool_action not in (manifest.allowed_tools or []):
            raise PolicyDenied("Tool action is not allowed by the Skill")
        if self._risk_rank(grant.risk_level) < self._risk_rank(manifest.risk_level):
            raise PolicyDenied("Grant risk level understates the Skill risk")
        now = self._clock()
        if now < grant.issued_at or now >= grant.expires_at:
            raise PolicyDenied("Grant validity window is not current")
        for requested_path in requested_paths:
            if not self._path_allowed(requested_path, manifest.allowed_paths or []):
                raise PolicyDenied("Requested path is not allowed by the Skill")
            if not self._path_allowed(requested_path, task_allowed_paths):
                raise PolicyDenied("Requested path is not allowed by the task")
        if grant.risk_level == "L3":
            raise PolicyDenied("L3 action execution is disabled in the competition runtime")
        if grant.risk_level == "L2" and not self._approval_matches(grant, approval, now):
            raise PolicyDenied("L2 grant approval is not valid")
        if valid_approval_refs:
            raise PolicyDenied("approval references must be represented by an ApprovalRecord")
        return self._sign(grant)

    async def issue_from_provider(
        self,
        grant: SkillExecutionGrant,
        *,
        provider: SkillProvider,
        request: SkillResolutionRequest,
        agent: AgentIdentity,
        requested_paths: list[str],
        task_allowed_paths: list[str],
        approval: ApprovalRecord | None = None,
        valid_approval_refs: set[str] | None = None,
    ) -> SignedSkillExecutionGrant:
        """Resolve a Skill through a provider, then apply the normal policy checks."""
        try:
            manifest = await provider.resolve(request)
        except SkillNotFound as error:
            version = f"@{request.version}" if request.version else ""
            raise PolicyDenied(
                f"Skill could not be resolved: {request.name}{version}"
            ) from error
        return self.issue(
            grant,
            manifest=manifest,
            agent=agent,
            requested_paths=requested_paths,
            task_allowed_paths=task_allowed_paths,
            approval=approval,
            valid_approval_refs=valid_approval_refs,
        )

    def verify(
        self,
        signed_grant: SignedSkillExecutionGrant,
        *,
        parameter_digest: str,
        requested_paths: list[str] | None = None,
    ) -> SkillExecutionGrant:
        grant = signed_grant.grant
        expected_signature = self._signature(grant)
        if not hmac.compare_digest(signed_grant.signature, expected_signature):
            raise PolicyDenied("grant signature is invalid")
        if self._clock() >= grant.expires_at:
            raise PolicyDenied("grant has expired")
        if not hmac.compare_digest(parameter_digest, grant.parameter_digest):
            raise PolicyDenied("request parameters do not match grant")
        if requested_paths is not None:
            for requested_path in requested_paths:
                if not self._path_allowed(requested_path, grant.authorized_paths):
                    raise PolicyDenied("request path is not authorized by grant")
        if not self._nonce_store.consume(grant.nonce):
            raise PolicyDenied("grant nonce has already been used")
        return grant

    def _signature(self, grant: SkillExecutionGrant) -> str:
        payload = json.dumps(
            grant.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hmac.new(self._signing_key, payload, hashlib.sha256).hexdigest()

    @staticmethod
    def _path_allowed(path: str, patterns: list[str]) -> bool:
        normalized = path.replace("\\", "/")
        parsed = PurePosixPath(normalized)
        if parsed.is_absolute() or ".." in parsed.parts:
            return False
        return any(fnmatchcase(normalized, pattern.replace("\\", "/")) for pattern in patterns)

    @staticmethod
    def _risk_rank(risk_level: str | None) -> int:
        if risk_level is None:
            return 4
        return {"L0": 0, "L1": 1, "L2": 2, "L3": 3}[risk_level]

    @staticmethod
    def _approval_matches(
        grant: SkillExecutionGrant,
        approval: ApprovalRecord | None,
        now: datetime,
    ) -> bool:
        return bool(
            approval
            and grant.approval_ref
            and grant.route_id
            and grant.rollback_plan_hash
            and approval.status == "APPROVED"
            and approval.approval_id == grant.approval_ref
            and approval.task_id == grant.task_id
            and approval.grant_id == grant.grant_id
            and approval.parameter_digest == grant.parameter_digest
            and approval.risk_level == "L2"
            and approval.route_id == grant.route_id
            and approval.rollback_plan_hash == grant.rollback_plan_hash
            and now < approval.expires_at
        )
