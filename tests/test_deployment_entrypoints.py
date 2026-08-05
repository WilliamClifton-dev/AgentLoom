from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def read_script(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def test_bootstrap_exposes_bounded_lite_and_full_profiles() -> None:
    script = read_script("bootstrap.ps1")

    assert '[ValidateSet("lite", "full")]' in script
    assert '[ValidateSet("none", "qwen", "deepseek")]' in script
    assert '[ValidateSet("qwen3.7-plus", "deepseek-v4-flash", "deepseek-v4-pro")]' in script
    assert "$PSScriptRoot" in script
    assert "sys.version_info[:2]" in script
    assert '"3.12"' in script
    assert '"-m", "venv"' in script
    assert "if (Test-Path -LiteralPath $venvPython -PathType Leaf)" in script
    assert "$pythonCommand = @($venvPython)" in script
    assert '"-m", "pip", "install", "-e"' in script
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
    assert script.index('"deploy.ps1"') < script.index('"configure-provider.ps1"')
    assert script.index('"deploy.ps1"') < script.index('"configure-deepseek-provider.ps1"')
    assert "apiKey" not in script
    assert "sk-" not in script


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

    assert '[ValidateSet("severity-normalization", "pagination-boundary")]' in script
    assert '"-m", "agentloom.mock_repair"' in script
    assert '"--case-root"' in script
    assert '"--output-root"' in script
    assert "QWEN_API_KEY" not in script
    assert "DEEPSEEK_API_KEY" not in script
