from datetime import UTC, datetime, timedelta

import pytest

from agentloom.contracts import SkillExecutionGrant
from agentloom.policy import InMemoryNonceStore, PolicyDenied, SkillGrantAuthorizer


def make_grant(**overrides: object) -> SkillExecutionGrant:
    issued_at = datetime.now(UTC)
    values: dict[str, object] = {
        "grant_id": "grant-01",
        "task_id": "task-01",
        "step_id": "implement-01",
        "agent_name": "agentloom-implementer",
        "skill_name": "test-driven-development",
        "skill_version": "1.0.0",
        "tool_name": "test-runner",
        "action": "process.exec:test",
        "parameter_digest": "b" * 64,
        "risk_level": "L1",
        "nonce": "nonce-0001",
        "issued_at": issued_at,
        "expires_at": issued_at + timedelta(minutes=5),
    }
    values.update(overrides)
    return SkillExecutionGrant.model_validate(values)


def make_authorizer() -> SkillGrantAuthorizer:
    return SkillGrantAuthorizer(b"test-signing-key-with-32-bytes!!", InMemoryNonceStore())


def test_valid_grant_is_accepted_once() -> None:
    authorizer = make_authorizer()
    signed = authorizer.sign(make_grant())

    verified = authorizer.verify(signed, parameter_digest="b" * 64)

    assert verified.grant_id == "grant-01"
    with pytest.raises(PolicyDenied, match="grant nonce has already been used"):
        authorizer.verify(signed, parameter_digest="b" * 64)


def test_parameter_digest_must_match_bound_request() -> None:
    authorizer = make_authorizer()
    signed = authorizer.sign(make_grant())

    with pytest.raises(PolicyDenied, match="request parameters do not match grant"):
        authorizer.verify(signed, parameter_digest="c" * 64)


def test_tampered_grant_is_rejected() -> None:
    authorizer = make_authorizer()
    signed = authorizer.sign(make_grant())
    tampered = signed.model_copy(
        update={"grant": signed.grant.model_copy(update={"action": "process.exec:shell"})}
    )

    with pytest.raises(PolicyDenied, match="grant signature is invalid"):
        authorizer.verify(tampered, parameter_digest="b" * 64)


def test_expired_grant_is_rejected() -> None:
    authorizer = make_authorizer()
    issued_at = datetime.now(UTC) - timedelta(minutes=10)
    signed = authorizer.sign(
        make_grant(
            issued_at=issued_at,
            expires_at=issued_at + timedelta(minutes=5),
        )
    )

    with pytest.raises(PolicyDenied, match="grant has expired"):
        authorizer.verify(signed, parameter_digest="b" * 64)


def test_l2_grant_requires_approval_reference() -> None:
    authorizer = make_authorizer()

    with pytest.raises(PolicyDenied, match="L2/L3 grants require approval"):
        authorizer.sign(make_grant(risk_level="L2"))
