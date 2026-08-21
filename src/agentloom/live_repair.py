"""Backward-compat re-export shim.

The live_repair module was split into a package on 2026-08-22. Prefer
importing from `agentloom.live_repair` (the package) or from the specific
submodule. This shim keeps every existing `from agentloom.live_repair
import X` call site working without churn.
"""
from agentloom.live_repair import *  # noqa: F401,F403
from agentloom.live_repair import __all__  # noqa: F401
