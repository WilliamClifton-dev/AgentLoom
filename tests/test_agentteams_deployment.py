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
    assert team["spec"]["humanMembers"] == [
        {"name": "agentloom-developer", "role": "coordinator"}
    ]
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


def test_business_agents_only_receive_the_policy_broker_mcp() -> None:
    manager = load_resource("manager.json")
    team = load_resource("team.json")
    expected = [
        {
            "name": "agentloom-policy-broker",
            "url": (
                "http://aigw-local.hiclaw.io:8080/mcp-servers/"
                "mcp-agentloom-policy-broker"
            ),
            "transport": "http",
        }
    ]

    assert "mcpServers" not in manager["spec"]
    assert team["spec"]["leader"]["mcpServers"] == expected
    for worker in team["spec"]["workers"]:
        assert worker["mcpServers"] == expected


def test_policy_broker_gateway_script_is_fail_closed_and_least_privilege() -> None:
    wrapper = (DEPLOY / "configure-policy-broker-gateway.ps1").read_text(encoding="utf-8")
    runtime = (DEPLOY / "configure-policy-broker-gateway.sh").read_text(encoding="utf-8")

    assert 'ControllerContainer = "hiclaw-controller"' in wrapper
    assert '"exec", "-i", $ControllerContainer, "bash", "-s"' in wrapper
    assert '$runtime = $runtime.Replace("`r`n", "`n")' in wrapper
    assert "RedirectStandardInput = $true" in wrapper
    assert ".StandardInput.Write($StandardInput)" in wrapper
    assert "version-lock.json" in wrapper
    assert "ConvertFrom-Json" in wrapper
    assert "initialPassword" not in wrapper
    assert "Write-Output $signingKey" not in wrapper

    assert 'MCP_SERVER_NAME="mcp-agentloom-policy-broker"' in runtime
    assert 'MCP_URL="http://host.docker.internal:8765/mcp"' in runtime
    assert (
        'GATEWAY_URL="http://aigw-local.hiclaw.io:8080/mcp-servers/'
        '${MCP_SERVER_NAME}"'
    ) in runtime
    assert 'type: "DIRECT_ROUTE"' in runtime
    assert "directRouteConfig" in runtime
    assert 'path: "/mcp"' in runtime
    assert 'transportType: "streamable"' in runtime
    assert "type: mcp-proxy" not in runtime
    assert 'type: "key-auth"' in runtime
    assert "allowedConsumers: []" in runtime
    assert '"worker-agentloom-investigator"' in runtime
    assert '"worker-agentloom-implementer"' in runtime
    assert '"worker-agentloom-verifier"' in runtime
    assert '"manager"' not in runtime
    assert "/v1/consumers/${consumer}" in runtime
    assert "Expected Higress consumer is unavailable" in runtime
    assert "/v1/mcpServer/consumers" in runtime
    assert "api_write DELETE" in runtime
    assert "current_consumer_body" in runtime
    assert "CONSUMER_MAX_ATTEMPTS=10" in runtime
    assert "sleep 2" in runtime
    assert "consumer_allowlist_matches" in runtime
    assert "== ($expected | sort)" in runtime
    assert "quiet_rejection" in runtime
    assert "route_result" in runtime
    assert "upstreamHost" in runtime
    assert 'test "${upstream_host}" = "host.docker.internal"' in runtime
    assert "route resolved to an unexpected upstream host" in runtime
    assert "HICLAW_ADMIN_PASSWORD" in runtime
    assert "set -euo pipefail" in runtime
    assert 'GetEnvironmentVariable("AGENTLOOM_GATEWAY_ASSERTION", "Process")' in wrapper
    assert "X-AgentLoom-Gateway-Assertion" in runtime
    assert 'KUBE_API="https://localhost:18443"' in runtime
    assert 'KUBE_NAMESPACE="higress-system"' in runtime
    assert '"Content-Type: application/json"' in runtime
    assert '--request PUT' in runtime
    assert 'current_ingress="$(curl --insecure' in runtime
    assert 'persisted_ingress="$(curl --insecure' in runtime
    assert ".metadata.annotations" in runtime
    assert "higress.io/enable-header-control" in runtime
    assert "higress.io/request-header-control-update" in runtime
    assert "env.ASSERTION_HEADER" in runtime
    assert "--data-binary @-" in runtime
    assert '--output /dev/null' in runtime
    assert '--arg assertionHeader' not in runtime
    assert 'api_write PUT "/v1/routes/' not in runtime
    assert "gatewayAssertionConfigured" in runtime
    assert "gatewayAssertion:" not in runtime


