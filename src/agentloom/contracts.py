"""Backward-compat re-export shim.

The contracts package was split into per-responsibility submodules on 2026-08-21.
Prefer importing from `agentloom.contracts` (the package) or from the
specific submodule (`agentloom.contracts.tool`, `agentloom.contracts.grant`,
etc.). This shim keeps every existing `from agentloom.contracts import X`
call working without code churn at every call site.
"""
from agentloom.contracts import *  # noqa: F401,F403
from agentloom.contracts import __all__  # noqa: F401
