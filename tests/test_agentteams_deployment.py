from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "agentteams"


def load_resource(name: str) -> dict[str, object]:
    return json.loads((DEPLOY / "resources" / name).read_text(encoding="utf-8"))


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