def test_policy_broker_start_script_uses_process_environment_without_printing_key() -> None:
    script = (DEPLOY / "start-policy-broker.ps1").read_text(encoding="utf-8")

    assert '[Parameter(Mandatory)][string]$SandboxImage' in script
    assert 'ValidatePattern("^(?:sha256:[a-f0-9]{64}|' in script
    assert 'deploy\\sandbox\\fixtures\\passing-workspace' in script
    assert '[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64})$")' in script
    assert "docker image inspect $SandboxImage" in script
    assert 'AGENTLOOM_SANDBOX_BACKEND = "docker"' in script
    assert "AGENTLOOM_SANDBOX_IMAGE = $SandboxImage" in script
    assert 'Remove-Item Env:AGENTLOOM_ALLOW_HOST_TEST_EXECUTION' in script
    assert "AGENTLOOM_ALLOW_HOST_TEST_EXECUTION =" not in script
    assert 'GetEnvironmentVariable("AGENTLOOM_POLICY_SIGNING_KEY", "Process")' in script
    assert "Test-Path -LiteralPath $resolvedWorkspace -PathType Container" in script
    assert "Test-Path -LiteralPath $venvPython -PathType Leaf" in script
    assert 'AGENTLOOM_TOOL_WORKSPACE = $resolvedWorkspace' in script
    assert 'AGENTLOOM_TOOL_EVIDENCE_ROOT = $resolvedEvidenceRoot' in script
    assert 'AGENTLOOM_DATABASE_URL = "sqlite:///$databaseUrlPath"' in script
    assert 'AGENTLOOM_MCP_TRANSPORT = "streamable-http"' in script
    assert 'AGENTLOOM_MCP_HOST = "0.0.0.0"' in script
    assert "AGENTLOOM_MCP_PORT = [string]$Port" in script
    assert 'AGENTLOOM_MCP_PUBLIC_HOST = "host.docker.internal"' in script
    assert 'GetEnvironmentVariable("AGENTLOOM_GATEWAY_ASSERTION", "Process")' in script
    assert 'AGENTLOOM_GATEWAY_ASSERTION = $gatewayAssertion' in script
    assert '"-m", "agentloom.policy_mcp"' in script
    assert "AGENTLOOM_POLICY_SIGNING_KEY =" not in script
    assert "Write-Output $signingKey" not in script
    assert "Write-Host $signingKey" not in script
    assert "Write-Output $gatewayAssertion" not in script
    assert "Write-Host $gatewayAssertion" not in script


def test_sandbox_runner_image_is_pinned_and_hash_locked() -> None:
    sandbox = DEPLOY.parent / "sandbox"
    dockerfile = (sandbox / "Dockerfile").read_text(encoding="utf-8")
    requirements = (sandbox / "requirements.lock").read_text(encoding="utf-8")
    build = (sandbox / "build-runner.ps1").read_text(encoding="utf-8")

    assert (
        "FROM python@sha256:"
        "dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65"
    ) in dockerfile
    assert "python -m pip install --no-cache-dir --require-hashes" in dockerfile
    assert "--only-binary=:all:" in requirements
    assert "pytest==9.1.1" in requirements
    for digest in (
        "f631c04d2c48c52b84d0d0549c99ff3859c98df65b3101406327ecc7d53fbf12",
        "5fc45236b9446107ff2415ce77c807cee2862cb6fac22b8a73826d0693b0980e",
        "e920276dd6813095e9377c0bc5566d94c932c33b27a3e3945d8389c374dd4746",
        "81a9e26dd42fd28a23a2d169d86d7ac03b46e2f8b59ed4698fb4785f946d0176",
        "37a86b45efb9a47a61a36449063e8e18d0cab3161329fc099eb21783169c4f0c",
    ):
        assert f"--hash=sha256:{digest}" in requirements
    assert "docker build --pull=false" in build
    assert "docker image inspect $Tag" in build
    assert '"^sha256:[a-f0-9]{64}$"' in build


