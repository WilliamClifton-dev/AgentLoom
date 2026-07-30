"""Skill-bound authorization for the Policy Broker."""

import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock

from agentloom.contracts import SignedSkillExecutionGrant, SkillExecutionGrant


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

    def sign(self, grant: SkillExecutionGrant) -> SignedSkillExecutionGrant:
        if grant.risk_level in {"L2", "L3"} and not grant.approval_ref:
            raise PolicyDenied("L2/L3 grants require approval")
        return SignedSkillExecutionGrant(
            grant=grant,
            signature=self._signature(grant),
        )

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
