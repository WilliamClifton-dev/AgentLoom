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
    assert "Wait-CoPawApiReady" in script
    assert "GetEnvironmentVariable" in script
    assert "docker port" in script
    assert "/api/models/dashscope/config" in script
    assert "/api/models/dashscope/models" in script
    assert "/api/models/active" in script
    assert "qwen3.7-plus" in script
    assert "apiKey" not in script
    assert "sk-" not in script


def test_deepseek_provider_script_is_bounded_and_redacts_credentials() -> None:
    script = (DEPLOY / "configure-deepseek-provider.ps1").read_text(encoding="utf-8")

    assert 'ApiKeyEnvironmentVariable = "DEEPSEEK_API_KEY"' in script
    assert "Wait-CoPawApiReady" in script
    assert '$ProviderId = "deepseek"' in script
    assert '[ValidateSet("deepseek-v4-flash", "deepseek-v4-pro")]' in script
    assert '[string]$Model = "deepseek-v4-flash"' in script
    assert '$Model = "deepseek-chat"' not in script
    assert '$BaseUrl = "https://api.deepseek.com/v1"' in script
    assert "[string]$ApiKeyEnvironmentVariable" not in script
    assert "[string]$BaseUrl" not in script
    assert "GetEnvironmentVariable" in script
    assert "/api/models/custom-providers" in script
    assert "/api/models/$ProviderId/config" in script
    assert "/api/models/$ProviderId/models" in script
    assert "/api/models/active" in script
    assert "/api/models/$ProviderId/models/test" in script
    assert "apiKey" not in script
    assert "sk-" not in script


def test_stepfun_provider_script_is_bounded_and_redacts_credentials() -> None:
    script = (DEPLOY / "configure-stepfun-provider.ps1").read_text(encoding="utf-8")

    assert 'ApiKeyEnvironmentVariable = "STEPFUN_API_KEY"' in script
    assert '$ProviderId = "stepfun"' in script
    assert '[string]$Model = "step-3.7-flash"' in script
    assert '$BaseUrl = "https://api.stepfun.com/step_plan/v1"' in script
    assert 'reasoning_effort = "low"' in script
    assert "/api/models/custom-providers" in script
    assert "/api/models/$ProviderId/config" in script
    assert "/api/models/$ProviderId/models/test" in script
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


def test_live_repair_runner_binds_fresh_role_events_and_task_artifacts() -> None:
    script = (DEPLOY / "run-live-repair.ps1").read_text(encoding="utf-8")

    assert "Test-ExactMarker" in script
    assert "$event.sender -eq $ExpectedSender" in script
    assert "$event.origin_server_ts -lt $StartedAtMilliseconds" in script
    assert "$lines -contains $Marker" in script
    assert "ROOT_CAUSE_REPORT" in script
    assert "IMPLEMENTER_ARTIFACT_DONE" in script
    assert "VERIFIER_ARTIFACT_DONE" in script
    assert script.count('[ValidatePattern("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]') == 2
    assert "[ValidateRange(1, 3600)]" in script
    assert "[ValidateRange(1, 60)]" in script
    assert 'shared/tasks/$TaskId/' in script
    assert '[string]$CaseRoot = ".\\demo\\cases\\pagination-boundary"' in script
    assert "Stage-LiveRepairCase" in script
    assert '"before/lib/__init__.py"' in script
    assert '"before/lib/pagination.py"' in script
    assert '"before/tests/test_pagination.py"' in script
    assert '"base/lib/__init__.py"' in script
    assert '"base/lib/pagination.py"' in script
    assert '"base/tests/test_pagination.py"' in script
    assert '"mc", "cp"' in script
    assert "$initialObjects.Count -eq 0" in script
    assert "lastModified" in script
    assert "[DateTimeOffset]$object.lastModified" in script
    assert "originServerTimestamp" in script
    assert "repair.patch" in script
    assert "live-repair-submission" in script
    assert "[switch]$Resume" in script
    assert "ResumeEvidencePath" in script
    assert 'resumeEvidence.schemaVersion -ne "agentloom.live-repair-run/v1alpha1"' in script
    assert '$resumeEvidence.taskId -ne $TaskId' in script
    assert "-not $resumeEvidence.strict" in script
    assert '@("REJECTED", "TIMEOUT") -notcontains $resumeEvidence.status' in script
    assert "StartedAtIso" not in script
    assert "if (-not $Resume)" in script
    assert "expected/" in script
    assert "hidden" in script
    assert "filesync push" in script
    assert "Never push the whole task directory" in script
    assert "PYTHONDONTWRITEBYTECODE=1" in script
    assert "patch-artifact.json" in script
    assert "resultObjectsMustBeAllowlisted" in script
    assert "inputObjectsRemainUnchanged" in script
    assert script.count("-InputObjects $initialInputObjects") == 9
    assert "foreach ($immutableInput in $initialInputObjects)" in script
    assert "foreach ($input in $initialInputObjects)" not in script
    assert "completionEventMustFollowArtifacts" in script
    assert "allowedFinalKeys" in script
    assert "$MaxArtifactBytes = 131072" in script
    assert "$object.size -gt $MaxArtifactBytes" in script
    assert script.count('"rmdir", $containerTempRoot') == 2
    assert "[DateTimeOffset]::MinValue" in script
    assert "[DateTimeOffset]::MaxValue" not in script
    assert "initialPassword" not in script
    assert "Write-Output $authToken" not in script