def test_sandbox_e2e_runner_uses_production_broker_and_redacts_secrets() -> None:
    script = (DEPLOY / "run-sandbox-e2e.ps1").read_text(encoding="utf-8")

    assert '[Parameter(Mandatory)][string]$SandboxImage' in script
    assert 'ValidatePattern("^(?:sha256:[a-f0-9]{64}|' in script
    assert '"agentloom.sandbox_e2e", "prepare"' in script
    assert '"agentloom.sandbox_e2e", "verify"' in script
    assert '"-SandboxImage", $SandboxImage' in script
    assert 'RandomNumberGenerator]::GetBytes(32)' in script
    assert '"AGENTLOOM_POLICY_SIGNING_KEY"' in script
    assert '"AGENTLOOM_GATEWAY_ASSERTION"' in script
    assert 'SetEnvironmentVariable($name, $null, "Process")' in script
    assert 'hiclaw-worker-agentloom-implementer' in script
    assert 'hiclaw-worker-agentloom-verifier' in script
    assert 'issue_skill_execution_grant' in script
    assert 'execute_governed_tool' in script
    assert 'nonce has already been used' in script
    assert "Write-Output $signingKey" not in script
    assert "Write-Host $signingKey" not in script
    assert "Write-Output $gatewayAssertion" not in script
    assert "Write-Host $gatewayAssertion" not in script


def test_sandbox_e2e_runner_isolates_artifacts_by_task_namespace() -> None:
    script = (DEPLOY / "run-sandbox-e2e.ps1").read_text(encoding="utf-8")

    assert '[ValidatePattern("^task[0-9]+$")]' in script
    assert '[string]$RunNamespace = "task16"' in script
    assert '"$RunNamespace-" + [DateTimeOffset]::UtcNow' in script
    assert '"artifacts\\policy-broker\\$RunNamespace\\$runId"' in script


def test_sandbox_model_e2e_runner_binds_minimax_marker_to_tool_evidence() -> None:
    script = (DEPLOY / "run-sandbox-model-e2e.ps1").read_text(encoding="utf-8")

    assert '[Parameter(Mandatory)][string]$RunRoot' in script
    assert 'configure-minimax-provider.ps1' in script
    assert '"MiniMax-M2.5"' in script
    assert 'hiclaw-worker-agentloom-investigator' in script
    assert 'hiclaw-worker-agentloom-verifier' in script
    assert 'issue_skill_execution_grant' in script
    assert 'execute_governed_tool' in script
    assert "administrator E2E probe" in script
    assert "Send-MatrixText -RoomId $verifier.roomID" in script
    assert "-MentionUserId $verifier.matrixUserID" in script
    assert "-RoomIds @($verifier.roomID)" in script
    assert "Delegate exactly one governed sandbox verification" not in script
    assert "$modelTask.successMarker" in script
    assert 'event.sender -ne $Verifier.matrixUserID' in script
    assert 'event.origin_server_ts -lt $StartedAtMilliseconds' in script
    assert '"agentloom.sandbox_e2e", "verify"' in script
    assert '"--task", "model"' in script
    assert "QWEN_API_KEY" not in script
    assert "DEEPSEEK_API_KEY" not in script
    assert "STEPFUN_API_KEY" not in script
    assert "AGENTLOOM_POLICY_SIGNING_KEY" not in script
    assert "AGENTLOOM_GATEWAY_ASSERTION" not in script
    assert '"signedGrant"' in script
    assert "$signedGrant" not in script
    assert "signedGrant =" not in script


