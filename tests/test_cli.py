from __future__ import annotations

from typer.testing import CliRunner

from agentloom.cli import app


def test_tui_command_exposes_local_case_and_output_options() -> None:
    result = CliRunner().invoke(app, ["tui", "--help"])

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "Launch the local Textual demo control panel" in result.output
    assert "--cases-root" in result.output
    assert "--runs-root" in result.output
