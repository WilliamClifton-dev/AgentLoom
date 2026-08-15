from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def read_script(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def test_bootstrap_exposes_bounded_lite_and_full_profiles() -> None:
    script = read_script("bootstrap.ps1")

    assert '[ValidateSet("lite", "full")]' in script
    assert (
        '[ValidateSet("none", "qwen", "deepseek", "stepfun", "minimax", "custom")]'
        in script
    )
    assert (
        '[ValidateSet("qwen3.7-plus", "deepseek-v4-flash", '
        '"deepseek-v4-pro", "step-3.7-flash", "MiniMax-M2.5")]'
    ) in script
    assert '[string]$ProviderProfilePath = ""' in script
    assert "[switch]$RunProviderConnectionTest" in script
    assert "$PSScriptRoot" in script
    assert "sys.version_info[:2]" in script
    assert '"3.12"' in script
    assert '"-m", "venv"' in script
    assert "$pythonCommand = @(Resolve-PythonCommand)" in script
    assert "if (Test-Path -LiteralPath $venvPython -PathType Leaf)" in script
    assert "$pythonCommand = @($venvPython)" in script
    assert '"-m", "pip", "install", "--upgrade", "pip>=26.1.2,<27"' in script
    assert script.index('"pip>=26.1.2,<27"') < script.index('"--no-cache-dir"')
    assert '"--retries", "10", "--timeout", "60", "-e"' in script
    assert '"-m", "alembic", "-c"' in script
    assert '"upgrade", "head"' in script
    assert "Push-Location $projectRoot" in script
    assert "Pop-Location" in script


def test_full_bootstrap_fails_closed_and_preserves_provider_order() -> None:
    script = read_script("bootstrap.ps1")

    assert "$PSVersionTable.PSVersion.Major -lt 7" in script
    assert 'Get-Command "docker"' in script
    assert '"info"' in script
    assert '"inspect", "hiclaw-controller"' in script
    assert "QWEN_API_KEY" in script
    assert "DEEPSEEK_API_KEY" in script
    assert "GetEnvironmentVariable" in script
    assert "configure-provider.ps1" in script
    assert "configure-deepseek-provider.ps1" in script
    assert "configure-stepfun-provider.ps1" in script
    assert "configure-minimax-provider.ps1" in script
    assert "configure-openai-compatible-provider.ps1" in script
    assert script.index('"deploy.ps1"') < script.index('"configure-provider.ps1"')
    assert script.index('"deploy.ps1"') < script.index('"configure-deepseek-provider.ps1"')
    assert script.index('"deploy.ps1"') < script.index('"configure-stepfun-provider.ps1"')
    assert script.index('"deploy.ps1"') < script.index('"configure-minimax-provider.ps1"')
    assert script.index('"deploy.ps1"') < script.rindex(
        '"configure-openai-compatible-provider.ps1"'
    )
    assert "$ApiKey" not in script
    assert "api_key =" not in script
    assert "sk-" not in script


def test_custom_bootstrap_validates_profile_before_external_access() -> None:
    script = read_script("bootstrap.ps1")

    validation = '"configure-openai-compatible-provider.ps1") @validationArguments'
    docker_access = 'Get-Command "docker"'
    assert validation in script
    assert script.index(validation) < script.index(docker_access)
    assert '"-ValidateOnly"' in script
    assert "$Model = $customProviderProfile.modelId" in script
    assert "$CustomProviderProfile.apiKeyEnvironmentVariable" in script
    assert "$SkipProviderConnectionTest -and $RunProviderConnectionTest" in script
    assert 'if ($Provider -eq "custom" -and $RunProviderConnectionTest)' in script
    assert '"-RunConnectionTest"' in script


def test_health_check_verifies_runtime_resources_and_writes_redacted_evidence() -> None:
    script = read_script("health-check.ps1")

    assert '"version-lock.json"' in script
    assert '"image", "inspect"' in script
    assert '"hiclaw-controller"' in script
    assert '"get", "managers", "default"' in script
    assert '"get", "teams", "agentloom-repair"' in script
    assert '"get", "workers", "--team", "agentloom-repair"' in script
    assert '"get", "humans", "agentloom-developer"' in script
    assert 'manager.phase -eq "Running"' in script
    assert 'team.phase -eq "Active"' in script
    assert "workers.total -eq 3" in script
    assert 'human.phase -eq "Active"' in script
    assert "team.teamRoomID" in script
    assert 'Add-HealthCheck -Name "matrix-rooms"' in script
    assert "$roomDetail =" in script
    assert "ConvertTo-Json" in script
    assert "EvidencePath" in script
    assert 'failureCode = $failureCode' in script
    assert '"Docker daemon is not reachable."' in script
    assert "initialPassword" not in script
    assert "access_token" not in script
    assert "GetEnvironmentVariable" not in script


def test_demo_entrypoint_is_offline_and_case_bounded() -> None:
    script = read_script("demo.ps1")

    assert (
        '[ValidateSet("severity-normalization", "pagination-boundary", '
        '"retry-delay-cap")]'
    ) in script
    assert '"-m", "agentloom.mock_repair"' in script
    assert '"--case-root"' in script
    assert '"--output-root"' in script
    assert "QWEN_API_KEY" not in script
    assert "DEEPSEEK_API_KEY" not in script


def test_clean_reproduction_is_fresh_redacted_and_fail_closed() -> None:
    script = read_script("verify-clean-reproduction.ps1")

    assert '[ValidateSet("lite", "full")]' in script
    assert '[string]$EvidenceRoot = ""' in script
    assert "Assert-NewDirectory" in script
    assert "Test-Path -LiteralPath $Path" in script
    assert 'throw "EvidenceRoot already exists' in script
    assert '"bootstrap.ps1"' in script
    assert '"demo.ps1"' in script
    assert "Invoke-Checked" in script
    assert '"--no-cache-dir"' in script
    assert '"--retries", "10", "--timeout", "60", "-e"' in script
    assert '"--junitxml"' in script
    assert "failures -ne 0" in script
    assert "errors -ne 0" in script
    assert "ConvertTo-Json" in script
    assert "Get-FileHash" in script
    assert "agentloom.clean-reproduction/v1alpha1" in script
    assert "323 passed" not in script
    assert "继续" not in script


def test_clean_reproduction_full_mode_propagates_prerequisite_failures() -> None:
    script = read_script("verify-clean-reproduction.ps1")

    assert '[ValidateSet("minimax", "stepfun", "custom")]' in script
    assert "MINIMAX_API_KEY" in script
    assert "STEPFUN_API_KEY" in script
    assert 'Get-Command "docker"' in script
    assert '"info"' in script
    assert "docker inspect $container" in script
    assert "requiredContainers" in script
    assert "exit 1" not in script


def test_competition_demo_defaults_to_replay_and_guards_paid_live_run() -> None:
    script = read_script("competition-demo.ps1")

    assert '[ValidateSet("replay", "live")]' in script
    assert '[string]$Mode = "replay"' in script
    assert "ConfirmPaidRun" in script
    assert '"health-check.ps1"' in script
    assert '"run-live-repair.ps1"' in script
    assert '"verify-live"' in script
    assert '"inspect-live"' in script
    assert script.count('"--public-output"') == 2
    assert '"tui"' in script
    assert script.index('"run-live-repair.ps1"') < script.index('"verify-live"')
    assert script.index('"verify-live"') < script.index('"inspect-live"')
    assert "QWEN_API_KEY" not in script
    assert "DEEPSEEK_API_KEY" not in script


def test_competition_rollback_demo_replays_free_and_guards_live_collection() -> None:
    script = read_script("competition-rollback-demo.ps1")

    assert '[ValidateSet("replay", "live")]' in script
    assert '[string]$Mode = "replay"' in script
    assert "ConfirmPaidRun" in script
    assert '"health-check.ps1"' in script
    assert '"run-live-rollback.ps1"' in script
    assert '"configure-provider.ps1"' in script
    assert '"configure-deepseek-provider.ps1"' in script
    assert '"configure-stepfun-provider.ps1"' in script
    assert "-SkipConnectionTest" in script
    assert script.index('"configure-provider.ps1"') < script.index(
        '"run-live-rollback.ps1"'
    )
    assert script.index('"configure-deepseek-provider.ps1"') < script.index(
        '"run-live-rollback.ps1"'
    )
    assert script.index('"configure-stepfun-provider.ps1"') < script.index(
        '"run-live-rollback.ps1"'
    )
    assert '"verify-rollback"' in script
    assert '"inspect-rollback"' in script
    assert '"--rollback-evidence"' in script
    assert "[switch]$PublicOutput" in script
    assert '"--public-output"' in script
    assert script.index('"run-live-rollback.ps1"') < script.index('"verify-rollback"')
    assert "QWEN_API_KEY" not in script
    assert "DEEPSEEK_API_KEY" not in script