def test_sandbox_model_e2e_runner_supports_strict_investigator_delegation() -> None:
    script = (DEPLOY / "run-sandbox-model-e2e.ps1").read_text(encoding="utf-8")

    assert '[ValidateSet("direct", "delegated")]' in script
    assert '[string]$DispatchMode = "direct"' in script
    assert '[string]$RunNamespace = "task16"' in script
    assert 'if ($DispatchMode -eq "delegated")' in script
    assert 'Send-MatrixText -RoomId $manager.roomID' in script
    assert '-MentionUserId $manager.matrixUserID' in script
    assert 'MANAGER_DELEGATED' in script
    assert '-ExpectedSender $manager.matrixUserID' in script
    assert '-ExpectedMentionUserId $investigator.matrixUserID' in script
    assert '-RoomIds @($investigator.roomID)' in script
    assert '$managerDelegationEvent.originServerTimestamp' in script
    assert '@($ManagerContainer, $investigatorContainer, $verifierContainer)' in script
    assert '$taskEnvelopeEvent = Send-MatrixText -RoomId $investigator.roomID' in script
    assert '-MentionUserId ""' in script
    assert 'MANAGER_DELEGATED $($taskEnvelopeEvent.eventId)' in script
    assert 'Use the shell tool exactly once to run this exact CoPaw dispatch command:' in script
    assert 'copaw channels send' in script
    assert '--target-session "$($investigator.roomID)"' in script
    assert '--target-user "$($investigator.matrixUserID)"' in script
    assert '$managerDispatchBody = @"' in script
    assert '$managerDispatchBodyBase64 = [Convert]::ToBase64String(' in script
    assert "base64 -d" in script
    assert '$investigatorDispatchBodyBase64 = [Convert]::ToBase64String(' in script
    assert '$investigatorDispatchCommand = @"' in script
    assert '--target-session "$($team.teamRoomID)"' in script
    assert '--target-user "$($verifier.matrixUserID)"' in script
    assert script.count('copaw channels send') >= 2
    assert 'Use the shell tool exactly once to run this exact CoPaw dispatch command:' in script
    assert 'Execute the referenced TASK_ENVELOPE now.' in script
    assert "The exact Investigator dispatch command is:\n$investigatorDispatchCommand" in script
    assert 'Do not reply in this Leader Room.' in script
    assert '-RequiredText $taskEnvelopeEvent.eventId' in script
    assert '$redactedEvidence["taskEnvelope"]' in script
    assert 'VERIFIER_DELEGATED' in script
    assert '-ExpectedSender $investigator.matrixUserID' in script
    assert '-ExpectedMentionUserId $verifier.matrixUserID' in script
    assert '-RoomIds @($team.teamRoomID)' in script
    assert '-StartedAtMilliseconds $delegationEvent.originServerTimestamp' in script
    assert 'agentloom.agentteams-sandbox-delegation-e2e/v1alpha1' in script


def test_delegated_model_e2e_timeout_writes_redacted_stage_evidence() -> None:
    script = (DEPLOY / "run-sandbox-model-e2e.ps1").read_text(encoding="utf-8")

    assert '"delegation-timeout-evidence.json"' in script
    assert 'agentloom.agentteams-sandbox-delegation-timeout/v1alpha1' in script
    assert 'taskEnvelopeStaged = $null -ne $taskEnvelopeEvent' in script
    assert 'managerDelegationObserved = $null -ne $managerDelegationEvent' in script
    assert 'investigatorDelegationObserved = $null -ne $delegationEvent' in script
    assert 'verifierMarkerObserved = $null -ne $markerEvent' in script
    assert 'managerDelegation = $managerDelegationEvent' in script
    assert 'delegation = $delegationEvent' in script


def test_minimax_provider_script_is_bounded_and_redacts_credentials() -> None:
    script = (DEPLOY / "configure-minimax-provider.ps1").read_text(encoding="utf-8")

    assert 'ApiKeyEnvironmentVariable = "MINIMAX_API_KEY"' in script
    assert '$ProviderId = "minimax-cn"' in script
    assert '$ProviderName = "MiniMax China"' in script
    assert '[string]$Model = "MiniMax-M2.5"' in script
    assert '$BaseUrl = "https://api.minimaxi.com/v1"' in script
    assert "https://api.minimax.io" not in script
    assert "[string]$ApiKeyEnvironmentVariable" not in script
    assert "[string]$BaseUrl" not in script
    assert "Wait-CoPawApiReady" in script
    assert '$portBindings = & docker port $Container "$containerPort/tcp" 2>&1' in script
    assert '$dockerExitCode = $LASTEXITCODE' in script
    assert '$binding = $portBindings | Select-Object -First 1' in script
    assert "/api/models/custom-providers" in script
    assert "/api/models/$ProviderId/config" in script
    assert "/api/models/$ProviderId/models/test" in script
    assert "hiclaw-manager" in script
    assert "hiclaw-worker-agentloom-investigator" in script
    assert "hiclaw-worker-agentloom-implementer" in script
    assert "hiclaw-worker-agentloom-verifier" in script
    assert "apiKey" not in script
    assert "sk-" not in script


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


