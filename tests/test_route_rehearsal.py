from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentloom.cli import app
from agentloom.policy_mcp import (
    POLICY_ALLOW_HOST_TEST_EXECUTION_ENV,
    POLICY_SANDBOX_BACKEND_ENV,
    POLICY_SANDBOX_IMAGE_ENV,
)
from agentloom.route_rehearsal import RouteRehearsalError, ToolRouteRollbackRehearsal

ROUTE_VARIABLES = (
    POLICY_SANDBOX_BACKEND_ENV,
    POLICY_SANDBOX_IMAGE_ENV,
    POLICY_ALLOW_HOST_TEST_EXECUTION_ENV,
)


def route_environment() -> dict[str, str | None]:
    return {name: os.environ.get(name) for name in ROUTE_VARIABLES}


def test_route_rehearsal_uses_actual_factory_and_restores_caller_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(POLICY_SANDBOX_BACKEND_ENV, "caller-backend")
    monkeypatch.setenv(POLICY_SANDBOX_IMAGE_ENV, "caller-image")
    monkeypatch.setenv(POLICY_ALLOW_HOST_TEST_EXECUTION_ENV, "caller-ack")
    caller_environment = route_environment()
    output_root = tmp_path / "route-rehearsal"

    result = ToolRouteRollbackRehearsal().run(output_root)

    assert result.status == "PASS"
    assert result.provider_sequence == [
        "local-test-runner",
        "sandboxed-test-runner/docker-sandbox",
        "local-test-runner",
    ]
    assert result.baseline_config_digest == result.rollback_config_digest
    assert result.caller_environment_restored is True
    assert route_environment() == caller_environment

    evidence_path = output_root / "route-rollback-rehearsal.json"
    evidence_text = evidence_path.read_text(encoding="utf-8")
    assert str(tmp_path) not in evidence_text
    assert "caller-backend" not in evidence_text
    assert "caller-image" not in evidence_text
    assert "caller-ack" not in evidence_text
    assert json.loads(evidence_text) == result.model_dump(by_alias=True, mode="json")


def test_route_rehearsal_restores_caller_environment_on_factory_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(POLICY_SANDBOX_BACKEND_ENV, "before-failure")
    monkeypatch.delenv(POLICY_SANDBOX_IMAGE_ENV, raising=False)
    monkeypatch.setenv(POLICY_ALLOW_HOST_TEST_EXECUTION_ENV, "before-ack")
    caller_environment = route_environment()

    def fail_factory(_workspace: Path, _evidence: Path) -> object:
        raise RuntimeError("synthetic route factory failure")

    monkeypatch.setattr("agentloom.route_rehearsal.tool_provider_from_env", fail_factory)

    with pytest.raises(RouteRehearsalError, match="failed closed"):
        ToolRouteRollbackRehearsal().run(tmp_path / "failure")

    assert route_environment() == caller_environment


def test_route_rehearsal_rejects_unexpected_provider_sequence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class WrongProvider:
        provider_id = "wrong-provider"

    monkeypatch.setattr(
        "agentloom.route_rehearsal.tool_provider_from_env",
        lambda _workspace, _evidence: WrongProvider(),
    )

    with pytest.raises(RouteRehearsalError, match="Provider sequence"):
        ToolRouteRollbackRehearsal().run(tmp_path / "wrong-provider")


def test_route_rehearsal_rejects_symlink_output_without_touching_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    output_root = tmp_path / "linked-output"
    try:
        output_root.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    with pytest.raises(RouteRehearsalError, match="empty directory"):
        ToolRouteRollbackRehearsal().run(output_root)

    assert list(target.iterdir()) == []


def test_route_rehearsal_rejects_occupied_output_without_mutation(tmp_path: Path) -> None:
    caller_environment = route_environment()
    output_root = tmp_path / "occupied"
    output_root.mkdir()
    marker = output_root / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(RouteRehearsalError, match="empty"):
        ToolRouteRollbackRehearsal().run(output_root)

    assert marker.read_text(encoding="utf-8") == "keep"
    assert route_environment() == caller_environment


def test_rehearse_route_rollback_cli_outputs_redacted_json(tmp_path: Path) -> None:
    output_root = tmp_path / "cli-route"

    result = CliRunner().invoke(
        app,
        ["rehearse-route-rollback", "--output-root", str(output_root)],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "evidenceFile": "route-rollback-rehearsal.json",
        "providerSequence": [
            "local-test-runner",
            "sandboxed-test-runner/docker-sandbox",
            "local-test-runner",
        ],
        "status": "PASS",
    }
    assert str(tmp_path) not in result.output
    assert (output_root / "route-rollback-rehearsal.json").is_file()
