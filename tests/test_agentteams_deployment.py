from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "agentteams"


def load_resource(name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((DEPLOY / "resources" / name).read_text(encoding="utf-8")),
    )


def test_agentteams_version_lock_is_immutable_and_pinned() -> None:
    lock = json.loads((DEPLOY / "version-lock.json").read_text(encoding="utf-8"))

    assert lock["upstream"]["tag"] == "v1.1.2"
    assert lock["upstream"]["commit"] == "a99457830fafb99c991bdb666aa8a1eef2f83b12"
    assert lock["images"]["controller"]["digest"].startswith("sha256:")
    assert lock["images"]["manager_copaw"]["digest"].startswith("sha256:")


def test_resources_define_four_distinct_agent_identities() -> None:
    manager = load_resource("manager.json")
    team = load_resource("team.json")

    assert manager["apiVersion"] == team["apiVersion"] == "hiclaw.io/v1beta1"
    assert manager["kind"] == "Manager"
    assert manager["metadata"]["name"] == "default"
    assert manager["spec"]["runtime"] == "copaw"

    assert team["kind"] == "Team"
    assert team["metadata"]["name"] == "agentloom-repair"
    assert team["spec"]["leader"]["name"] == "agentloom-investigator"
    assert [worker["name"] for worker in team["spec"]["workers"]] == [
        "agentloom-implementer",
        "agentloom-verifier",
    ]

    identities = {
        manager["metadata"]["name"],
        team["spec"]["leader"]["name"],
        *(worker["name"] for worker in team["spec"]["workers"]),
    }
    assert len(identities) == 4


def test_human_has_team_scoped_access() -> None:
    human = load_resource("human.json")

    assert human["apiVersion"] == "hiclaw.io/v1beta1"
    assert human["kind"] == "Human"
    assert human["metadata"]["name"] == "agentloom-developer"
    assert human["spec"]["permissionLevel"] == 2
    assert human["spec"]["accessibleTeams"] == ["agentloom-repair"]


def test_resources_do_not_embed_secrets() -> None:
    resource_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((DEPLOY / "resources").glob("*.json"))
    ).lower()

    forbidden = ("api_key", "apikey", "password", "secret", "token", "sk-")
    assert not any(term in resource_text for term in forbidden)


def test_deployment_script_fails_closed_and_redacts_human_password() -> None:
    script = (DEPLOY / "deploy.ps1").read_text(encoding="utf-8")

    assert '$dockerArguments = @("exec", $ControllerContainer, "hiclaw") + $Arguments' in script
    assert "Invoke-Docker -Arguments $dockerArguments" in script
    assert "Assert-ImageDigest" in script
    assert 'manager.phase -eq "Running"' in script
    assert 'team.phase -eq "Active"' in script
    assert "workers.total -eq 3" in script
    assert 'human.phase -eq "Active"' in script
    assert "$validHumanRooms -contains $team.teamRoomID" in script
    assert "Wait-AgentTeamCoreReady" in script
    assert "Test-HumanExists" in script
    assert "Human updates are not supported by AgentTeams v1.1.2" in script
    assert "initialPassword" not in script


def test_cloud_provider_script_reads_secret_from_environment_and_redacts_output() -> None:
    script = (DEPLOY / "configure-provider.ps1").read_text(encoding="utf-8")

    assert 'ApiKeyEnvironmentVariable = "QWEN_API_KEY"' in script
    assert "GetEnvironmentVariable" in script
    assert "docker port" in script
    assert "/api/models/dashscope/config" in script
    assert "/api/models/dashscope/models" in script
    assert "/api/models/active" in script
    assert "qwen3.7-plus" in script
    assert "apiKey" not in script
    assert "sk-" not in script


def test_e2e_script_requires_role_owned_exact_line_markers() -> None:
    script = (DEPLOY / "e2e.ps1").read_text(encoding="utf-8")

    assert "Test-ExactMarker" in script
    assert "$event.sender -eq $ExpectedSender" in script
    assert "$event.origin_server_ts -lt $StartedAtMilliseconds" in script
    assert "$lines -contains $Marker" in script
    assert "IMPLEMENTER_DONE" in script
    assert "VERIFIER_DONE" in script
    assert "INVESTIGATOR_DONE" in script
    assert "MANAGER_DONE" in script
    assert "E2E_PASS" in script
    assert "initialPassword" not in script
    assert "authToken" in script
    assert "Write-Output $authToken" not in script