def test_deployment_patches_v112_team_human_members_and_verifies_result() -> None:
    script = (DEPLOY / "deploy.ps1").read_text(encoding="utf-8")

    assert "function Set-TeamHumanMembersCompatibilityPatch" in script
    assert '"Content-Type: application/merge-patch+json"' in script
    assert '"Authorization: Bearer $token"' in script
    assert '"/data/hiclaw-controller/pki/token.csv"' in script
    assert 'spec = [ordered]@{ humanMembers = @($HumanMembers) }' in script
    assert '$patchScript = $patchScript.Replace("`r`n", "`n")' in script
    assert 'Set-TeamHumanMembersCompatibilityPatch `' in script
    assert '-HumanMembers @($resource.spec.humanMembers)' in script
    assert 'Team humanMembers compatibility patch was not persisted' in script
    assert "Remove-Item -LiteralPath $localPatchPath" in script
    assert "Write-Output $token" not in script


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
    assert '[Parameter(Mandatory)][string]$CaseRoot' in script
    assert "Stage-LiveRepairCase" in script
    assert "$caseContext.sourceFiles" in script
    assert '"before/" + [string]$_.sourcePath' in script
    assert "[string]$_.objectName" in script
    assert '"mc", "cp"' in script
    assert "mc cp" in script
    assert "New-CoPawSendCommand" in script
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
    assert '(^|/)(expected|hidden[^/]*)/' in script
    assert "filesync" not in script
    assert "Worker-local pytest is unavailable" in script
    assert "patch-artifact.json" in script
    assert "resultObjectsMustBeAllowlisted" in script
    assert "inputObjectsRemainUnchanged" in script
    assert script.count("-InputObjects $initialInputObjects") == 9
    assert "foreach ($immutableInput in $initialInputObjects)" in script
    assert "foreach ($input in $initialInputObjects)" not in script
    assert "completionEventMustFollowArtifacts" in script
    assert "coordinationEventsMustMatchMentions" in script
    assert "MANAGER_DELEGATED" in script
    assert "IMPLEMENTER_ASSIGNED" in script
    assert "VERIFIER_ASSIGNED" in script
    assert "mentionedUserId" in script
    assert '"m.mentions"' in script
    assert "$event.content.\"m.mentions\".user_ids -contains $ExpectedMentionUserId" in script
    assert "Send-MatrixText -RoomId $manager.roomID" in script
    assert "coordinationTrace" in script
    assert "allowedFinalKeys" in script
    assert "$MaxArtifactBytes = 131072" in script
    assert "$object.size -gt $MaxArtifactBytes" in script
    assert script.count('"rmdir", $containerTempRoot') == 2
    assert "[DateTimeOffset]::MinValue" in script
    assert "[DateTimeOffset]::MaxValue" not in script
    assert "initialPassword" not in script
    assert "Write-Output $authToken" not in script


def test_live_repair_runner_reserves_time_for_every_stage_and_sends_one_reminder() -> None:
    script = (DEPLOY / "run-live-repair.ps1").read_text(encoding="utf-8")

    assert "$runDeadline =" in script
    assert "function Get-StageDeadline" in script
    assert "[ValidateRange(1, 3)][int]$RemainingStages" in script
    assert "[Parameter(Mandatory)][DateTimeOffset]$Deadline" in script
    assert "[ValidateRange(0, 3600)][int]$ReminderAfterSeconds = 0" in script
    assert "[scriptblock]$OnReminder = $null" in script
    assert "$reminderSent = $false" in script
    assert "-not $reminderSent -and" in script
    assert "-Deadline (Get-StageDeadline -RemainingStages 3)" in script
    assert "-Deadline (Get-StageDeadline -RemainingStages 2)" in script
    assert "-Deadline (Get-StageDeadline -RemainingStages 1)" in script
    assert "-OnReminder $investigatorReminder" in script
    assert "-OnReminder $implementerReminder" in script
    assert "-OnReminder $verifierReminder" in script
    assert "while ([DateTimeOffset]::UtcNow -lt $deadline)" not in script


