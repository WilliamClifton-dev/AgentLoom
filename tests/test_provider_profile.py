import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "agentteams" / "configure-openai-compatible-provider.ps1"
EXAMPLE_PROFILE = (
    ROOT / "deploy" / "agentteams" / "provider-profiles" / "example.json"
)


def valid_profile(**overrides: object) -> dict[str, object]:
    profile: dict[str, object] = {
        "schemaVersion": "agentloom.provider-profile/v1alpha1",
        "providerId": "custom-example",
        "displayName": "Example OpenAI-compatible provider",
        "baseUrl": "https://api.example.com/v1",
        "modelId": "example/model-1",
        "apiKeyEnvironmentVariable": "EXAMPLE_API_KEY",
        "generate": {"temperature": 0.1, "maxTokens": 4096},
    }
    profile.update(overrides)
    return profile


def run_validation(
    tmp_path: Path,
    profile: dict[str, object],
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    profile_path = tmp_path / "provider.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    environment = os.environ.copy()
    environment["EXAMPLE_API_KEY"] = "test-secret-must-not-appear"
    return subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(SCRIPT),
            "-ProfilePath",
            str(profile_path),
            "-ValidateOnly",
            *arguments,
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )


def test_tracked_example_profile_is_valid_and_secret_free() -> None:
    environment = os.environ.copy()
    environment.pop("EXAMPLE_API_KEY", None)

    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(SCRIPT),
            "-ProfilePath",
            str(EXAMPLE_PROFILE),
            "-ValidateOnly",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "schemaVersion": "agentloom.provider-profile/v1alpha1",
        "providerId": "custom-example",
        "displayName": "Example OpenAI-compatible provider",
        "baseUrl": "https://api.example.com/v1",
        "modelId": "example/model-1",
        "apiKeyEnvironmentVariable": "EXAMPLE_API_KEY",
        "containers": [
            "hiclaw-manager",
            "hiclaw-worker-agentloom-investigator",
            "hiclaw-worker-agentloom-implementer",
            "hiclaw-worker-agentloom-verifier",
        ],
        "connectionTestRequested": False,
        "validated": True,
    }


def test_valid_profile_is_model_free_and_redacted(tmp_path: Path) -> None:
    result = run_validation(tmp_path, valid_profile())

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output == {
        "schemaVersion": "agentloom.provider-profile/v1alpha1",
        "providerId": "custom-example",
        "displayName": "Example OpenAI-compatible provider",
        "baseUrl": "https://api.example.com/v1",
        "modelId": "example/model-1",
        "apiKeyEnvironmentVariable": "EXAMPLE_API_KEY",
        "containers": [
            "hiclaw-manager",
            "hiclaw-worker-agentloom-investigator",
            "hiclaw-worker-agentloom-implementer",
            "hiclaw-worker-agentloom-verifier",
        ],
        "connectionTestRequested": False,
        "validated": True,
    }
    assert "test-secret-must-not-appear" not in result.stdout
    assert "test-secret-must-not-appear" not in result.stderr


@pytest.mark.parametrize(
    ("overrides", "expected_error"),
    [
        ({"baseUrl": "http://api.example.com/v1"}, "HTTPS"),
        ({"baseUrl": "https://localhost/v1"}, "public host"),
        ({"baseUrl": "https://127.0.0.1/v1"}, "public host"),
        ({"providerId": "Bad Provider"}, "providerId"),
        ({"modelId": "model with spaces"}, "modelId"),
        ({"apiKeyEnvironmentVariable": "unsafe-name"}, "environment"),
        ({"generate": {"temperature": 3}}, "temperature"),
        ({"generate": {"maxTokens": 0}}, "maxTokens"),
    ],
)
def test_profile_rejects_unsafe_values_before_external_access(
    tmp_path: Path,
    overrides: dict[str, object],
    expected_error: str,
) -> None:
    result = run_validation(tmp_path, valid_profile(**overrides))

    assert result.returncode != 0
    assert expected_error.lower() in result.stderr.lower()
    assert "test-secret-must-not-appear" not in result.stdout
    assert "test-secret-must-not-appear" not in result.stderr


def test_profile_rejects_unknown_fields_and_embedded_secret(tmp_path: Path) -> None:
    result = run_validation(
        tmp_path,
        valid_profile(apiKey="embedded-secret-must-not-appear"),
    )

    assert result.returncode != 0
    assert "unknown profile field" in result.stderr.lower()
    assert "embedded-secret-must-not-appear" not in result.stdout
    assert "embedded-secret-must-not-appear" not in result.stderr


def test_profile_rejects_unknown_generation_fields(tmp_path: Path) -> None:
    result = run_validation(
        tmp_path,
        valid_profile(generate={"temperature": 0.1, "apiKey": "hidden"}),
    )

    assert result.returncode != 0
    assert "unknown generate field" in result.stderr.lower()
    assert "hidden" not in result.stdout
    assert "hidden" not in result.stderr


def test_profile_rejects_unsafe_container_name(tmp_path: Path) -> None:
    result = run_validation(
        tmp_path,
        valid_profile(),
        "-Containers",
        "docker-desktop",
    )

    assert result.returncode != 0
    assert "containers" in result.stderr.lower()


def test_provider_script_requires_explicit_paid_connection_test() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert "[switch]$RunConnectionTest" in script
    assert "if ($RunConnectionTest)" in script
    assert "SkipConnectionTest" not in script
    assert "Get-SecretFromEnvironment" in script
    assert "Write-Output $secretValue" not in script
    assert "Write-Host $secretValue" not in script
    assert "api_key = $secretValue" in script
    assert 'chat_model = "OpenAIChatModel"' in script