def test_live_rollback_runner_is_paid_guarded_and_collects_role_owned_events() -> None:
    script = (DEPLOY / "run-live-rollback.ps1").read_text(encoding="utf-8")

    assert "[switch]$ConfirmPaidRun" in script
    assert "if (-not $ConfirmPaidRun)" in script
    assert "Test-ExactMarker" in script
    assert "$event.sender -eq $ExpectedSender" in script
    assert "VERIFICATION_FAILED" in script
    assert "ROLLBACK_REQUESTED" in script
    assert "ROLLBACK_EXECUTED" in script
    assert "ROLLBACK_VERIFIED" in script
    assert "agentloom.live-rollback-submission/v1alpha1" in script
    assert "failedPatchSha256" in script
    assert "bindingSha256" in script
    assert "$bindingSha256" in script
    assert "RESTORE_APPROVED_SNAPSHOT" in script
    assert "originServerTimestamp" in script
    assert "$manager.roomID" in script
    assert "joined_rooms" in script
    assert "[string[]]$RoomIds" in script
    assert "$roomIds = @(\n    $manager.roomID,\n    $investigator.roomID," in script
    assert "$failureEvents = Wait-StrictMarkers" in script
    assert "Continue the existing workflow after the Verifier failure event" in script
    assert script.index("$failureEvents = Wait-StrictMarkers") < script.index(
        "Continue the existing workflow after the Verifier failure event"
    )
    assert "[int]$ReminderAfterSeconds" in script
    assert "[scriptblock]$OnReminder" in script
    assert "$reminderSent = $false" in script
    assert "-not $reminderSent -and" in script
    assert "$implementerEvents = Wait-StrictMarkers" in script
    assert "-OnReminder $implementerReminder" in script
    assert "The shared task directory is not required" in script
    assert "$verifierContinuationPrompt" in script
    assert script.index("$implementerEvents = Wait-StrictMarkers") < script.index(
        "$verifierContinuationPrompt"
    )
    assert "$verifierEvents = Wait-StrictMarkers" in script
    assert "$finalRequirements" not in script
    assert "/api/models/active" in script
    assert "$active.active_llm.provider_id" in script
    assert "$active.active_llm.model" in script
    assert "active provider/model does not match" in script
    assert "catch {\n                break\n            }" not in script
    assert "$adminMatrixUserId -ne $manager.matrixUserID" not in script
    assert "initialPassword" not in script
    assert "Write-Output $authToken" not in script


def test_opspilot_baseline_script_is_serial_and_keeps_incidents_out_of_manager_room() -> None:
    script = (DEPLOY / "run-opspilot-baseline.ps1").read_text(encoding="utf-8")

    assert "create_agents_messages.md" in script
    assert "run_demo_task_message.md" in script
    assert "host.docker.internal:18089" in script
    assert "opspilot-zero-demo-leader" in script
    for worker in (
        "alert-intake",
        "rca-analyst",
        "remediation-planner",
        "recovery-verifier",
    ):
        assert worker in script
    assert "Wait-OpsPilotTeamReady" in script
    assert "Wait-CoPawApiReady" in script
    assert "CompletionReminderSeconds" in script
    assert "completionReminderSent" in script
    assert 'target=room:$($Team.teamRoomID)' in script
    assert "不要发送到 DM" in script
    assert "Send-MatrixText -RoomId $team.teamRoomID" in script
    assert "Send-MatrixText -RoomId $manager.roomID -Text $incident" not in script
    assert "INC-1001" in script
    assert "INC-1002" in script
    assert "INCIDENT_REPORT_COMPLETE" in script
    assert "Assert-ToolTrace" in script
    assert "markerMustBeIndependentTrimmedLine" in script
    assert "不要使用 projectflow、taskflow、filesync 或共享任务目录" in script
    assert "Save-BaselineEvidence" in script
    assert "initialPassword" not in script
    assert "Write-Output $AuthToken" not in script
    assert "token = $login.access_token" in script


def test_l2_approval_demo_requires_a_real_human_event_and_redacts_secrets() -> None:
    script = (DEPLOY / "run-l2-approval-demo.ps1").read_text(encoding="utf-8")

    assert '[ValidateSet("Prepare", "Collect")]' in script
    assert "prepare-l2" in script
    assert "verify-l2" in script
    assert "agentloom.l2-approval-run/v1alpha1" in script
    assert "agentloom.l2-approval-decision/v1alpha1" in script
    assert '$event.sender -ne $state.humanUserId' in script
    assert '$event.origin_server_ts -le $state.requestEvent.originServerTimestamp' in script
    assert '$candidates.Count -ne 1' in script
    assert "deterministic-host" in script
    assert '$allowedMatrixHosts = @("127.0.0.1", "localhost")' in script
    assert "$matrixUri.Port -ne 18080" in script
    assert "$state.databasePath -ne $resolvedDatabasePath" in script
    assert '"--database", $resolvedDatabasePath' in script
    assert "Send-MatrixText" in script
    assert "decision-template-approved.json" in script
    assert "decision-template-rejected.json" in script
    assert "L3" not in script
    assert "initialPassword" not in script
    assert "Write-Output $accessToken" not in script
    assert "grant signature" not in script.lower()
