from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_builds_immutable_sandbox_before_full_pytest() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    build_marker = "- name: Build immutable Docker sandbox image"
    test_marker = "- name: Test"

    assert build_marker in workflow
    assert workflow.index(build_marker) < workflow.index(test_marker)

    build_step = workflow[workflow.index(build_marker) : workflow.index(test_marker)]
    assert "deploy/sandbox/build-runner.ps1" in build_step
    assert "AGENTLOOM_TEST_SANDBOX_IMAGE=$imageId" in build_step
    assert "$env:GITHUB_ENV" in build_step

    test_step = workflow[workflow.index(test_marker) :]
    assert "python -m pytest" in test_step
