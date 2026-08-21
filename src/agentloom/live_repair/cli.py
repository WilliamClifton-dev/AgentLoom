"""Fail-closed verification for model-generated AgentTeams repair submissions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Literal

AgentName = Literal[
    "agentloom-investigator",
    "agentloom-implementer",
    "agentloom-verifier",
]
ProviderName = Literal["dashscope", "deepseek", "stepfun", "minimax-cn"]
ModelName = Literal[
    "qwen3.7-plus",
    "deepseek-v4-pro",
    "step-3.7-flash",
    "MiniMax-M2.5",
]

_EXPECTED_AGENTS: tuple[AgentName, ...] = (
    "agentloom-investigator",
    "agentloom-implementer",
    "agentloom-verifier",
)
_PROVIDER_MODELS: dict[ProviderName, ModelName] = {
    "dashscope": "qwen3.7-plus",
    "deepseek": "deepseek-v4-pro",
    "stepfun": "step-3.7-flash",
    "minimax-cn": "MiniMax-M2.5",
}
_HIDDEN_WORKSPACE = ".agentloom-hidden-tests"
_MAX_PATCH_BYTES = 131_072
_MAX_SOURCE_FILES = 64
_MAX_SOURCE_BYTES = 1_048_576




from agentloom.live_repair.case import (  # noqa: E402,F401
    _write_case_context,
    prepare_live_repair_case_context,
)
from agentloom.live_repair.verifier import LiveRepairVerifier  # noqa: E402,F401


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare live repair Case inputs")
    subcommands = parser.add_subparsers(dest="command", required=True)
    prepare = subcommands.add_parser("prepare-case")
    prepare.add_argument("--case-root", required=True, type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        context = prepare_live_repair_case_context(arguments.case_root)
        _write_case_context(arguments.output, context)
    except (OSError, RuntimeError, ValueError, UnicodeError) as exc:
        print(f"live repair Case preparation failed: {exc}", file=sys.stderr)
        return 1
    return 0