def test_live_repair_stage_continuations_are_reactivated_through_manager() -> None:
    script = (DEPLOY / "run-live-repair.ps1").read_text(encoding="utf-8")

    assert "[$TaskId] IMPLEMENTATION_ENVELOPE" not in script
    assert "[$TaskId] VERIFICATION_ENVELOPE" not in script
    assert "$implementerTransitionEvent = Send-MatrixText" not in script
    assert "$verifierTransitionEvent = Send-MatrixText" not in script
    assert "$implementerInvestigatorDispatchCommand = New-CoPawSendCommand" in script
    assert "$verifierInvestigatorDispatchCommand = New-CoPawSendCommand" in script
    assert "$implementerManagerPrompt = @\"" in script
    assert "$verifierManagerPrompt = @\"" in script
    assert script.count("Send-MatrixText -RoomId $manager.roomID") >= 3
    assert "-Text $implementerManagerPrompt" in script
    assert "-Text $verifierManagerPrompt" in script
    assert "-MentionUserId $manager.matrixUserID -AuthToken $authToken" in script


def test_live_repair_manager_reactivates_each_single_purpose_handoff() -> None:
    script = (DEPLOY / "run-live-repair.ps1").read_text(encoding="utf-8")

    assert "$implementerInvestigatorPrompt = @\"" in script
    assert "$verifierInvestigatorPrompt = @\"" in script
    assert "Run only the exact CoPaw dispatch command below" in script
    conflicting_instruction = (
        "Do not inspect code, copy artifacts, or delegate to another Worker yourself"
    )
    assert conflicting_instruction not in script
    assert "IMPLEMENTER_DISPATCH_COMMAND_PLACEHOLDER" not in script
    assert "VERIFIER_DISPATCH_COMMAND_PLACEHOLDER" not in script
    verifier_requirement = script[script.index('key = "verifier-assigned"') :]
    verifier_requirement = verifier_requirement[: verifier_requirement.index("},")]
    assert 'agentName = "agentloom-investigator"' in verifier_requirement
    assert "sender = $investigator.matrixUserID" in verifier_requirement


def test_live_repair_investigator_reminder_reactivates_through_manager() -> None:
    script = (DEPLOY / "run-live-repair.ps1").read_text(encoding="utf-8")
    reminder = script[script.index("$investigatorReminder = {") :]
    reminder = reminder[: reminder.index("Wait-ForRequiredMarkers")]

    assert "Send-MatrixText -RoomId $manager.roomID" in reminder
    assert "-Text $investigatorManagerReminder" in reminder
    assert "-Text $prompt" not in reminder
    assert "Send-MatrixText -RoomId $investigator.roomID" not in reminder
    assert "$investigatorCompletionDispatchCommand" in script
    assert "Confirm that root-cause-report.json is already uploaded" in script


def test_live_repair_assignments_emit_matrix_mentions_for_the_target_role() -> None:
    script = (DEPLOY / "run-live-repair.ps1").read_text(encoding="utf-8")

    implementer_assignment = (
        '$implementerBody = @"\n$($implementer.matrixUserID)\n'
        "[$TaskId] IMPLEMENTER_ASSIGNED"
    )
    assert implementer_assignment in script
    assert '$verifierBody = @"\n$($verifier.matrixUserID)\n[$TaskId] VERIFIER_ASSIGNED' in script


def test_live_repair_stages_assignments_as_immutable_input_objects() -> None:
    script = (DEPLOY / "run-live-repair.ps1").read_text(encoding="utf-8")

    assert "function Stage-AssignmentObject" in script
    assert '"assignments/implementer.txt"' in script
    assert '"assignments/verifier.txt"' in script
    assert script.count("Stage-AssignmentObject -TaskPrefix $taskPrefix") == 2
    assert '-ObjectName "assignments/implementer.txt" -Text $implementerBody' in script
    assert '-ObjectName "assignments/verifier.txt" -Text $verifierBody' in script
    assert "$expectedInitial" in script
    assert "$initialInputObjects" in script
    assert "$allowedFinalKeys = @($expectedInitial" in script


