"""Skill-bound authorization for the Policy Broker."""

import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from threading import Lock

from agentloom.contracts import (
    AgentIdentity,
    SignedSkillExecutionGrant,
    SkillExecutionGrant,
    SkillManifest,
)


class PolicyDenied(Exception):
    """Raised when a tool call fails a Policy Broker check."""

    code = "POLICY_DENIED"


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


class SkillGrantAuthorizer:
    def __init__(
        self,
        signing_key: bytes,
        nonce_store: InMemoryNonceStore,
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
        valid_approval_refs: set[str],
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
        if grant.risk_level in {"L2", "L3"} and grant.approval_ref not in valid_approval_refs:
            raise PolicyDenied("L2/L3 grant approval is not valid")
        return self._sign(grant)

    def verify(
        self,
        signed_grant: SignedSkillExecutionGrant,
        *,
        parameter_digest: str,
    ) -> SkillExecutionGrant:
        grant = signed_grant.grant
        expected_signature = self._signature(grant)
        if not hmac.compare_digest(signed_grant.signature, expected_signature):
            raise PolicyDenied("grant signature is invalid")
        if self._clock() >= grant.expires_at:
            raise PolicyDenied("grant has expired")
        if not hmac.compare_digest(parameter_digest, grant.parameter_digest):
            raise PolicyDenied("request parameters do not match grant")
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
