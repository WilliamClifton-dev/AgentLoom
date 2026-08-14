"""Model-free rehearsal of Policy Broker Tool Provider route rollback."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from threading import Lock
from typing import Literal

from pydantic import Field

from agentloom.contracts import ContractModel
from agentloom.policy_mcp import (
    POLICY_ALLOW_HOST_TEST_EXECUTION_ENV,
    POLICY_SANDBOX_BACKEND_ENV,
    POLICY_SANDBOX_IMAGE_ENV,
    tool_provider_from_env,
)

_ROUTE_VARIABLES = (
    POLICY_SANDBOX_BACKEND_ENV,
    POLICY_SANDBOX_IMAGE_ENV,
    POLICY_ALLOW_HOST_TEST_EXECUTION_ENV,
)
_SYNTHETIC_IMAGE = "sha256:" + "d" * 64
_EXPECTED_PROVIDER_SEQUENCE = [
    "local-test-runner",
    "sandboxed-test-runner/docker-sandbox",
    "local-test-runner",
]
_ENVIRONMENT_LOCK = Lock()


class RouteRehearsalError(Exception):
    """Raised when route switching or rollback cannot be proven."""


class RouteRollbackRehearsalResult(ContractModel):
    schema_version: Literal["agentloom.route-rollback-rehearsal/v1alpha1"] = Field(
        default="agentloom.route-rollback-rehearsal/v1alpha1",
        alias="schemaVersion",
    )
    status: Literal["PASS"] = "PASS"
    provider_sequence: list[str] = Field(alias="providerSequence", min_length=3, max_length=3)
    baseline_config_digest: str = Field(
        alias="baselineConfigDigest", pattern=r"^[a-f0-9]{64}$"
    )
    rollback_config_digest: str = Field(
        alias="rollbackConfigDigest", pattern=r"^[a-f0-9]{64}$"
    )
    caller_environment_restored: bool = Field(alias="callerEnvironmentRestored")


class ToolRouteRollbackRehearsal:
    """Switch the actual Provider factory and restore all route environment state."""

    def run(self, output_root: Path) -> RouteRollbackRehearsalResult:
        if output_root.is_symlink():
            raise RouteRehearsalError("output root must be an empty directory")
        root = output_root.resolve()
        self._prepare_empty_output(root)
        workspace = root / "workspace"
        workspace.mkdir()
        evidence_root = root / "tool-evidence"

        with _ENVIRONMENT_LOCK:
            caller_environment = self._snapshot()
            route_error: Exception | None = None
            provider_sequence: list[str] = []
            baseline_digest = ""
            rollback_digest = ""
            try:
                self._apply_local_route()
                baseline_environment = self._snapshot()
                baseline_digest = self._digest(baseline_environment)
                provider_sequence.append(
                    tool_provider_from_env(workspace, evidence_root).provider_id
                )

                self._apply_docker_route()
                provider_sequence.append(
                    tool_provider_from_env(workspace, evidence_root).provider_id
                )

                self._restore(baseline_environment)
                rollback_digest = self._digest(self._snapshot())
                provider_sequence.append(
                    tool_provider_from_env(workspace, evidence_root).provider_id
                )
            except Exception as exc:
                route_error = exc
            finally:
                self._restore(caller_environment)

            caller_restored = self._snapshot() == caller_environment
            if not caller_restored:
                raise RouteRehearsalError("caller route environment was not restored")
            if route_error is not None:
                raise RouteRehearsalError("route rehearsal failed closed") from route_error
            if baseline_digest != rollback_digest:
                raise RouteRehearsalError("route rollback configuration digest changed")
            if provider_sequence != _EXPECTED_PROVIDER_SEQUENCE:
                raise RouteRehearsalError("route Provider sequence is invalid")

            result = RouteRollbackRehearsalResult(
                provider_sequence=provider_sequence,
                baseline_config_digest=baseline_digest,
                rollback_config_digest=rollback_digest,
                caller_environment_restored=caller_restored,
            )
            (root / "route-rollback-rehearsal.json").write_text(
                result.model_dump_json(by_alias=True, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            return result

    @staticmethod
    def _prepare_empty_output(root: Path) -> None:
        if root.exists():
            if not root.is_dir() or any(root.iterdir()):
                raise RouteRehearsalError("output root must be empty")
            return
        root.mkdir(parents=True)

    @staticmethod
    def _snapshot() -> dict[str, str | None]:
        return {name: os.environ.get(name) for name in _ROUTE_VARIABLES}

    @staticmethod
    def _restore(snapshot: dict[str, str | None]) -> None:
        for name, value in snapshot.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    @staticmethod
    def _apply_local_route() -> None:
        os.environ[POLICY_SANDBOX_BACKEND_ENV] = "local-development"
        os.environ[POLICY_ALLOW_HOST_TEST_EXECUTION_ENV] = "true"
        os.environ.pop(POLICY_SANDBOX_IMAGE_ENV, None)

    @staticmethod
    def _apply_docker_route() -> None:
        os.environ[POLICY_SANDBOX_BACKEND_ENV] = "docker"
        os.environ[POLICY_SANDBOX_IMAGE_ENV] = _SYNTHETIC_IMAGE
        os.environ.pop(POLICY_ALLOW_HOST_TEST_EXECUTION_ENV, None)

    @staticmethod
    def _digest(snapshot: dict[str, str | None]) -> str:
        encoded = json.dumps(snapshot, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()