def test_live_repair_implementer_generates_patch_with_git_diff() -> None:
    script = (DEPLOY / "run-live-repair.ps1").read_text(encoding="utf-8")

    assert "git diff --check" in script
    assert (
        'git diff --no-ext-diff -- "$changedPath" '
        '> "$implementerRoot/repair.patch"'
    ) in script
    assert "Do not hand-write unified diff hunk headers" in script


def test_live_repair_dispatches_assignment_objects_without_nested_base64() -> None:
    script = (DEPLOY / "run-live-repair.ps1").read_text(encoding="utf-8")

    assert "function New-CoPawSendObjectCommand" in script
    assert "--text \"`$(mc cat '$ObjectPath')\"" in script
    assert "$verifierDispatchCommand = New-CoPawSendObjectCommand" in script
    assert "$implementerDispatchCommand = New-CoPawSendObjectCommand" in script
    assert '-ObjectPath "$remoteTaskRoot/assignments/verifier.txt"' in script
    assert '-ObjectPath "$remoteTaskRoot/assignments/implementer.txt"' in script
    assert "$verifierDispatchCommand = New-CoPawSendCommand" not in script
    assert "$implementerDispatchCommand = New-CoPawSendCommand" not in script


def test_live_repair_run_evidence_projects_only_public_role_event_fields() -> None:
    script = (DEPLOY / "run-live-repair.ps1").read_text(encoding="utf-8")

    save_evidence = script[script.index("function Save-RunEvidence") :]
    save_evidence = save_evidence[: save_evidence.index("$resolvedCaseRoot")]
    assert "$eventEvidence += $Markers[$key]" not in save_evidence
    assert "$marker = $Markers[$key]" in save_evidence
    for field in (
        "key = $marker.key",
        "agentName = $marker.agentName",
        "sender = $marker.sender",
        "eventId = $marker.eventId",
        "roomId = $marker.roomId",
        "originServerTimestamp = $marker.originServerTimestamp",
    ):
        assert field in save_evidence
    assert "phase = $marker.phase" not in save_evidence
    assert "mentionedAgent = $marker.mentionedAgent" not in save_evidence
    assert "mentionedUserId = $marker.mentionedUserId" not in save_evidence


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
    assert "decision-template-approved.json" in script
    assert "decision-template-rejected.json" in script
    assert "function Get-ManagerSession" in script
    assert '"HICLAW_MANAGER_PASSWORD"' in script
    assert "$login.user_id -ne $Manager.matrixUserID" in script
    assert "function Get-AdminSession" in script
    assert '"HICLAW_ADMIN_PASSWORD"' in script
    assert "function Ensure-ManagerTeamRoomMembership" in script
    assert 'send/m.room.member' not in script
    assert '"/_matrix/client/v3/rooms/$roomSegment/invite"' in script
    assert '"/_matrix/client/v3/join/$roomSegment"' in script
    assert "[int]$_.Exception.Response.StatusCode -ne 404" in script
    assert "-AdminAccessToken $adminSession.token" in script
    assert "-ManagerAccessToken $managerSession.token" in script
    assert "-ExpectedSender $resources.manager.matrixUserID" in script
    assert script.count(
        "$adminSession = Get-AdminSession -Manager $resources.manager"
    ) == 2
    assert "-accessToken $adminSession.token -Body $null" in script
    assert "function Send-ManagerApprovalRequest" in script
    assert "-RoomId $resources.team.teamRoomID" in script
    assert "-RequestBody $requestBody -accessToken $managerSession.token" in script
    assert '"copaw", "channels", "send"' not in script
    assert "function Send-ManagerApprovalPrompt" not in script
    assert "[switch]$ConfirmModelRun" not in script
    assert "L2 approval preparation can spend model quota" not in script
    assert "function Wait-ExactManagerRequest" in script
    assert "$requestEvent = Wait-ExactManagerRequest" in script
    assert "[ValidateRange(1, 300)][int]$TimeoutSeconds = 30" in script
    assert "-TimeoutSeconds 30" in script
    assert "L3" not in script
    assert "initialPassword" not in script
    assert "Write-Output $accessToken" not in script
    assert "grant signature" not in script.lower()
